#!/usr/bin/env python3
"""Prepare a G1 phase-B restart *configuration proposal* from finished job 90739.

This script deliberately does NOT run a solver, modify frozen cases, copy a
full flow mesh, or claim that restarting all three participants works. It
creates only a NEW, isolated set of candidate control files and a machine-
readable feasibility manifest for code review / subsequent real implementation.

Phase A must prove that a nonempty CalculiX .rout exists.
Continuous 20-window 87186 (IQN5) will be used for B trajectory comparison.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re
import sys

A_REL = "g1-rout10-job-90739/candidate-10"
BASELINE_REL = "implicit-pilot-002-8mpi-timefix-87186/production"
DT = 0.000125
T0 = 10 * DT
T1 = 20 * DT


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1<<20), b""):
            h.update(chunk)
    return h.hexdigest()


def replace_exact(pattern, repl, original, label):
    new, n = re.subn(pattern, repl, original, flags=re.MULTILINE)
    if n != 1:
        raise ValueError(f"{label}: exactly one replacement required, found {n}")
    return new


def make_restart_deck(deck):
    """Official *RESTART,READ first, only the one step block retained.

    Do NOT add mesh/material definitions again. The CCX restart image
    contains the previous step. The custom adapter is not verified here.
    """
    start = list(re.finditer(r"(?im)^\s*\*STEP(?:\s|,)", deck))
    end = list(re.finditer(r"(?im)^\s*\*END\s+STEP\s*$", deck))
    if len(start) != 1 or len(end) != 1 or end[0].start() <= start[0].start():
        raise ValueError("expected exactly one structural STEP...END STEP")
    step = deck[start[0].start():end[0].end()]
    if not re.search(r"(?im)^\s*\*DYNAMIC\s*,\s*DIRECT\s*$", step):
        raise ValueError("missing validated DYNAMIC,DIRECT step")
    if not re.search(r"(?im)^\s*\*RESTART\s*,\s*WRITE\s*,\s*FREQUENCY=1\s*,\s*OVERLAY\s*$", step):
        raise ValueError("phase A did not use STEP-frequency=1 restart write")
    if re.search(r"(?im)^\s*\*RESTART\s*,\s*READ", step):
        raise ValueError("unexpected pre-existing restart READ inside step")
    match = re.search(r"(?im)^\s*\*DYNAMIC\s*,\s*DIRECT[^\n]*\n([^\n]+)", step)
    nums = [float(q.strip()) for q in match.group(1).split(",")[:2]]
    if not (math.isclose(nums[0], DT, abs_tol=1e-12)
            and math.isclose(nums[1], T0, abs_tol=1e-10)):
        raise ValueError(f"unexpected CCX time increments {nums}")
    return "*RESTART,READ,STEP=1\n" + step + "\n"


def make_restart_fluid(control):
    src = re.search(r"\bstartFrom\s+startTime\s*;", control)
    if src is None:
        raise ValueError("expected exactly one startFrom startTime")
    control=replace_exact(r"\bstartFrom\s+startTime\s*;",
                          "startFrom latestTime;",control,"fluid startFrom")
    control=replace_exact(r"\bendTime\s+0\.00125\s*;",
                          "endTime 0.0025;",control,"fluid endTime")
    if not re.search(r"\bdeltaT\s+0\.000125\s*;",control):
        raise ValueError("fluid deltaT mismatch")
    if "restartFromDeformed" in control:
        raise ValueError("unexpected restart field in controlDict")
    return control


def make_restart_precice_dict(config):
    """Add one explicit restart option INSIDE the existing FSI block.

    Preserve existing fluid physical properties, solver type and interface
    fields. This does not validate the custom solid restart semantics.
    """
    headers=list(re.finditer(r"(?m)^[ \t]*FSI[ \t]*(?:\r?\n[ \t]*)?\{", config))
    if len(headers)!=1:
        raise ValueError(f"expected exactly one existing FSI block, found {len(headers)}")
    opened=headers[0].end()-1
    depth=0
    close=None
    for index in range(opened,len(config)):
        if config[index]=="{":
            depth+=1
        elif config[index]=="}":
            depth-=1
            if depth==0:
                close=index
                break
    if close is None:
        raise ValueError("unbalanced FSI block; refusing to modify")

    # Ignore // comments while searching for live assignments.
    def options(text):
        uncommented="\n".join(line.split("//",1)[0]
                              for line in text.splitlines())
        return list(re.finditer(r"\brestartFromDeformed\s+(\w+)\s*;",uncommented))

    all_opts=options(config)
    fsi_opts=options(config[opened+1:close])
    if all_opts:
        if len(all_opts)!=1 or len(fsi_opts)!=1 or all_opts[0].group(1)!="true":
            raise ValueError("conflicting, duplicate, or misplaced restartFromDeformed option")
        return config

    return (config[:opened+1]
            + "\n    restartFromDeformed true;"
            + config[opened+1:])

def safe_json(path):
    return json.loads(path.read_text())


def check_a(base):
    a=base/A_REL
    run=a/"runs/hpcc-implicit-002"
    s=safe_json(a/"STATE.json")
    ev=safe_json(a/"G1_RESTART_WRITE_EVIDENCE.json")
    baseline=safe_json(base/BASELINE_REL/"STATE.json")
    if (s.get("status")!="SHORT_FSI_PERFORMANCE_PASS"
        or s.get("accepted_windows")!=10
        or s.get("participant_exit_codes")!={"fluid":0,"solid":0}):
        raise ValueError("phase A did not finish 10 windows with both participants")
    if ev.get("status")!="G1_PHASE_A_RESTART_FILE_PRESENT_NOT_RESTART_VERIFIED":
        raise ValueError("phase A restart-write proof absent")
    if ev.get("restart_verified") is not False:
        raise ValueError("phase A improperly claims full restart")
    if (baseline.get("status")!="HPCC_0P02_IMPLICIT_PASS_RESTART_UNVERIFIED"
        or baseline.get("accepted_windows")!=160):
        raise ValueError("continuous IQN5 reference 87186 missing")
    b=run/"solid/seagrass.rout"
    if not b.is_file() or b.stat().st_size < 1024:
        raise ValueError("structural restart image missing")
    if sha(b)!=ev.get("solid_restart_sha256"):
        raise ValueError("structural restart image hash changed")
    k=run/"solid/kinematic_state.bin"
    if not k.is_file() or k.stat().st_size==0:
        raise ValueError("kinematic state missing")
    ref=run/"restart_reference/Solid-Mesh.coords"
    if not ref.is_file() or ref.stat().st_size==0:
        raise ValueError("interface reference coordinates missing")
    p=run/"fluid"
    procs=[p/f"processor{n}" for n in range(8)]
    if not all(q.is_dir() for q in procs):
        raise ValueError("missing MPI processor directory")
    records=[]
    for i,q in enumerate(procs):
        folders=[]
        for child in q.iterdir():
            if not child.is_dir():
                continue
            try:
                t=float(child.name)
                if math.isfinite(t):
                    folders.append((t,child))
            except ValueError:
                pass
        if not folders or not math.isclose(max(t for t,c in folders),T0,abs_tol=1e-10):
            raise ValueError(f"processor{i} final 10-window time absent or mismatched")
        fin=max(folders,key=lambda x:x[0])[1]
        for field in ("U","p","phi","pointDisplacement","polyMesh/points","uniform/time"):
            if not (fin/field).is_file():
                raise ValueError(f"processor{i} checkpoint missing: {field}")
        if not (q/"constant/motionReferenceDiffusivity").is_file():
            raise ValueError(f"processor{i} frozen motion reference missing")
        records.append({
            "processor":i,"final_time":str(fin.relative_to(run)),
            "state_field_names":["U","p","phi","pointDisplacement","polyMesh/points","uniform/time"]
        })
    return a,run,b,k,ref,records


def generate(base,out):
    a,run,b,k,ref,records=check_a(base)
    inputs={
        "solid/seagrass.inp": make_restart_deck((run/"solid/seagrass.inp").read_text()),
        "fluid/system/controlDict": make_restart_fluid((run/"fluid/system/controlDict").read_text()),
        "fluid/system/preciceDict": make_restart_precice_dict((run/"fluid/system/preciceDict").read_text()),
        "precice-config.xml": (run/"precice-config.xml").read_text()
    }
    # Fresh preCICE session has local clock [0,0.00125]; fluid will use
    # absolute time [0.00125,0.0025]. This behavior remains UNVERIFIED.
    xml=inputs["precice-config.xml"]
    if (xml.count('limit="1e-05"')!=2 or
        '<max-time value="0.00125"' not in xml or
        '<time-window-size value="0.000125"' not in xml or
        'coupling-scheme:parallel-implicit' not in xml):
        raise ValueError("preCICE scheme/time/tolerance mismatch")
    proposed={
        "status":"G1_PHASE_B_CONFIG_PROPOSED_NOT_RUN",
        "created_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
        "original_phase_a":str(a),"source_run":str(run),
        "resume_from_absolute_time_s":T0,"proposed_to_absolute_time_s":T1,
        "new_precice_session_local_duration_s":T0,
        "windows_in_resume_session":10,"restart_validated":False,
        "structural_restart_file":str(b),
        "structural_restart_sha256":sha(b),
        "structural_restart_size_bytes":b.stat().st_size,
        "kinematic_state":str(k),"kinematic_state_sha256":sha(k),
        "reference_coords":str(ref),"reference_coords_sha256":sha(ref),
        "fluid_processor_checkpoint_fields":records,
        "design_assumptions_unverified":[
            "Does custom ccx_preCICE_persistent_v2 support RESTART READ with SG_PERSISTENT_STATE_IN?",
            "Does *RESTART,READ preserve initial model and internal load/reference state?",
            "Does adapter launch new preCICE local time 0 with Fluid physical time 0.00125?",
            "Does OpenFOAM restartFromDeformed true match custom solid absolute displacement?",
            "Are all eight OpenFOAM processor fields and ALE history restored without duplication?",
            "Does preCICE coupling mapping remain consistent with restored reference coordinates?",
            "IQN history is reset in new session; trajectory must be compared to continuous 87186.",
        ],
        "forbidden_operations":[
            "NO immediate Slurm or solver launch",
            "NO mutation of original 87186 / 89038 / 90739",
            "NO claim of three-participant coupled restart",
        ],
        "proposed_files_sha256":{},
    }
    if out.exists():
        raise FileExistsError(f"Refusing existing staging directory {out}")
    # Do not allow writing under any frozen or source tree.
    forbidden=[
        (base/v).resolve() for v in (
            A_REL, BASELINE_REL, "performance-full160-job-89038",
            "seagrass-implicit-20261111")
    ]
    if any(out.is_relative_to(protected) for protected in forbidden):
        raise ValueError("G1 phase B staging cannot touch frozen input or result trees")
    out.mkdir(parents=True)
    for name,data in inputs.items():
        path=out/name
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open("x") as f:
            f.write(data)
        proposed["proposed_files_sha256"][name]=sha(path)
    with (out/"G1_PHASE_B_PROPOSAL.json").open("x") as f:
        json.dump(proposed,f,indent=2,ensure_ascii=False)
        f.write("\n")
    return proposed


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base",type=Path,default=Path.home()/"hpcc-fsi")
    p.add_argument("--out",type=Path)
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:
        d=("*NODE, NSET=ALL\n1,0,0,0\n*STEP,INC=80,NLGEOM\n"
           "*DYNAMIC,DIRECT\n0.000125, 0.00125\n*NODE FILE,FREQUENCY=10\n"
           "U\n*RESTART,WRITE,FREQUENCY=1,OVERLAY\n*END STEP\n")
        expected=make_restart_deck(d)
        assert expected.startswith("*RESTART,READ,STEP=1\n*STEP")
        assert "*NODE, NSET=ALL" not in expected
        assert "*RESTART,WRITE,FREQUENCY=1,OVERLAY" in expected
        assert "*NODE FILE,FREQUENCY=10" in expected
        new=make_restart_fluid(
            "startFrom startTime; startTime 0; endTime 0.00125; deltaT 0.000125;\n")
        assert "startFrom latestTime;" in new and "endTime 0.0025;" in new
        actual_precice_dict = (
            "FoamFile { version 2.0; }\n"
            "preciceConfig \"../precice-config.xml\";\n"
            "FSI\n{\n    solverType incompressible;\n"
            "    // Keep these physical values\n"
            "    rho rho [1 -3 0 0 0 0 0] 1000;\n"
            "}\n"
            "interfaces\n{\n"
            "    DisplacementInterface { readData (Displacement); }\n"
            "}\n"
        )
        edited = make_restart_precice_dict(actual_precice_dict)
        assert edited.count("FSI\n{")==1
        assert edited.count("restartFromDeformed true;")==1
        assert "solverType incompressible;" in edited
        assert "rho rho [1 -3 0 0 0 0 0] 1000;" in edited
        assert "DisplacementInterface { readData (Displacement); }" in edited
        assert make_restart_precice_dict(edited) == edited
        inline = make_restart_precice_dict("FSI { solverType incompressible; }\n")
        assert "restartFromDeformed true;" in inline
        assert "solverType incompressible;" in inline
        for invalid in (
            "FoamFile{}\ninterfaces{}\n",
            "FSI {}\nFSI {}\n",
            "FSI { restartFromDeformed false; }\n",
            "FSI { restartFromDeformed true; restartFromDeformed true; }\n",
        ):
            try:
                make_restart_precice_dict(invalid)
            except ValueError:
                pass
            else:
                raise AssertionError(f"Unsafe FSI dictionary accepted: {invalid!r}")
        print("G1_B_CONFIG_STAGE_STATIC_SELF_TEST_PASS")
        return
    if a.out is None:
        p.error("--out is required unless --self-test")
    base=a.base.expanduser().resolve(strict=True)
    out=a.out.expanduser().resolve()
    r=generate(base,out)
    print("G1_PHASE_B_CONFIG_STAGE_ONLY_COMPLETE")
    print("PROPOSAL_PATH:",out/"G1_PHASE_B_PROPOSAL.json")
    print("STRUCTURAL_RESTART_FILE_INTEGRITY=PASS")
    print("EIGHT_FLUID_PROCESSOR_CHECKPOINTS=PASS")
    print("NEW_PRESCRIBED_CONFIG_FILES=4")
    print("G1_THREE_PARTICIPANT_RESTART=UNVERIFIED")
    print("NO_SLURM_NO_SOLVER_NO_FROZEN_MUTATION")


if __name__=="__main__":
    sys.exit(main())
