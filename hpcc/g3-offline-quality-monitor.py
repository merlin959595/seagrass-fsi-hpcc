#!/usr/bin/env python3
"""G3 read-only monitor + quality and readiness evidence for FSI jobs.

Reads a completed or running job directory, without launching jobs. Does not
declare long-motion stability or periodicity from initial displacement alone.
A completed job passes only after independent preCICE residuals, trajectory,
mesh-quality/exit evidence are explicitly available. For 90873, use its own
G1_B_RESULT.json as the actual coupled restart authority.
"""
import argparse
import datetime
import json
import math
from pathlib import Path
import re
import sys

MAX_NONORTH=65
MAX_CO=.5
DT=.000125
TOL=1e-5


def safe_json(p):
    if not p.is_file():return None
    try:return json.loads(p.read_text())
    except (OSError,ValueError,UnicodeError):return None


def metric(q,key,lower=None,upper=None):
    x=q.get(key) if isinstance(q,dict) else None
    good=isinstance(x,(float,int)) and not isinstance(x,bool) and math.isfinite(x)
    if good and lower is not None:good=x>=lower
    if good and upper is not None:good=x<=upper
    return {"value":x,"pass":bool(good)}


def monitor_90873(base):
    root=base/"g1-b10-job-90873"
    state=safe_json(root/"STATE.json")
    result=safe_json(root/"G1_B_RESULT.json")
    case=root/"runs/hpcc-implicit-002"
    logs={}
    for name in ("solid","fluid"):
        p=root/(name+".log")
        if p.is_file():
            with p.open(errors="replace") as f:
                tail=list(f)[-14:]
            logs[name]={"status":"AVAILABLE","last_14_lines":[s.rstrip()[:250] for s in tail]}
        else:
            logs[name]={"status":"NOT_WRITTEN"}
    if state is None:
        return {"job":"90873","status":"NOT_STARTED_OR_NO_STATE",
                "G1_B_10_PLUS_10_RESTART_VERIFIED":False,"log_evidence":logs}
    status=state.get("status")
    accepted=status=="G1_B_10_PLUS_10_COUPLED_RESTART_PASS"
    result_valid=bool(accepted and result and
        result.get("status")=="G1_B_10_PLUS_10_COUPLED_RESTART_PASS"
        and result.get("participant_exit_codes")=={"fluid":0,"solid":0}
        and result.get("fluid_terminal_mesh_check")=="PASS"
        and result.get("g1_a_windows")==10
        and result.get("g1_b_windows")==10
        and result.get("allow_long_production") is False)
    if result_valid:
        trajectories=result.get("interface_trajectories",{})
        result_valid=all(
            isinstance(trajectories.get(k,{}).get("windows"),list)
            and len(trajectories[k]["windows"])==10
            and all(
                isinstance(w.get("difference_norm"),(int,float))
                and isinstance(w.get("acceptance_limit"),(int,float))
                and math.isfinite(w["difference_norm"])
                and 0<=w["difference_norm"]<=w["acceptance_limit"]
                for w in trajectories[k]["windows"])
            for k in ("tip","loads"))
    return {
        "job":"90873",
        "state_status":status,
        "G1_B_10_PLUS_10_RESTART_VERIFIED":bool(result_valid),
        "report_present":bool(result),
        "reported_wall_s":state.get("wall_s"),
        "reason":state.get("failure"),
        "participant_exit_codes":state.get("participant_exit_codes"),
        "log_evidence":logs,
        "production_authorized":False,
        "G3_large_motion_stability":"NOT_TESTED",
        "G3_new_speedup_candidate_full160":"NOT_TESTED",
    }


