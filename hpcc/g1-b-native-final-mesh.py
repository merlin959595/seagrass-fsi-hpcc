#!/usr/bin/env python3
"""G1-B 90873 independent native checkMesh + checkpoint advancement gate.

Only runs OpenFOAM checkMesh (NO FSI, NO mesh writes) on already completed
mesh. All artifacts are written under --out-dir, NEVER under 90873/90739.
Use --self-test anywhere; --preflight-only on login; --run in Slurm container.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time

END=0.0025
START=0.00125
RUN_REL="g1-b10-job-90873/runs/hpcc-implicit-002"
SRC_REL="g1-rout10-job-90739/candidate-10/runs/hpcc-implicit-002"


def digest(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def checkpoint_check(base):
    run=base/RUN_REL
    src=base/SRC_REL
    solid=run/"solid"
    files={
        "90739_rout":src/"solid/seagrass.rout",
        "90873_input_rin":solid/"seagrass.rin",
        "90873_new_rout":solid/"seagrass.rout",
        "90739_kinematic":src/"solid/kinematic_state.bin",
        "90873_input_kinematic":solid/"kinematic_state.input.bin",
        "90873_new_kinematic":solid/"kinematic_state.bin",
    }
    meta={}
    for key,p in files.items():
        if not p.is_file() or p.stat().st_size<1024:
            raise RuntimeError(f"Missing/empty checkpoint file: {key}: {p}")
        meta[key]={"bytes":p.stat().st_size,"sha256":digest(p)}
    def sha(k):return meta[k]["sha256"]
    if sha("90739_rout")!=sha("90873_input_rin"):
        raise RuntimeError("Frozen CalculiX restart image changed between source and input")
    if sha("90739_kinematic")!=sha("90873_input_kinematic"):
        raise RuntimeError("Frozen kinematic input changed between source and input")
    # Byte-identical means unchanged state; a future chained restart would be
    # unsafe even though a single 10+10 run appeared to converge.
    advanced_rout=sha("90873_input_rin")!=sha("90873_new_rout")
    advanced_kin=sha("90873_input_kinematic")!=sha("90873_new_kinematic")
    if not advanced_rout or not advanced_kin:
        raise RuntimeError("Output restart checkpoint is byte-identical to input: "
                           f"rout_advanced={advanced_rout}, kinematic_advanced={advanced_kin}")
    state=json.loads((base/"g1-b10-job-90873/STATE.json").read_text())
    if state.get("participant_exit_codes")!={"fluid":0,"solid":0}:
        raise RuntimeError("FSI participant exits were not clean")
    for rank in range(8):
        proc=run/f"fluid/processor{rank}"
        if not proc.is_dir():
            raise RuntimeError(f"Missing rank {rank}")
        numeric_times=[]
        for p in proc.iterdir():
            if p.is_dir():
                try:
                    t=float(p.name)
                    if math.isfinite(t):numeric_times.append((t,p))
                except ValueError:pass
        if not numeric_times:
            raise RuntimeError(f"No fluid time directories at processor {rank}")
        t,folder=max(numeric_times,key=lambda a:a[0])
        if abs(t-END)>1e-9:
            raise RuntimeError(f"Unexpected latest time rank {rank}: {t}")
        for f in ("U","p","phi","pointDisplacement","polyMesh/points","uniform/time"):
            if not (folder/f).is_file():
                raise RuntimeError(f"Missing final checkpoint field: rank {rank}: {f}")
    return {"checkpoint_files":meta,
            "solid_restart_image_advanced":advanced_rout,
            "solid_kinematic_state_advanced":advanced_kin,
            "all_8_mpi_final_fields_present":True}


def inspect_mesh_log(txt,rc):
    """Fail closed; run checkMesh -parallel -latestTime -allGeometry -allTopology."""
    errors=[]
    if rc!=0:errors.append(f"checkMesh process exit {rc}")
    # Use checkMesh's final report, not intermediate quality warnings.
    if not re.search(r"(?m)^\s*Mesh OK\.\s*$",txt):
        errors.append("Missing native final Mesh OK.")
    for m in re.finditer(r"(?mi)^\s*Failed\s+(\d+)\s+mesh checks?",txt):
        if int(m.group(1))>0:errors.append(m.group(0).strip())
    fatal=re.search(r"FOAM FATAL|Floating point exception|Segmentation fault",txt,re.I)
    if fatal:errors.append("Native checkMesh fatal marker")
    # Nonorthogonality in allGeometry log varies by version; if present it
    # must not exceed the frozen 65deg limit. If absent, mark unmeasured.
    nonorth=[float(x) for x in re.findall(
        r"(?i)(?:Max\s+non-orthogonality|maximum\s+non-orthogonality)\s*(?:=|:)\s*([\d.]+)",
        txt)]
    if nonorth and max(nonorth)>65:errors.append("Max nonorthogonality >65 degrees")
    volume=[float(x) for x in re.findall(
        r"(?i)Min(?:imum)?\s+volume\s*(?:=|:)\s*([+-]?[\d.eE+-]+)",txt)]
    if volume and min(volume)<=0:errors.append("Nonpositive native min volume")
    return {"status":"PASS" if not errors else "FAIL","exit_code":rc,
            "mesh_ok_record":bool(re.search(r"(?m)^\s*Mesh OK\.\s*$",txt)),
            "max_nonorthogonality_deg":max(nonorth) if nonorth else None,
            "min_volume_m3":min(volume) if volume else None,"errors":errors,
            "note":"Only quantities exposed by checkMesh output are reported; absent metrics are not invented."}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base",type=Path,default=Path.home()/"hpcc-fsi")
    p.add_argument("--out-dir",type=Path)
    p.add_argument("--preflight-only",action="store_true")
    p.add_argument("--run",action="store_true")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:
        ok=inspect_mesh_log("Mesh OK.\n",0)
        assert ok["status"]=="PASS" and ok["max_nonorthogonality_deg"] is None
        assert inspect_mesh_log("Failed 2 mesh checks\n",0)["status"]=="FAIL"
        assert inspect_mesh_log("Mesh OK.\n",1)["status"]=="FAIL"
        assert inspect_mesh_log("Max non-orthogonality = 67.1\nMesh OK.\n",0)["status"]=="FAIL"
        print("G1_B_NATIVE_CHECKMESH_STATIC_SELF_TEST_PASS")
        return
    if a.run==a.preflight_only:
        p.error("select exactly one of --preflight-only and --run")
    base=a.base.expanduser().resolve(strict=True)
    checks=checkpoint_check(base)
    print("G1_B_RESTART_CHECKPOINT_ADVANCEMENT_PASS",flush=True)
    print("FLUID_EIGHT_RANK_FINAL_FIELDS_PRESENT",flush=True)
    if a.preflight_only:
        print("NO_SLURM_NO_SOLVER_NO_FROZEN_MUTATION",flush=True)
        return
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("Native mesh check requires a Slurm job ID")
    if a.out_dir is None:p.error("--run requires --out-dir")
    dest=a.out_dir.expanduser().resolve()
    work=base/"g1-b10-job-90873"
    source=base/"g1-rout10-job-90739"
    for forbidden in (work,source,base/"implicit-pilot-002-8mpi-timefix-87186",
                      base/"performance-full160-job-89038"):
        if dest==forbidden or forbidden in dest.parents or dest in forbidden.parents:
            raise RuntimeError("Output directory overlaps frozen cases")
    dest.mkdir(parents=False,exist_ok=False)
    original_files={}
    # Snapshot all 8 final polyMesh and pointDisplacement hashes before
    # running a read-only OpenFOAM mesh utility.
    run=base/RUN_REL
    for i in range(8):
        for rel in ("polyMesh/points","pointDisplacement"):
            path=run/f"fluid/processor{i}/{END:g}"/rel
            original_files[str(path)]=digest(path)
    commands=["mpirun","--oversubscribe","-np","8","--bind-to","none",
              "checkMesh","-case",str(run/"fluid"),"-parallel",
              "-fileHandler","uncollated","-latestTime",
              "-allGeometry","-allTopology","-meshQuality"]
    start=time.monotonic()
    result=subprocess.run(commands,cwd=dest,stdin=subprocess.DEVNULL,
                          capture_output=True,text=True,timeout=1800)
    output=result.stdout+"\n"+result.stderr
    (dest/"native-checkMesh.log").write_text(output)
    mesh=inspect_mesh_log(output,result.returncode)
    for path,expected in original_files.items():
        if digest(Path(path))!=expected:
            mesh["status"]="FAIL"
            mesh["errors"].append(f"Original case hash changed: {path}")
    summary={
        "status":"G1_B_90873_NATIVE_FINAL_MESH_PASS"
                 if mesh["status"]=="PASS" else "G1_B_90873_NATIVE_FINAL_MESH_FAIL",
        "time_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
        "job":"90873",
        "original_job_state_left_unchanged":True,
        "source_state_integrity":checks,
        "native_mesh":mesh,
        "runtime_seconds":time.monotonic()-start,
        "checkMesh_command":commands,
        "note":"Does not authorize large displacement/chained 3-day production; only latest 0.0025s mesh and checkpoint advancement.",
    }
    (dest/"G1_B_NATIVE_FINAL_EVIDENCE.json").write_text(
        json.dumps(summary,indent=2,ensure_ascii=False)+"\n")
    print(summary["status"],flush=True)
    print("RESULT",dest/"G1_B_NATIVE_FINAL_EVIDENCE.json",flush=True)
    if mesh["status"]!="PASS":
        raise SystemExit(2)


if __name__=="__main__":
    main()
