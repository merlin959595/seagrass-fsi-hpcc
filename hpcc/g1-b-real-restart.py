#!/usr/bin/env python3
"""G1-B true three-participant FSI restart experiment, isolated and fail-closed.

Source: accepted G1-A job 90739 (10 windows, t=0.00125).
Target: 10 additional windows to physical t=0.0025.
Compare ALL ten interface tip/load points against continuous IQN5 87186.

The result is NOT declared successful unless real independent fluid+solid
processes exit 0, ten windows converge, ALE mesh passes checkMesh, and
all ten interface observables match the continuous reference.

Use --preflight-only on login; use --run only inside an explicit Slurm allocation.
Does not edit 90739, 87186, or 89038. Do not use for production until PASS.
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import traceback

DT=0.000125
OFFSET=0.00125
FINAL=0.0025
N=10
EXPECTED_SOURCE="g1-rout10-job-90739/candidate-10/runs/hpcc-implicit-002"
EXPECTED_BASELINE="implicit-pilot-002-8mpi-timefix-87186/production/runs/hpcc-implicit-002"
CCX_REL="seagrass-implicit-20261111/scripts/native/bin/ccx_preCICE_persistent_v2"
REF_SO_REL="seagrass-implicit-20261111/scripts/native/lib/libseagrassReferenceRestart.so"
QUALITY_NONORTH_MAX=65
TOL=1e-5


def digest(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()


def load(p):
    return json.loads(p.read_text())


def atomic_json(p,obj):
    temp=p.with_suffix(p.suffix+".tmp")
    temp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+"\n")
    temp.replace(p)


def path_inside(child,parent):
    return child==parent or parent in child.parents


def stage_helper(base):
    p=base/"g1-phase-b-stage-config.py"
    if not p.is_file():
        raise RuntimeError(f"Missing stage generator: {p}")
    spec=importlib.util.spec_from_file_location("g1_b_stage_checked",p)
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    if not math.isclose(m.T0,OFFSET) or not math.isclose(m.T1,FINAL):
        raise RuntimeError("Stage generator target time has changed")
    return m


def preflight(base,proposal):
    stage=stage_helper(base)
    a,source,rout,kin,reference,processors=stage.check_a(base)
    if source!=(base/EXPECTED_SOURCE):
        raise RuntimeError(f"Unexpected phase-A source: {source}")
    b=base/EXPECTED_BASELINE
    if not b.is_dir():
        raise RuntimeError("Missing continuous 87186 reference")
    manifest=load(proposal/"G1_PHASE_B_PROPOSAL.json")
    if manifest.get("status")!="G1_PHASE_B_CONFIG_PROPOSED_NOT_RUN":
        raise RuntimeError("Proposal is not a review-only configuration")
    if manifest.get("restart_validated") is not False:
        raise RuntimeError("Proposal improperly declares restart verified")
    if manifest.get("source_run")!=str(source):
        raise RuntimeError("Proposal source mismatch")
    if not (math.isclose(manifest.get("resume_from_absolute_time_s",-1),OFFSET)
            and math.isclose(manifest.get("proposed_to_absolute_time_s",-1),FINAL)):
        raise RuntimeError("Proposal physical time mismatch")
    for path,expected in manifest["proposed_files_sha256"].items():
        p=proposal/path
        if not p.is_file() or digest(p)!=expected:
            raise RuntimeError(f"Proposal file tampered or missing: {p}")
    if set(manifest["proposed_files_sha256"])!={
            "solid/seagrass.inp","fluid/system/controlDict",
            "fluid/system/preciceDict","precice-config.xml"}:
        raise RuntimeError("Unexpected proposal files")
    if digest(rout)!=manifest["structural_restart_sha256"]:
        raise RuntimeError("Solid .rout checksum mismatch")
    if digest(kin)!=manifest["kinematic_state_sha256"]:
        raise RuntimeError("Solid persistent state checksum mismatch")
    if digest(reference)!=manifest["reference_coords_sha256"]:
        raise RuntimeError("Solid coupling reference checksum mismatch")
    xml=(proposal/"precice-config.xml").read_text()
    ctrl=(proposal/"fluid/system/controlDict").read_text()
    deck=(proposal/"solid/seagrass.inp").read_text()
    foam_precice=(proposal/"fluid/system/preciceDict").read_text()
    if xml.count('limit="1e-05"')!=2:
        raise RuntimeError("Convergence tolerances not frozen")
    if '<time-windows-reused value="5"' not in xml:
        raise RuntimeError("G1 compare must use IQN5")
    if '<max-time value="0.00125"' not in xml:
        raise RuntimeError("New preCICE session must end after ten local windows")
    for expected in ("startFrom latestTime;","endTime 0.0025;","deltaT 0.000125;"):
        if expected not in ctrl:
            raise RuntimeError(f"OpenFOAM resume configuration mismatch: {expected}")
    if not deck.lstrip().startswith("*RESTART,READ,STEP=1"):
        raise RuntimeError("CalculiX must restart from saved step 1")
    if "restartFromDeformed true;" not in foam_precice:
        raise RuntimeError("Missing explicit fluid FSI restart reference policy")
    if len(processors)!=8:
        raise RuntimeError("Unexpected fluid rank count")
    c=base/CCX_REL
    so=base/REF_SO_REL
    for x in (c,so):
        if not x.is_file():
            raise RuntimeError(f"Required custom native component missing: {x}")
    binding=load(source/"INPUT_BINDING.json")
    original_binary_hash=binding.get("binary_sha256")
    if original_binary_hash and digest(c)!=original_binary_hash:
        raise RuntimeError("CalculiX executable changed since G1-A")
    return source,b,c,so,rout,kin,reference,manifest


def stage_case(base,proposal,work):
    source,baseline,ccx,so,rout,kin,ref,manifest=preflight(base,proposal)
    forbidden=[base/"g1-rout10-job-90739",base/"implicit-pilot-002-8mpi-timefix-87186",
               base/"performance-full160-job-89038",base/"seagrass-implicit-20261111",
               proposal]
    if any(path_inside(work,x) or path_inside(x,work) for x in forbidden):
        raise RuntimeError("Work path overlaps frozen sources / proposal")
    if work.exists():
        raise FileExistsError(f"Refusing to reuse existing run: {work}")
    work.mkdir(parents=True)
    dst=work/"runs/hpcc-implicit-002"
    dst.parent.mkdir()
    shutil.copytree(source,dst,symlinks=False)
    # Never modify source. Remove previous output / preCICE log files ONLY in COPY.
    # Preserve reference coordinates, fluid processor checkpoints, static fields.
    for child in dst.rglob("*"):
        if not child.is_file():
            continue
        name=child.name
        if (name.startswith("precice-") and
            (name.endswith(".log") or name.endswith(".json") or name.endswith(".csv"))):
            child.unlink()
    for d in sorted(dst.rglob("precice-profiling"),reverse=True):
        if d.is_dir():
            shutil.rmtree(d)
    for child in dst.glob("*.log"):
        child.unlink()
    solid=dst/"solid"
    for pat in ("seagrass.dat","seagrass.cvg","seagrass.frd","seagrass.sta",
                "seagrass.12d","spooles.out"):
        (solid/pat).unlink(missing_ok=True)
    # Retain exact A checkpoint as new input. Prevent stale state/output files
    # from being mistaken for fresh B completion.
    shutil.copy2(solid/"seagrass.rout",solid/"seagrass.rin")
    if digest(solid/"seagrass.rin")!=digest(rout):
        raise RuntimeError("Copied CalculiX restart image checksum mismatch")
    (solid/"seagrass.rout").unlink()
    shutil.copy2(solid/"kinematic_state.bin",solid/"kinematic_state.input.bin")
    if digest(solid/"kinematic_state.input.bin")!=digest(kin):
        raise RuntimeError("Copied solid persistent state checksum mismatch")
    (solid/"kinematic_state.bin").unlink()
    for rel in manifest["proposed_files_sha256"]:
        out=dst/rel
        shutil.copy2(proposal/rel,out)
        if digest(out)!=manifest["proposed_files_sha256"][rel]:
            raise RuntimeError(f"Staged proposal mismatch: {rel}")
    # Verify exactly eight checkpoint folders are still present and unchanged.
    for i in range(8):
        latest=dst/f"fluid/processor{i}/0.00125"
        for rel in ("U","p","phi","pointDisplacement","polyMesh/points","uniform/time"):
            if not (latest/rel).is_file():
                raise RuntimeError(f"Staged fluid checkpoint missing: rank={i} {rel}")
    if digest(dst/"restart_reference/Solid-Mesh.coords")!=digest(ref):
        raise RuntimeError("Reference coordinates changed while staging")
    atomic_json(work/"G1_B_STAGE_EVIDENCE.json",{
        "status":"G1_B_ISOLATED_STAGED_NOT_RUN",
        "source":str(source),"reference_87186":str(baseline),
        "proposal":str(proposal),"fluid_ranks":8,"solid_threads":4,
        "fluid_begin_time":OFFSET,"fluid_target_time":FINAL,
        "precice_new_session_max_time":OFFSET,
        "solid_restart_input_sha256":digest(solid/"seagrass.rin"),
        "solid_state_input_sha256":digest(solid/"kinematic_state.input.bin"),
        "reference_coords_sha256":digest(dst/"restart_reference/Solid-Mesh.coords"),
        "original_90739_untouched":True,"restart_verified":False})
    return dst,baseline,ccx,so


def read_watch(path,quantity):
    lines=path.read_text(errors="replace").splitlines()
    if not lines:
        raise RuntimeError(f"Empty watchpoint: {path}")
    headers=lines[0].split()
    want=["Time"]+[f"{quantity}{i}" for i in range(3)]
    if any(x not in headers for x in want):
        raise RuntimeError(f"Watchpoint missing columns {want}: {headers}")
    observations=[]
    for line in lines[1:]:
        fields=line.split()
        if len(fields)!=len(headers):
            continue
        try:
            values=dict(zip(headers,map(float,fields)))
        except ValueError:
            continue
        if any(not math.isfinite(values[key]) for key in want):
            raise RuntimeError(f"Non-finite {quantity} trajectory")
        observations.append((values["Time"],[values[f"{quantity}{i}"] for i in range(3)]))
    if not observations:
        raise RuntimeError(f"No watchpoint observations: {path}")
    return observations


def at_time(records,t):
    found=[v for x,v in records if abs(x-t)<1e-9]
    if not found:
        raise RuntimeError(f"Missing accepted watchpoint at {t:.9g}")
    return found[-1]


def compare_trajectory(run,reference):
    results={}
    for label,filename,quantity,abs_tol,rel_tol in (
        ("tip","precice-Solid-watchpoint-Blade-Tip.log","Displacement",2e-6,.02),
        ("loads","precice-Solid-watchintegral-Interface-Integral.log","Force",5e-4,.02)):
        actual=read_watch(run/"solid"/filename,quantity)
        baseline=read_watch(reference/"solid"/filename,quantity)
        # Fresh preCICE session may report local [0,T0] times or true
        # physical [T0,2*T0] times. Detect from the FINAL time record.
        max_t=max(t for t,_ in actual)
        if abs(max_t-OFFSET)<1e-9:
            time_mode="local"
            shift=0.
        elif abs(max_t-FINAL)<1e-9:
            time_mode="absolute"
            shift=OFFSET
        else:
            raise RuntimeError(
                f"{label} last watchpoint time={max_t:.9g}; "
                "cannot determine resumed session time convention")
        per_window=[]
        for j in range(1,N+1):
            t_abs=OFFSET+j*DT
            v=at_time(actual,t_abs-shift)
            ref=at_time(baseline,t_abs)
            error=math.dist(v,ref)
            limit=abs_tol+rel_tol*math.sqrt(sum(x*x for x in ref))
            if error>limit or not math.isfinite(error):
                raise RuntimeError(
                    f"G1-B {label} continuity FAIL window {j}: "
                    f"error={error:g} > {limit:g}; observed={v} baseline={ref}")
            per_window.append({"resume_window":j,"physical_time_s":t_abs,
                               "observed":v,"continuous_reference":ref,
                               "difference_norm":error,"acceptance_limit":limit})
        results[label]={"time_mode":time_mode,"windows":per_window}
    return results


def check_iterations(path):
    if not path.is_file():
        raise RuntimeError("Missing new preCICE iterations log")
    rows=[]
    for ln in path.read_text(errors="replace").splitlines()[1:]:
        bits=ln.split()
        if len(bits)!=7:
            continue
        try:
            ints=list(map(int,bits))
        except ValueError:
            continue
        rows.append(ints)
    if len(rows)!=N:
        raise RuntimeError(f"Expected exactly {N} completed new preCICE time windows, got {len(rows)}")
    if [r[0] for r in rows]!=list(range(1,N+1)):
        raise RuntimeError("preCICE iteration window indices not sequential")
    if any(r[1]<1 or r[1]>50 for r in rows):
        raise RuntimeError("preCICE coupling iterations outside 1..50")
    return rows


def run_case(base,proposal,work,max_seconds):
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("--run requires a real Slurm compute allocation")
    if os.environ.get("WM_PROJECT_VERSION")!="v2512":
        raise RuntimeError("OpenFOAM v2512 environment not sourced")
    if shutil.which("precice-config-validate") is None:
        raise RuntimeError("preCICE validation tool unavailable")
    if shutil.which("mpirun") is None:
        raise RuntimeError("No MPI runtime")
    if not Path("/usr/bin/time").is_file():
        raise RuntimeError("/usr/bin/time unavailable")
    run,baseline,ccx,so=stage_case(base,proposal,work)
    fluid=run/"fluid"
    solid=run/"solid"
    state={"status":"G1_B_STAGED","resume_from_time_s":OFFSET,
           "target_time_s":FINAL,"participant_exit_codes":None,
           "restart_verified":False}
    atomic_json(work/"STATE.json",state)
    procs={}
    outs={}
    start=time.monotonic()
    try:
        for participant in ("Fluid","Solid"):
            r=subprocess.run(
                ["precice-config-validate",str(run/"precice-config.xml"),participant],
                cwd=run,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=120)
            (work/f"precice-validate-{participant}.log").write_text(r.stdout+r.stderr)
            if r.returncode:
                raise RuntimeError(f"Invalid preCICE {participant} config; see validation log")
        commands={
            "fluid":["/usr/bin/time","-v","mpirun","--oversubscribe","-np","8",
                     "--bind-to","none","pimpleFoam","-fileHandler","uncollated","-parallel"],
            "solid":["/usr/bin/time","-v",str(ccx),"-i","seagrass",
                     "-precice-participant","Solid"]}
        atomic_json(work/"COMMANDS.json",commands)
        for name,cwd in (("fluid",fluid),("solid",solid)):
            env=os.environ.copy()
            env["OMP_NUM_THREADS"]="4" if name=="solid" else "1"
            env["PYTHONDONTWRITEBYTECODE"]="1"
            if name=="solid":
                env.update({
                    "LD_PRELOAD":str(so),
                    "SG_REFERENCE_MODE":"restore",
                    "SG_REFERENCE_DIR":str(run/"restart_reference"),
                    "SG_PERSISTENT_STATE_IN":str(solid/"kinematic_state.input.bin"),
                    "SG_PERSISTENT_STATE_OUT":str(solid/"kinematic_state.bin"),
                })
            out=(work/f"{name}.log").open("x")
            outs[name]=out
            procs[name]=subprocess.Popen(commands[name],cwd=cwd,env=env,
                stdin=subprocess.DEVNULL,stdout=out,stderr=subprocess.STDOUT,
                start_new_session=True)
        state.update(status="G1_B_RUNNING",
                     participants={name:p.pid for name,p in procs.items()})
        atomic_json(work/"STATE.json",state)
        while any(p.poll() is None for p in procs.values()):
            if time.monotonic()-start>max_seconds:
                raise RuntimeError(f"G1_B_RUNTIME_TIMEOUT_{max_seconds}_seconds")
            failed=[(name,p.returncode) for name,p in procs.items()
                    if p.poll() is not None and p.returncode!=0]
            if failed:
                raise RuntimeError(f"FSI participant failed early: {failed}")
            time.sleep(10)
        exits={name:p.returncode for name,p in procs.items()}
        state.update(participant_exit_codes=exits,wall_s=time.monotonic()-start)
        atomic_json(work/"STATE.json",state)
        if exits!={"fluid":0,"solid":0}:
            raise RuntimeError(f"FSI participants failed: {exits}")
        if not (solid/"kinematic_state.bin").is_file():
            raise RuntimeError("Persistent state NOT REWRITTEN by restarted CalculiX")
        # Previous .rout was deliberately deleted before restart; a fresh,
        # nonempty .rout is required for any later persistent continuation.
        rout=solid/"seagrass.rout"
        if not rout.is_file() or rout.stat().st_size<1024:
            raise RuntimeError("Restarted CalculiX did not emit NEW nonempty .rout")
        rows=check_iterations(solid/"precice-Solid-iterations.log")
        solid_text=(work/"solid.log").read_text(errors="replace")
        fluid_text=(work/"fluid.log").read_text(errors="replace")
        for token in ("Reached end at: final time-window:",):
            if token not in solid_text:
                raise RuntimeError(f"Solid did not report coupling completion: {token}")
        if re.search(r"FOAM FATAL|\bSegmentation fault\b|\*ERROR",fluid_text):
            raise RuntimeError("Fluid log reports solver failure")
        if re.search(r"\bSegmentation fault\b|\*ERROR",solid_text):
            raise RuntimeError("Solid log reports solver failure")
        # Native quality at FINAL deformed mesh, parallel on all eight ranks.
        mesh_cmd=["mpirun","--oversubscribe","-np","8","--bind-to","none",
                  "checkMesh","-case",str(fluid),"-parallel","-fileHandler",
                  "uncollated","-latestTime","-allGeometry","-allTopology","-meshQuality"]
        r=subprocess.run(mesh_cmd,cwd=fluid,stdin=subprocess.DEVNULL,
              capture_output=True,text=True,timeout=1200)
        (work/"terminal-parallel-checkMesh.log").write_text(r.stdout+r.stderr)
        if r.returncode!=0 or "Mesh OK." not in r.stdout or "Failed " in r.stdout:
            raise RuntimeError("Restarted deformed fluid mesh checkMesh failed")
        angle=[float(x) for x in re.findall(
            r"Max non-orthogonality\s*=\s*([\d.]+)",r.stdout)]
        if angle and max(angle)>QUALITY_NONORTH_MAX:
            raise RuntimeError("Nonorthogonality exceeds 65 degrees")
        if "negative volume" in r.stdout.lower():
            raise RuntimeError("CheckMesh reports negative volume")
        trajectory=compare_trajectory(run,baseline)
        evidence={
            "status":"G1_B_10_PLUS_10_COUPLED_RESTART_PASS",
            "g1_a_windows":10,"g1_b_windows":N,
            "continuous_reference_job":"87186",
            "resume_absolute_time_s":OFFSET,
            "final_absolute_time_s":FINAL,
            "participant_exit_codes":exits,
            "coupling_iterations_total":sum(row[1] for row in rows),
            "coupling_iterations_per_resumed_window":[row[1] for row in rows],
            "fresh_structural_rout_sha256":digest(rout),
            "fresh_structural_kinematic_state_sha256":digest(solid/"kinematic_state.bin"),
            "fluid_terminal_mesh_check":"PASS",
            "interface_trajectories":trajectory,
            "wall_s":time.monotonic()-start,
            "allow_long_production":False,
            "notes":"Pass applies only to 10+10 low-deformation windows. Large motion and multiple chained restarts remain unqualified.",
        }
        atomic_json(work/"G1_B_RESULT.json",evidence)
        state.update(status=evidence["status"],restart_verified=True)
        atomic_json(work/"STATE.json",state)
        print("G1_B_REAL_10_PLUS_10_RESTART_PASS",flush=True)
    except BaseException as ex:
        state.update(status="G1_B_FAILED",failure=str(ex),restart_verified=False)
        atomic_json(work/"STATE.json",state)
        traceback.print_exc()
        print("G1_B_FAILED",str(ex),flush=True)
        raise
    finally:
        for name,p in procs.items():
            if p.poll() is None:
                try:os.killpg(p.pid,signal.SIGTERM)
                except ProcessLookupError:pass
        for p in procs.values():
            try:p.wait(timeout=20)
            except subprocess.TimeoutExpired:
                try:os.killpg(p.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                p.wait()
        for out in outs.values():
            out.close()


def self_test():
    # Test time/reference alignment and strict behavior with synthetic records.
    vals=[(i*DT,[i*.001,0.,0.]) for i in range(1,11)]
    assert at_time(vals,4*DT)==[.004,0.,0.]
    try:at_time(vals,12*DT)
    except RuntimeError:pass
    else:raise AssertionError("Missing time accepted")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        f=Path(td)/"watch.log"
        f.write_text("Time Displacement0 Displacement1 Displacement2\n"
                     "0.00125 0.1 0.2 0.3\n")
        v=read_watch(f,"Displacement")
        assert len(v)==1 and v[0][1]==[.1,.2,.3]
        f.write_text("Time Displacement0 Displacement1 Displacement2\n"
                     "0.00125 nan 0.2 0.3\n")
        try:read_watch(f,"Displacement")
        except RuntimeError:pass
        else:raise AssertionError("Non-finite watchpoint accepted")
    assert path_inside(Path("/tmp/a/b"),Path("/tmp/a"))
    assert not path_inside(Path("/tmp/c"),Path("/tmp/a"))
    print("G1_B_REAL_RESTART_STATIC_SELF_TEST_PASS")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base",type=Path,default=Path.home()/"hpcc-fsi")
    p.add_argument("--proposal",type=Path)
    p.add_argument("--work",type=Path)
    p.add_argument("--preflight-only",action="store_true")
    p.add_argument("--run",action="store_true")
    p.add_argument("--max-seconds",type=int,default=10800)
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:
        self_test()
        return
    if a.run==a.preflight_only or a.proposal is None:
        p.error("select exactly one --preflight-only or --run and supply --proposal")
    base=a.base.expanduser().resolve(strict=True)
    proposal=a.proposal.expanduser().resolve(strict=True)
    if not path_inside(proposal,base) or not proposal.is_dir():
        raise RuntimeError("Proposal must be an existing directory under hpcc-fsi")
    source,baseline,ccx,so,rout,kin,ref,manifest=preflight(base,proposal)
    print("G1_B_CROSS_PARTICIPANT_SOURCE_PREFLIGHT_PASS",flush=True)
    if a.preflight_only:
        print("G1_B_NO_SLURM_NO_SOLVER_NO_MUTATION",flush=True)
    else:
        if a.work is None:
            p.error("--run requires --work")
        run_case(base,proposal,a.work.expanduser().resolve(),a.max_seconds)


if __name__=="__main__":
    sys.exit(main())