def assess_reference(base):
    # Original 89038 G3 benchmark is already proved independently, but
    # collect explicit primary gate evidence here, not just an archived status.
    root=base/"performance-full160-job-89038/optimized-160"
    state=safe_json(root/"STATE.json") or {}
    gate=safe_json(root/"runs/hpcc-implicit-002/GATE-0160.json") or {}
    win=safe_json(root/"runs/hpcc-implicit-002/WINDOWS.json")
    q=gate.get("quality") or {}
    checks={
        "status":state.get("status")=="OPTIMIZED_0P02_FSI_PASS",
        "accepted_windows":state.get("accepted_windows")==160,
        "participant_exit_codes":state.get("participant_exit_codes")=={"fluid":0,"solid":0},
        "window_count":isinstance(win,list) and len(win)==160,
        "final_time_s":abs(gate.get("gate_s",-1)-.02)<1e-9,
        "mesh_nonorth":metric(q,"max_nonorthogonality_deg",0,MAX_NONORTH),
        "fluid_Co":metric(q,"max_Co",0,MAX_CO),
        "mesh_Co":metric(q,"max_mesh_Co",0,MAX_CO),
        "cell_volume":metric(q,"min_volume_m3",1e-30),
    }
    if isinstance(win,list) and len(win)==160:
        checks["all_160_coupling_converged"]=all(
            isinstance(w,dict)
            and isinstance(w.get("force_residual"),(float,int))
            and isinstance(w.get("displacement_residual"),(float,int))
            and math.isfinite(w["force_residual"])
            and math.isfinite(w["displacement_residual"])
            and 0<=w["force_residual"]<=TOL
            and 0<=w["displacement_residual"]<=TOL
            and w.get("window")==i
            and abs(w.get("time_s",-99)-i*DT)<1e-9
            for i,w in enumerate(win,1))
    else:checks["all_160_coupling_converged"]=False
    approved=all(v if isinstance(v,bool) else v["pass"] for v in checks.values())
    return {"reference_job":"89038","baseline_acceptance":"PASS" if approved else "FAIL",
            "checks":checks,"new_candidate_acceptance":"NOT_TESTED"}


def self_test():
    assert metric({"max_Co":.445},"max_Co",0,.5)["pass"]
    assert not metric({"max_Co":.501},"max_Co",0,.5)["pass"]
    assert not metric({"max_Co":float("nan")},"max_Co",0,.5)["pass"]
    assert not metric({},"max_Co",0,.5)["pass"]
    assert not metric({"min_volume_m3":-1e-6},"min_volume_m3",1e-30)["pass"]
    print("G3_OFFLINE_MONITOR_STATIC_SELF_TEST_PASS")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base",type=Path,default=Path.home()/"hpcc-fsi")
    p.add_argument("--out",type=Path)
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:
        self_test();return
    base=a.base.expanduser().resolve(strict=True)
    results={
        "schema":"G3-quality-monitor-v1",
        "generated_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "mode":"OFFLINE_READ_ONLY",
        "G3_reference":assess_reference(base),
        "G1_B_current":monitor_90873(base),
        "G3_72hour_two_cycles":"NOT_VERIFIED",
        "restart_after_90873":"DO_NOT_CHAIN_BEFORE_VERIFIED",
    }
    print("G3_89038_REFERENCE",results["G3_reference"]["baseline_acceptance"])
    print("G1_B_90873_STATE",results["G1_B_current"].get("state_status",
                                                results["G1_B_current"].get("status")))
    print("G1_B_RESTART_VERIFIED",results["G1_B_current"].get("G1_B_10_PLUS_10_RESTART_VERIFIED",False))
    print("G3_NEW_CANDIDATE_160=NOT_TESTED")
    print("G3_TWO_CYCLES=NOT_VERIFIED")
    if a.out:
        out=a.out.expanduser().resolve()
        if out.suffix!=".json" or not out.is_relative_to(base):
            raise SystemExit("Output must be a fresh JSON report under hpcc-fsi")
        if out.exists():raise SystemExit("Refusing to overwrite report")
        for protected in (
            "performance-full160-job-89038","implicit-pilot-002-8mpi-timefix-87186",
            "seagrass-implicit-20261111","g1-b10-job-90873"):
            if out.is_relative_to(base/protected):
                raise SystemExit("Report may not be inside original/active result tree")
        out.parent.mkdir(parents=True,exist_ok=True)
        with out.open("x") as f:
            json.dump(results,f,indent=2,ensure_ascii=False)
            f.write("\n")
        print("G3_REPORT",out)


if __name__=="__main__":
    main()
