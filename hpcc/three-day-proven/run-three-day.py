#!/usr/bin/env python3
"""3-day allocation / long, continuous, real 3D two-way seagrass FSI.

Scientific choice:
  Start from the independently evidenced t=0.0025s source of successful
  job 91006 (240 accepted windows), NOT from t=0.0325s, which reproducibly
  diverges after a *new* preCICE session. Reruns t=.0025..0325 once.
  Keep one continuous preCICE/CalculiX process for 1280 windows:
  t=0.0025 -> t=0.1625s (dt=0.000125), i.e. 0.16s of physical time.
  Estimate = 1280 * (32483.809s/240)=48.13h, allowing 35% slowdown
  within 66h watchdog and 72h Slurm allocation.

Uses frozen, previously executed core (the same version as failed A
chain, but stage 0 is run from proven earlier 90873 checkpoint).
No changing mesh, physics, ALE numerics, FSI solver or force/disp
initialization settings. The successful 91006 path is the control run.

Real restart checkpoint qualification is by BOTH:
  fluid latest time of all 8 processor folders, all fields + native checkMesh
  CCX final .rout and persistent kinematic state from a normal successful exit
and 1280 accepted preCICE windows plus startup-transient Courant audit.
Only a qualified result is RESUME_SOURCE_APPROVED (NOT "restart proven").

IMPORTANT LIMITATION: OpenFOAM time folders alone do not checkpoint CCX.
*RESTART,WRITE,FREQUENCY=1 writes at CalculiX STEP completion, NOT after
every preCICE time window. Mid-run cancellation / walltime does not
guarantee a paired valid restart. Use generous 72h wall and 66h timeout.
Never automatically launch a new coupled session from a new checkpoint until
2-window restart continuity (force, mesh, structure) has been demonstrated.
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import sys
import traceback

BASE=Path.home()/"hpcc-fsi"
CORE=BASE/"seagrass-fsi-mainline/bin/segment.py"
DT=.000125
WINDOWS=1280
START=.0025
END=START+DT*WINDOWS
EXPECTED_91006_FX=.017663820833889
WALL=3*24*3600
DRIVER_WATCHDOG=66*3600
SUCCESS={"FSI_LONG_SEGMENT_PASS","FSI_LONG_SEGMENT_PASS_WITH_RESTART_TRANSIENT"}

def core_module(path):
    if not path.is_file():
        raise RuntimeError(f"Missing frozen baseline FSI runtime: {path}")
    sp=importlib.util.spec_from_file_location("frozen_verified_fsi",path)
    m=importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m

def certification(base,core):
    cert=json.loads((base/"FSI_91006_RESUME_CERT.json").read_text())
    if (cert.get("status")!="FSI_91006_CONDITIONAL_RESTART_ELIGIBLE"
        or cert.get("source_job")!=91006
        or cert.get("native_terminal_checkMesh",{}).get("status")!="PASS"
        or cert.get("evidence",{}).get("accepted_windows")!=240):
        raise RuntimeError("Reference trajectory 91006 is not independently certified")
    source_parent,source,start,saved,step,per_win=core.source_for(base,0,90873)
    if abs(start-START)>1e-10 or step!=2:
        raise RuntimeError(f"Expected 90873 restart at {START}, Step2")
    if any(abs(x-START)>1e-10 for x,_ in saved):
        raise RuntimeError("The 8 MPI ranks do not share t=0.0025")
    xml=(source/"precice-config.xml").read_text()
    if re.search(r'<exchange[^>]*\binitialize\s*=\s*"yes"',xml):
        raise RuntimeError("90873 source configuration no longer matches the 91006 baseline")
    pc=(source/"fluid/system/preciceDict").read_text()
    if "restartFromDeformed true;" not in pc:
        raise RuntimeError("Moving-mesh restart reference was changed")
    if not (source/"solid/seagrass.rout").is_file() or not (source/"solid/kinematic_state.bin").is_file():
        raise RuntimeError("Missing structural restart state")
    if not (source/"restart_reference/Solid-Mesh.coords").is_file():
        raise RuntimeError("Missing original structural reference mesh")
    previous=base/"fsi-long-stage0-job91006"
    if not (previous/"fluid.log").is_file():
        raise RuntimeError("Missing original 91006 fluid log for trajectory regression")
    return source,per_win

def expected_window(stage,max_windows,speed):
    if stage!=0 or max_windows!=WINDOWS:
        raise RuntimeError("Three-day run accepts only the chosen 1280-window source 90873")
    if not math.isfinite(speed) or speed<=0:raise RuntimeError("Invalid source benchmark throughput")
    return WINDOWS

def watch_rows(file):
    if not file.is_file():raise RuntimeError(f"Missing structural watch evidence {file}")
    rows={}
    for l in file.read_text(errors="replace").splitlines():
        fields=l.split()
        if len(fields)<7:continue
        try:
            t=float(fields[0]); fx=float(fields[1])
        except ValueError:continue
        rows[round(t,9)]=fx
    return rows

def force_regression(base,work):
    old=base/"fsi-long-stage0-job91006/runs/hpcc-implicit-002/solid/precice-Solid-watchintegral-Interface-Integral.log"
    new=work/"runs/hpcc-implicit-002/solid/precice-Solid-watchintegral-Interface-Integral.log"
    o=watch_rows(old);n=watch_rows(new)
    time=.030
    if time not in o or time not in n:
        raise RuntimeError("No accepted force watch at physical time .0325 (relative t=.03)")
    fx1=o[time];fx2=n[time]
    if not .01<fx1<.03:raise RuntimeError("Original 91006 Force0 at .0325 unexpected")
    rel=abs(fx2-fx1)/abs(fx1)
    return {"source_Fx_N":fx1,"new_Fx_N":fx2,
            "relative_difference":rel,"source_rel_time_s":time,
            "baseline_91006_match_within_10pct":rel<=.10}

def self_test():
    assert math.isclose(END,.1625,abs_tol=1e-12)
    assert math.gcd(int(round(END/DT)),80)==20
    assert expected_window(0,WINDOWS,135.349)==WINDOWS
    for bad in (1,1279,1281):
        try:expected_window(0,bad,135.349)
        except RuntimeError:pass
        else:raise AssertionError("Window number not gated")
    assert WINDOWS*(32483.809472374618/240)*1.35 < DRIVER_WATCHDOG
    print("FSI_3DAY_CONTINUOUS_1280_WINDOW_SELF_TEST_PASS")

def run(base,work):
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("Only on a real Slurm compute node")
    if work.exists():
        raise RuntimeError("Refusing to overwrite a prior production case")
    if not work.is_relative_to(base):
        raise RuntimeError("Work must be inside hpcc-fsi")
    mod=core_module(CORE)
    certification(base,mod)
    original=mod.choose_windows
    error=None
    mod.choose_windows=expected_window
    try:
        print(f"FSI_THREE_DAY_REAL_START from={START} to={END} dt={DT} accepted_windows_target={WINDOWS}",flush=True)
        mod.run(base,0,90873,work,WINDOWS,DRIVER_WATCHDOG)
    except BaseException as ex:
        error=repr(ex)
        traceback.print_exc()
    finally:
        mod.choose_windows=original
    result_path=work/"FSI_SEGMENT_RESULT.json"
    result=json.loads(result_path.read_text()) if result_path.is_file() else None
    regression=None
    regression_err=None
    if result and result.get("status") in SUCCESS:
        try:regression=force_regression(base,work)
        except Exception as e:regression_err=repr(e)
    accepted=bool(
       error is None
       and result and result.get("status") in SUCCESS
       and result.get("accepted_windows")==WINDOWS
       and abs(float(result.get("final_time_s",0))-END)<1e-9
       and result.get("participant_exit_codes")=={"fluid":0,"solid":0}
       and result.get("native_terminal_mesh",{}).get("status")=="PASS"
       and regression and regression["baseline_91006_match_within_10pct"])
    packet={
       "status":"FSI_3DAY_PAIRED_RESTART_READY_NOT_RESUME_VALIDATED" if accepted
          else "FSI_3DAY_NOT_APPROVED",
       "source":"successful 90873 at 0.0025s; repeats 91006 t=.0025..0325",
       "initial_time_s":START,"final_time_s_target":END,
       "real_physical_time_advanced_s":WINDOWS*DT,
       "accepted_windows_target":WINDOWS,
       "no_new_precice_session_within_long_segment":True,
       "no_automatic_next_segment_before_restart_proven":True,
       "structural_restart_only_at_completed_STEP":True,
       "nonzero_initial_field_changes_applied":False,
       "real_core_result":result,
       "91006_regression":regression,
       "91006_regression_error":regression_err,
       "run_error":error,
       "proven_2window_continuation_at_endpoint":False
    }
    if work.exists():
        (work/"THREE_DAY_RESULT.json").write_text(json.dumps(packet,indent=2,ensure_ascii=False)+"\n")
    print(packet["status"],"TARGET",END,"ERROR",error,
          "BASELINE_FX_MATCH",regression["baseline_91006_match_within_10pct"] if regression else None,flush=True)
    if not accepted:sys.exit(3)

def main():
    a=argparse.ArgumentParser()
    a.add_argument("--base",type=Path,default=BASE)
    a.add_argument("--work",type=Path)
    a.add_argument("--self-test",action="store_true")
    a.add_argument("--preflight",action="store_true")
    a.add_argument("--run",action="store_true")
    x=a.parse_args()
    if x.self_test:return self_test()
    base=x.base.expanduser().resolve(strict=True)
    m=core_module(CORE)
    source,sec_per_win=certification(base,m)
    projection=WINDOWS*(32483.809472374618/240)
    if projection*1.35>=DRIVER_WATCHDOG:
        raise RuntimeError("Unsafe estimated runtime for 3-day Slurm job")
    if x.preflight:
        print("FSI_THREE_DAY_PREFLIGHT_PASS",f"source={source}",
          f"start={START}",f"end={END}",f"windows={WINDOWS}",
          f"estimated_hours_from_91006={projection/3600:.2f}",
          "no_files_changed_or_slurm_submitted")
        return
    if not x.run or x.work is None:
        a.error("Use --preflight or --run --work <new_dir>")
    run(base,x.work.expanduser().resolve())

if __name__=="__main__":
    main()
