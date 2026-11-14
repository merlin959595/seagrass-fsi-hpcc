#!/usr/bin/env python3
"""Real long-run 3D FSI segment, auto-chainable; no new numerical method.

Stage 0: continue validated 90873 at t=0.0025 s.
Later stages: consume ONLY successful previous stage with intact checkpoints.
Starts Fluid and Solid simultaneously in a fresh preCICE session and checks
coupling convergence, native mesh, Courant and checkpoint advancement. Each
stage ends normally to write CalculiX .rout; Slurm dependency stops on failure.
No staged data or physics inputs are modified in place.
"""
import argparse
import datetime as dt
import hashlib
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
MAX_ITER=50
MAX_CO=.5
MAX_NONORTH=65
END_G1=.0025
EXPECTED_RANKS=8

def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1<<20),b""):h.update(b)
    return h.hexdigest()

def jread(path):
    return json.loads(path.read_text())

def jwrite(path,obj):
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(obj,indent=2,ensure_ascii=False)+"\n")
    tmp.replace(path)

def exact(pattern,repl,source,description):
    result,n=re.subn(pattern,repl,source,flags=re.M)
    if n!=1:raise RuntimeError(f"{description}: expected one replacement, got {n}")
    return result

def latest_time(fluid):
    timestamps=[]
    for rank in range(EXPECTED_RANKS):
        p=fluid/f"processor{rank}"
        if not p.is_dir():raise RuntimeError(f"Missing processor{rank}")
        numeric=[]
        for child in p.iterdir():
            if child.is_dir():
                try:
                    n=float(child.name)
                    if math.isfinite(n):numeric.append((n,child))
                except ValueError:pass
        if not numeric:raise RuntimeError(f"No saved times rank {rank}")
        t,folder=max(numeric,key=lambda item:item[0])
        for field in ("U","p","phi","pointDisplacement","polyMesh/points","uniform/time"):
            if not (folder/field).is_file():
                raise RuntimeError(f"Rank {rank} lacks checkpoint {field}")
        timestamps.append((t,folder))
    if max(t for t,_ in timestamps)-min(t for t,_ in timestamps)>1e-9:
        raise RuntimeError("Fluid MPI checkpoints do not share one time")
    return timestamps[0][0],timestamps

def source_for(base,stage,previous_job):
    if stage==0:
        previous=base/"g1-b10-job-90873"
        reports=sorted(base.glob("g1-b-90873-posthoc-*.json"))
        if not reports:raise RuntimeError("Missing 90873 passed posthoc evidence")
        accepted=any(jread(p).get("status")==
            "G1_B_90873_POSTHOC_EVIDENCE_PASS_NATIVE_MESH_UNVERIFIED"
            for p in reports)
        if not accepted:raise RuntimeError("No verified 90873 10+10 posthoc report")
        expected_t=END_G1
        previous_wall_per_window=1690.2690456761047/10
        next_step=2
    else:
        if not previous_job:raise RuntimeError("Missing previous Slurm job")
        previous=base/f"fsi-long-stage{stage-1}-job{previous_job}"
        evidence=jread(previous/"FSI_SEGMENT_RESULT.json")
        if evidence.get("status")!="FSI_LONG_SEGMENT_PASS":
            raise RuntimeError("Previous chained job was not accepted")
        if evidence.get("stage")!=stage-1:
            raise RuntimeError("Previous stage index mismatch")
        if evidence.get("participant_exit_codes")!={"fluid":0,"solid":0}:
            raise RuntimeError("Previous participant exit status mismatch")
        expected_t=float(evidence["final_time_s"])
        previous_wall_per_window=float(evidence["wall_s"])/int(evidence["accepted_windows"])
        next_step=int(evidence["read_restart_step"])+1
    run=previous/"runs/hpcc-implicit-002"
    if not run.is_dir():
        raise RuntimeError(f"Missing validated source run: {run}")
    t,saved=latest_time(run/"fluid")
    if abs(t-expected_t)>1e-9:
        raise RuntimeError(f"Checkpoint mismatch expected {expected_t} found {t}")
    deck=(run/"solid/seagrass.inp").read_text()
    match=re.search(r"(?mi)^\s*\*RESTART\s*,\s*READ\s*,\s*STEP=(\d+)",deck)
    if not match or int(match.group(1))!=next_step-1:
        raise RuntimeError("CalculiX prior restart step chain not as expected")
    for f in ("solid/seagrass.rout","solid/kinematic_state.bin",
              "restart_reference/Solid-Mesh.coords"):
        if not (run/f).is_file() or (run/f).stat().st_size<1000:
            raise RuntimeError(f"Missing source structural state {f}")
    return previous,run,t,saved,next_step,previous_wall_per_window

