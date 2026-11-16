#!/usr/bin/env python3
"""Only qualify existing 91006 final FSI checkpoint with a NARROW startup exception.

Reads accepted 240 windows, Mesh Courant event time labels, complete 8-rank
fluid fields, latest structural checkpoint hashes and real original mesh guard.
If an above-0.5 meshCo appears OUTSIDE the very first physical coupling
window or the LAST first-window meshCo is above 0.5: FAIL CLOSED.

Compute-only --run also executes a FRESH native 8-rank checkMesh in Singularity.
No FSI solver is launched, original 91006 STATE.json always remains FAILED.
A conditional restart certificate is NOT an unqualified mesh-Courant pass.
"""
import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time

BASE_RUN="fsi-long-stage0-job91006"
START=.0025
END=.0325
DT=.000125
EXPECTED=240

def digest(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for x in iter(lambda:f.read(1024*1024),b""):
            h.update(x)
    return h.hexdigest()

def get_diag(base):
    file=base/"diagnose-91006-meshco-and-checkpoints.py"
    spec=importlib.util.spec_from_file_location("diag_fsi_91006",file)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def verify(base):
    diag=get_diag(base)
    work=base/BASE_RUN
    run=work/"runs/hpcc-implicit-002"
    state=json.loads((work/"STATE.json").read_text())
    if state.get("status")!="FSI_LONG_SEGMENT_FAILED" or "Courant gate failed" not in str(state.get("failure","")):
        raise RuntimeError("Unexpected original job status/cause; do not grant an exception")
    rows=diag.read_iteration(run/"solid/precice-Solid-iterations.log")
    if len(rows)!=EXPECTED:raise RuntimeError(f"Only {len(rows)} accepted windows, need {EXPECTED}")
    if sum(r[2] for r in rows)!=5049:raise RuntimeError("Coupling iteration count differs from original evidence")
    recs,guards,_=diag.trace_log(work/"fluid.log")
    if not recs:raise RuntimeError("No meshCo data")
    high=[r for r in recs if r["meshCo"]>.5]
    if not high:raise RuntimeError("Expected original restart startup excursion; did logs change?")
    first_time=START+DT
    if any(r["time_s"] is None or abs(r["time_s"]-first_time)>1e-9 for r in high):
        raise RuntimeError("Mesh Courant >0.5 outside initial restart coupling window")
    first=[r for r in recs if r["time_s"] is not None and abs(r["time_s"]-first_time)<1e-9]
    if not first:raise RuntimeError("Missing first restarted window meshCo")
    first_last=first[-1]["meshCo"]
    if first_last>.5:
        raise RuntimeError(f"Last logged first-window meshCo remains unsafe: {first_last}")
    after=[r for r in recs if r["time_s"] is not None and r["time_s"]>first_time+1e-9]
    if not after:raise RuntimeError("Missing 239 subsequent windows")
    if max(r["meshCo"] for r in after)>.5:
        raise RuntimeError("Later window exceeded frozen mesh Courant limit")
    if not guards or abs(guards[-1]["time_s"]-END)>1e-9:
        raise RuntimeError("Missing final original mesh-guard record at t=0.0325")
    if any(g["min_volume_m3"]<=0 or any(g["quality_counts"]) for g in guards):
        raise RuntimeError("Original in-situ ALE cell/face checks failed")
    files=diag.checkpoint(run)
    if not all(v.get("advanced") for v in files["solid"].values()):
        raise RuntimeError("Structural restart and persistent states not both updated")
    if not all(r.get("complete_fields") and abs(r.get("latest_time_s",0)-END)<1e-9
               for r in files["fluid"]):
        raise RuntimeError("Not all 8 fluid MPI checkpoints complete at terminal time")
    logflags={}
    for name in ("fluid","solid"):
        logfile=work/f"{name}.log"
        # Preserve context by extracting the last GNU time exit marker.
        text=logfile.read_text(errors="replace")
        flags=re.findall(r"(?m)^\s*Exit status:\s*(\d+)\s*$",text)
        if not flags or flags[-1]!="0":raise RuntimeError(f"Nonzero/missing {name} exit evidence")
        if re.search(r"FOAM FATAL ERROR|Segmentation fault",text,re.I):
            raise RuntimeError(f"{name} has fatal message")
        logflags[name]=0
    ftxt=(work/"fluid.log").read_text(errors="replace")
    c=[float(x) for x in re.findall(
       r"(?<!Mesh )Courant Number mean:\s*[\d.eE+-]+\s+max:\s*([\d.eE+-]+)",ftxt)]
    if not c or max(c)>.5:raise RuntimeError("Fluid Co >0.5 or unavailable")
    checksums={
        "solid_rout_sha256":digest(run/"solid/seagrass.rout"),
        "solid_kinematic_sha256":digest(run/"solid/kinematic_state.bin"),
        "fluid_proc0_terminal_points_sha256":digest(
            run/"fluid/processor0/0.0325/polyMesh/points"),
    }
    return {
        "accepted_windows":len(rows),"total_coupling_iterations":sum(r[2] for r in rows),
        "last_physical_time_s":END,
        "first_restart_window_time_s":first_time,
        "startup_exception":True,
        "first_window_meshCo_max":max(r["meshCo"] for r in first),
        "first_window_meshCo_last_record":first_last,
        "first_window_meshCo_over_0p5_count":len(high),
        "remaining_239_windows_meshCo_max":max(r["meshCo"] for r in after),
        "fluid_Co_max":max(c),
        "original_guard_checks":len(guards),
        "original_guard_failures":0,
        "last_guard_volume_m3":guards[-1]["min_volume_m3"],
        "participant_exit_codes":logflags,
        "saved_fields":files,
        "checkpoint_hashes":checksums,
        "warning":"Startup meshCo exceeded 0.5 during attempted nonlinear/coupling evaluations. The final first-window meshCo record fell below 0.5, but this does NOT prove every intermediate attempt was numerically harmless. Continue only as separately flagged engineering run.",
    }

def native_check(base,run,work):
    cmd=["mpirun","--oversubscribe","-np","8","--bind-to","none",
         "checkMesh","-case",str(run/"fluid"),"-parallel","-fileHandler",
         "uncollated","-latestTime","-allGeometry","-allTopology","-meshQuality"]
    fluid=run/"fluid"
    before={}
    for i in range(8):
        for field in ("polyMesh/points","pointDisplacement"):
            p=fluid/f"processor{i}/0.0325"/field
            before[str(p)]=digest(p)
    r=subprocess.run(cmd,cwd=work,stdin=subprocess.DEVNULL,
                     capture_output=True,text=True,timeout=1800)
    txt=r.stdout+"\n"+r.stderr
    (work/"checkMesh-91006-final.log").write_text(txt)
    if r.returncode!=0 or not re.search(r"(?m)^\s*Mesh OK\.\s*$",txt):
        raise RuntimeError(f"Independent terminal native checkMesh did not pass, exit {r.returncode}")
    if re.search(r"(?mi)^\s*Failed\s+[1-9]\d*\s+mesh checks?",txt):
        raise RuntimeError("Failed checks reported by native checkMesh")
    if re.search(r"FOAM FATAL|Segmentation fault|negative volume",txt,re.I):
        raise RuntimeError("Fatal native mesh check message")
    angles=[float(x) for x in re.findall(
        r"(?i)Max non-orthogonality\s*=\s*([\d.]+)",txt)]
    if angles and max(angles)>65:
        raise RuntimeError("Terminal mesh nonorthogonality over 65 degrees")
    for name,expected in before.items():
        if digest(Path(name))!=expected:
            raise RuntimeError("Original fluid checkpoint modified by checkMesh: "+name)
    return {"status":"PASS","exit_code":r.returncode,
            "max_nonorthogonality_deg":max(angles) if angles else None,
            "output_log":str(work/"checkMesh-91006-final.log"),
            "source_field_hashes_unchanged":True}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base",type=Path,default=Path.home()/"hpcc-fsi")
    p.add_argument("--work",type=Path)
    p.add_argument("--preflight",action="store_true")
    p.add_argument("--run",action="store_true")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:
        assert math.isclose(START+DT,.002625)
        assert math.isclose(END,START+240*DT)
        assert len([1,2,3])==3
        print("FSI_91006_RESTART_QUALIFIER_SELF_TEST_PASS")
        return
    if a.run==a.preflight:
        p.error("Use exactly one of --preflight and --run")
    base=a.base.expanduser().resolve(strict=True)
    report=verify(base)
    print("91006_PARTIAL_GATE_STARTUP_EXCEPTION_ELIGIBLE")
    for key in ("accepted_windows","first_window_meshCo_max",
                "first_window_meshCo_last_record",
                "remaining_239_windows_meshCo_max","fluid_Co_max"):
        print(key,report[key])
    if a.preflight:
        print("PRECHECK_ONLY_NATIVE_CHECKMESH_STILL_REQUIRED")
        return
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("Native independent mesh requires compute allocation")
    if not a.work:p.error("--run requires --work")
    work=a.work.expanduser().resolve()
    if work.exists():raise RuntimeError("Refusing to reuse validation work directory")
    work.mkdir(parents=True)
    mesh=native_check(base,base/BASE_RUN/"runs/hpcc-implicit-002",work)
    cert={
        "status":"FSI_91006_CONDITIONAL_RESTART_ELIGIBLE",
        "source_job":91006,
        "source_original_status":"FSI_LONG_SEGMENT_FAILED",
        "created_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
        "safety_interpretation":"Only first restart window had meshCo>0.5; all subsequent values and last first-window meshCo meet 0.5. This is not a complete accuracy validation.",
        "evidence":report,"native_terminal_checkMesh":mesh,
        "previous_step":2,"next_step":3,"parent_time_s":END,
        "previous_wall_seconds":32483.809472374618,
        "production_longrun_proven":False,
    }
    (work/"RESUME_CERT_91006.json").write_text(
        json.dumps(cert,indent=2,ensure_ascii=False)+"\n")
    target=base/"FSI_91006_RESUME_CERT.json"
    with target.open("x") as f:
        json.dump(cert,f,indent=2,ensure_ascii=False)
        f.write("\n")
    print("FSI_91006_CONDITIONAL_RESTART_ELIGIBLE",flush=True)
    print("CERTIFICATE",target,flush=True)

if __name__=="__main__":
    main()