def choose_windows(stage,max_windows,seconds_per_window):
    if stage==0:
        if max_windows!=220:raise RuntimeError("First segment must be 220 windows to align next output at 0.03s")
        return 220
    if not math.isfinite(seconds_per_window) or seconds_per_window<=0:
        raise RuntimeError("Missing prior measured wall clock throughput")
    # 60h of estimated wall with 35% slowdown reserve and <=66h hard watchdog.
    budget=int((60*3600)/(seconds_per_window*1.35))
    planned=min(max_windows, (budget//80)*80)
    if planned<80:
        raise RuntimeError("Performance too slow even for an 80-window safe segment")
    return planned

def stage_inputs(base,stage,previous_job,work,max_windows):
    previous,source,start,saved,step,per_win=source_for(base,stage,previous_job)
    n=choose_windows(stage,max_windows,per_win)
    end=start+n*DT
    if work.exists():raise RuntimeError(f"Refusing to reuse work path {work}")
    for f in (previous,source,base/"seagrass-implicit-20261111",
              base/"performance-full160-job-89038"):
        if work==f or f in work.parents or work in f.parents:
            raise RuntimeError("Work path overlaps a frozen original")
    work.mkdir(parents=True)
    dst=work/"runs/hpcc-implicit-002"
    dst.parent.mkdir()
    # Keep only the latest distributed checkpoint, with original case static
    # fields; do not accumulate older history across multi-day stages.
    latest_names={f"processor{i}":saved[i][1].name for i in range(8)}
    def ignore(parent,names):
        p=Path(parent)
        skip=[]
        if p.name in latest_names and p.parent.name=="fluid":
            for name in names:
                try: float(name)
                except ValueError:continue
                if name!=latest_names[p.name]:skip.append(name)
        if p.name in ("fluid","solid"):
            skip +=[x for x in names if x=="precice-profiling"]
        return skip
    shutil.copytree(source,dst,ignore=ignore,symlinks=False)
    for child in dst.rglob("precice-*"):
        if child.is_file() and child.suffix in (".log",".json",".csv"):
            child.unlink()
    for name in ("seagrass.dat","seagrass.cvg","seagrass.frd","seagrass.sta","spooles.out"):
        (dst/"solid"/name).unlink(missing_ok=True)
    for log in dst.glob("*.log"):log.unlink()
    solid=dst/"solid"
    original_rout=sha(solid/"seagrass.rout")
    original_kin=sha(solid/"kinematic_state.bin")
    shutil.copy2(solid/"seagrass.rout",solid/"seagrass.rin")
    shutil.copy2(solid/"kinematic_state.bin",solid/"kinematic_state.input.bin")
    (solid/"seagrass.rout").unlink()
    (solid/"kinematic_state.bin").unlink()
    # Set next explicit CalculiX restart step and duration. No new material
    # or mesh definitions, no changes to physical structure parameters.
    deck=solid/"seagrass.inp"
    txt=deck.read_text()
    txt=exact(r"(?im)^(\s*\*RESTART\s*,\s*READ\s*,\s*STEP=)\d+",
              lambda m:m.group(1)+str(step),txt,"CalculiX restart step")
    def dynamic(match):
        parts=match.group(2).split(",")
        if not math.isclose(float(parts[0]),DT,abs_tol=1e-12):
            raise RuntimeError("Structure dt changed")
        parts[1]=f" {n*DT:.12g}"
        return match.group(1)+",".join(parts)
    txt=exact(r"(?im)^(\s*\*DYNAMIC\s*,\s*DIRECT[^\n]*\n)([^\n]+)",
              dynamic,txt,"structural step duration")
    if not re.search(r"(?im)^\s*\*RESTART\s*,\s*WRITE\s*,\s*FREQUENCY=1\s*,\s*OVERLAY",txt):
        raise RuntimeError("Solid stage lacks end-step output .rout")
    deck.write_text(txt)
    control=dst/"fluid/system/controlDict"
    conf=control.read_text()
    if not re.search(r"\bstartFrom\s+latestTime\s*;",conf):
        raise RuntimeError("Fluid did not use latestTime restart")
    conf=exact(r"(?m)(?<![A-Za-z0-9_])(endTime\s+)([-+.\deE]+)(\s*;)",
               lambda m:m.group(1)+f"{end:.12g}"+m.group(3),
               conf,"fluid absolute endTime")
    # End at 80-step aligned absolute time, ensuring the final distributed
    # time field is saved and earlier outputs do not consume disk indefinitely.
    conf,changes=re.subn(r"(writeControl\s+timeStep\s*;\s*writeInterval\s+)\d+(\s*;)",
                         r"\g<1>80\2",conf)
    if changes!=4:raise RuntimeError(f"Expected 4 writeIntervals; got {changes}")
    conf=exact(r"(purgeWrite\s+)\d+(\s*;)",r"\g<1>2\2",conf,"fluid purgeWrite")
    control.write_text(conf)
    xml=dst/"precice-config.xml"
    doc=xml.read_text()
    doc=exact(r'(<max-time value=")[\d.eE+-]+(")',
              lambda m:m.group(1)+f"{n*DT:.12g}"+m.group(2),
              doc,"new session duration")
    doc=exact(r'(<time-windows-reused value=")(?:5|15)(")',
              r"\g<1>15\2",doc,"IQN15")
    if doc.count('limit="1e-05"')!=2 or "coupling-scheme:parallel-implicit" not in doc:
        raise RuntimeError("Convergence or implicit coupling altered")
    xml.write_text(doc)
    if "restartFromDeformed true;" not in (dst/"fluid/system/preciceDict").read_text():
        raise RuntimeError("Missing restored fluid FSI reference policy")
    meta={
        "status":"STAGED_NOT_RUN",
        "stage":stage,"parent_job":90873 if stage==0 else int(previous_job),
        "parent_run":str(source),"parent_time_s":start,
        "read_restart_step":step,"accepted_windows":n,
        "estimated_previous_wall_s_per_window":per_win,
        "final_time_s":end,
        "solid_input_rin_sha256":original_rout,
        "solid_input_kinematic_sha256":original_kin,
        "no_physical_parameters_modified":True,
        "mpi_fluid":8,"omp_solid":4,"iqn_reuse":15,
        "dt_s":DT,"dual_convergence_tol":1e-5,
        "origin_90873_untouched":True
    }
    jwrite(work/"FSI_SEGMENT_STAGE.json",meta)
    return dst,meta

def accepted_iterations(path,n):
    if not path.is_file():raise RuntimeError("Missing preCICE Solid iterations")
    lines=[line.split() for line in path.read_text(errors="replace").splitlines() if line.strip()]
    hdr=["TimeWindow","TotalIterations","Iterations","Convergence",
         "QNColumns","DeletedQNColumns","DroppedQNColumns"]
    if not lines or lines[0]!=hdr or len(lines)!=n+1:
        raise RuntimeError(f"preCICE iterations count or header error: {len(lines)-1} / {n}")
    allrows=[]
    total=0
    for index,values in enumerate(lines[1:],1):
        try:row=list(map(int,values))
        except ValueError:raise RuntimeError(f"Noninteger window row {index}")
        if len(row)!=7:raise RuntimeError("Incorrect preCICE columns")
        total+=row[2]
        if row[0]!=index or not 1<=row[2]<=MAX_ITER or row[1]!=total or row[3]!=1:
            raise RuntimeError(f"Window {index} did not pass convergence: {row}")
        allrows.append(row)
    return allrows

def quality_from_log(log,end):
    txt=log.read_text(errors="replace")
    matches=re.findall(
       r"SEAGRASS_MESH_GUARD\s+time=([\d.eE+-]+)\s+minVolume=([\d.eE+-]+)"
       r"\s+concave=(\d+)\s+qualityFailed=(\d+)\s+skewFailed=(\d+)"
       r"\s+orthFailed=(\d+)\s+tetFailed=(\d+)",txt)
    if not matches:raise RuntimeError("No in-situ original ALE guard evidence")
    recs=[]
    for data in matches:
        recs.append([float(data[0]),float(data[1])]+[int(x) for x in data[2:]])
    if any(r[1]<=0 or any(r[2:]) for r in recs):
        raise RuntimeError("ALE mesh guard failed during real FSI segment")
    if not any(abs(r[0]-end)<1e-9 for r in recs):
        raise RuntimeError("ALE mesh guard missing final physical time")
    meshco=[float(x) for x in re.findall(r"Mesh Courant Number mean:\s*[\d.eE+-]+\s+max:\s*([\d.eE+-]+)",txt)]
    co=[float(x) for x in re.findall(r"(?<!Mesh )Courant Number mean:\s*[\d.eE+-]+\s+max:\s*([\d.eE+-]+)",txt)]
    if not meshco or not co:
        raise RuntimeError("Missing fluid/mesh Courant histories")
    if max(meshco)>.5 or max(co)>.5:
        raise RuntimeError(f"Courant gate failed: fluid={max(co)} mesh={max(meshco)}")
    return {"max_fluid_Co":max(co),"max_mesh_Co":max(meshco),
            "min_ale_volume_m3":min(r[1] for r in recs),
            "native_guard_checks":len(recs)}

def check_mesh(fluid,work):
    command=["mpirun","--oversubscribe","-np","8","--bind-to","none",
             "checkMesh","-case",str(fluid),"-parallel",
             "-fileHandler","uncollated","-latestTime",
             "-allGeometry","-allTopology","-meshQuality"]
    result=subprocess.run(command,cwd=work,capture_output=True,text=True,timeout=1800)
    txt=result.stdout+"\n"+result.stderr
    (work/"native-final-checkMesh.log").write_text(txt)
    if result.returncode!=0 or not re.search(r"(?m)^\s*Mesh OK\.\s*$",txt):
        raise RuntimeError("Native terminal checkMesh failed (see retained log)")
    if re.search(r"FOAM FATAL|Failed\s+[1-9]\d*\s+mesh checks?",txt,re.I):
        raise RuntimeError("Native terminal mesh failed checks")
    orth=[float(x) for x in re.findall(r"Max non-orthogonality\s*=\s*([\d.]+)",txt)]
    if orth and max(orth)>65:raise RuntimeError("Mesh nonorthogonality exceeds 65")
    return {"status":"PASS","max_nonorthogonality_deg":max(orth) if orth else None}

def run(base,stage,previous_job,work,max_windows,timeout):
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("Real job requires a Slurm allocation")
    if os.environ.get("WM_PROJECT_VERSION")!="v2512":
        raise RuntimeError("OpenFOAM v2512 environment not loaded")
    if not shutil.which("mpirun") or not shutil.which("precice-config-validate"):
        raise RuntimeError("Required OpenMPI/preCICE tools missing")
    start_wall=time.monotonic()
    runfolder,meta=stage_inputs(base,stage,previous_job,work,max_windows)
    state={"status":"STARTING","stage":stage,"restart_from_time_s":meta["parent_time_s"],
           "final_time_s":meta["final_time_s"]}
    jwrite(work/"STATE.json",state)
    fluid=runfolder/"fluid"
    solid=runfolder/"solid"
    ccx=base/"seagrass-implicit-20261111/scripts/native/bin/ccx_preCICE_persistent_v2"
    refso=base/"seagrass-implicit-20261111/scripts/native/lib/libseagrassReferenceRestart.so"
    for binary in (ccx,refso):
        if not binary.is_file():raise RuntimeError(f"Missing native component {binary}")
    for participant in ("Fluid","Solid"):
        p=subprocess.run(["precice-config-validate",
              str(runfolder/"precice-config.xml"),participant],
              cwd=runfolder,capture_output=True,text=True,timeout=120)
        (work/f"precice-{participant}-validation.log").write_text(p.stdout+p.stderr)
        if p.returncode:raise RuntimeError(f"Invalid preCICE {participant} configuration")
    commands={
       "fluid":["/usr/bin/time","-v","mpirun","--oversubscribe","-np","8",
                "--bind-to","none","pimpleFoam","-fileHandler","uncollated","-parallel"],
       "solid":["/usr/bin/time","-v",str(ccx),"-i","seagrass",
                "-precice-participant","Solid"]}
    jwrite(work/"COMMANDS.json",commands)
    procs={}
    handles={}
    try:
        for name,directory in (("fluid",fluid),("solid",solid)):
            env=os.environ.copy()
            env["OMP_NUM_THREADS"]="4" if name=="solid" else "1"
            env["PYTHONDONTWRITEBYTECODE"]="1"
            if name=="solid":
                env.update({
                  "LD_PRELOAD":str(refso),
                  "SG_REFERENCE_MODE":"restore",
                  "SG_REFERENCE_DIR":str(runfolder/"restart_reference"),
                  "SG_PERSISTENT_STATE_IN":str(solid/"kinematic_state.input.bin"),
                  "SG_PERSISTENT_STATE_OUT":str(solid/"kinematic_state.bin"),
                })
            f=(work/f"{name}.log").open("x")
            handles[name]=f
            procs[name]=subprocess.Popen(commands[name],cwd=directory,env=env,
                 stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT,
                 start_new_session=True)
        state["status"]="RUNNING"
        jwrite(work/"STATE.json",state)
        while any(p.poll() is None for p in procs.values()):
            if time.monotonic()-start_wall>=timeout:
                raise RuntimeError("SEGMENT_TIMEOUT_BEFORE_CHECKPOINT")
            failures=[(name,p.returncode) for name,p in procs.items()
                      if p.poll() is not None and p.returncode!=0]
            if failures:raise RuntimeError(f"FSI participant error: {failures}")
            time.sleep(15)
        exits={name:p.returncode for name,p in procs.items()}
        if exits!={"fluid":0,"solid":0}:raise RuntimeError(f"FSI exits invalid: {exits}")
        iters=accepted_iterations(solid/"precice-Solid-iterations.log",meta["accepted_windows"])
        t,saved=latest_time(fluid)
        if abs(t-meta["final_time_s"])>1e-9:
            raise RuntimeError("Fluid latest time not equal accepted preCICE time")
        quality=quality_from_log(work/"fluid.log",t)
        if not (solid/"seagrass.rout").is_file() or not (solid/"kinematic_state.bin").is_file():
            raise RuntimeError("New structural continuation checkpoints missing")
        if (sha(solid/"seagrass.rout")==meta["solid_input_rin_sha256"] or
            sha(solid/"kinematic_state.bin")==meta["solid_input_kinematic_sha256"]):
            raise RuntimeError("Structural restart/kinematic state did not advance")
        check=check_mesh(fluid,work)
        wall=time.monotonic()-start_wall
        result={
           "status":"FSI_LONG_SEGMENT_PASS","stage":stage,
           "parent_job":meta["parent_job"],
           "parent_time_s":meta["parent_time_s"],
           "read_restart_step":meta["read_restart_step"],
           "final_time_s":t,"accepted_windows":meta["accepted_windows"],
           "coupling_iterations":sum(r[2] for r in iters),
           "max_coupling_iterations_per_window":max(r[2] for r in iters),
           "participant_exit_codes":exits,
           "quality":quality,"native_terminal_mesh":check,
           "wall_s":wall,"s_per_window":wall/meta["accepted_windows"],
           "solid_rout_sha256":sha(solid/"seagrass.rout"),
           "solid_kinematic_sha256":sha(solid/"kinematic_state.bin"),
           "scientific_two_periods_verified":False,
           "note":"Approved computation only through stated physical time; two wet oscillations are not inferred."
        }
        jwrite(work/"FSI_SEGMENT_RESULT.json",result)
        state.update(status="FSI_LONG_SEGMENT_PASS",accepted_time_s=t)
        jwrite(work/"STATE.json",state)
        print("FSI_LONG_SEGMENT_PASS",json.dumps({k:result[k] for k in
            ("stage","final_time_s","accepted_windows","wall_s","s_per_window")}),flush=True)
    except BaseException as exc:
        state.update(status="FSI_LONG_SEGMENT_FAILED",failure=str(exc),
                     elapsed_s=time.monotonic()-start_wall)
        jwrite(work/"STATE.json",state)
        print("FSI_LONG_SEGMENT_FAILED",str(exc),flush=True)
        traceback.print_exc()
        raise
    finally:
        for p in procs.values():
            if p.poll() is None:
                try:os.killpg(p.pid,signal.SIGTERM)
                except ProcessLookupError:pass
        for p in procs.values():
            try:p.wait(timeout=20)
            except subprocess.TimeoutExpired:
                try:os.killpg(p.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                p.wait()
        for f in handles.values():f.close()

def self_test():
    assert choose_windows(0,220,180)==220
    assert choose_windows(1,960,150)==960
    assert choose_windows(1,960,300)==(int((60*3600)/(300*1.35))//80)*80
    assert round((.0025+220*DT)/DT)==240
    source="*RESTART,READ,STEP=1\n*STEP\n*DYNAMIC,DIRECT\n0.000125, 0.00125\n*RESTART,WRITE,FREQUENCY=1,OVERLAY\n*END STEP\n"
    changed=exact(r"(?im)^(\s*\*RESTART\s*,\s*READ\s*,\s*STEP=)\d+",
                  lambda m:m.group(1)+"2",source,"restart self-test")
    assert changed.startswith("*RESTART,READ,STEP=2")
    print("FSI_LONG_CHAIN_STATIC_SELF_TEST_PASS")

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base",type=Path,default=Path.home()/"hpcc-fsi")
    p.add_argument("--stage",type=int,required=False,default=0)
    p.add_argument("--previous-job",type=int)
    p.add_argument("--max-windows",type=int,default=960)
    p.add_argument("--work",type=Path)
    p.add_argument("--preflight-only",action="store_true")
    p.add_argument("--run",action="store_true")
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--timeout-seconds",type=int,default=66*3600)
    a=p.parse_args()
    if a.self_test:self_test();return
    if a.stage<0:raise RuntimeError("Invalid stage")
    if a.run==a.preflight_only:
        p.error("choose exactly one --run or --preflight-only")
    if a.stage==0 and a.max_windows!=220:
        p.error("Initial segment fixed at 220 windows")
    base=a.base.expanduser().resolve(strict=True)
    if a.preflight_only:
        prev,src,t,saved,step,perwin=source_for(base,a.stage,a.previous_job)
        n=choose_windows(a.stage,a.max_windows,perwin)
        print("FSI_LONG_CHAIN_PREFLIGHT_PASS",f"stage={a.stage}",f"from={t}",
              f"to={t+n*DT}",f"windows={n}",f"step={step}")
        print("NO_SLURM_NO_SOLVER_NO_MUTATION")
        return
    if a.work is None:p.error("--run needs --work")
    run(base,a.stage,a.previous_job,a.work.expanduser().resolve(),
        a.max_windows,a.timeout_seconds)

if __name__=="__main__":
    sys.exit(main())
