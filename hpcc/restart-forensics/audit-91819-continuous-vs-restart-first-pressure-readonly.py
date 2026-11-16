#!/usr/bin/env python3
"""Compare the same physical-time pressure/flow solver trace for 91006,
91543 (continuous) and 91767/91819 (cross-job restarts).

Read-only; no Slurm, solver, adapter, case writes, or changes to 91543.
Search streams only through the first 0.033s of case time, bounded memory.
"""
import argparse
import json
import math
import re
from pathlib import Path
import tempfile

REL = {
  "source91006": "fsi-long-stage0-job91006",
  "continuous91543": "three-day-proven/long-job-91543",
  "restart91767": "crossjob-fix-20261116/trials/trial-91767",
  "restart91819": "crossjob-fix-20261116/trials/trial-91819",
}
TGT=(.0325,.032625,.03275)
TIMERE=re.compile(r"^\s*Time\s*=\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*$")
FORCERE=re.compile(r"^\s*(Total|Pressure|Viscous)\s*:\s*\(\s*([^\)]+)\)")
SOLVERRE=re.compile(r"(Solving for (?:p|p_rgh|Ux|Uy|Uz|U|phi)|continuity errors|Courant Number|Mesh Courant Number|"
                    r"PIMPLE: iteration|correctPhi|GAMG|PCG:|smoothSolver:|DICPCG:|forces bladeForces write:)",re.I)

def compact_trace(path, label):
    if not path.is_file():
        return {"file_exists":False,"path":str(path)}
    kept={f"{t:.6f}":{"matching_time_blocks":0,"samples":[],
                      "force_evaluations":0,
                      "first_forces":[],"last_forces":[]} for t in TGT}
    current=None
    reading_force=False
    after_force_header=False
    count=0
    time_matches=0
    first_time=None
    for line in path.open(errors="replace"):
        count+=1
        # Limit text scanning on a long-running production log while
        # still capturing the window region ~0.0325.
        if count>2_000_000:break
        m=TIMERE.match(line)
        if m:
            t=float(m.group(1))
            if first_time is None:first_time=t
            current=None
            reading_force=False
            after_force_header=False
            for goal in TGT:
                if abs(t-goal)<5e-10:
                    current=f"{goal:.6f}"
                    data=kept[current]
                    data["matching_time_blocks"]+=1
                    break
            if t>.0330001 and first_time is not None and first_time<=.033:
                break
            if current is not None:
                kept[current]["samples"].append({"kind":"time","text":line.strip()})
                time_matches+=1
            continue
        if current is None:continue
        data=kept[current]
        # Function object prints TWO identically named triple groups:
        # "Sum of forces" AND "Sum of moments". The previous parser included
        # moment components in "last forces" and falsely reported ~1e-10 N.
        # Only parse Total/Pressure/Viscous BETWEEN these two headings.
        if "forces bladeForces write:" in line:
            after_force_header=True
            reading_force=False
        elif after_force_header and "Sum of forces" in line:
            reading_force=True
            after_force_header=False
        elif "Sum of moments" in line:
            reading_force=False
            after_force_header=False
        m=FORCERE.match(line) if reading_force else None
        if m:
            kind=m.group(1)
            try: vals=[float(v) for v in m.group(2).split()]
            except ValueError: vals=[]
            if len(vals)==3 and math.isfinite(vals[0]):
                if kind=="Total":data["force_evaluations"]+=1
                data["last_forces"].append([kind,vals[0]])
                if len(data["first_forces"])<3:data["first_forces"].append([kind,vals[0]])
            continue
        if SOLVERRE.search(line):
            if len(data["samples"])<35 or ("Solving for p" in line and len(data["samples"])<80):
                data["samples"].append({"kind":"solver","text":line.strip()[:250]})
    for data in kept.values():
        last=data["last_forces"]
        data["last_forces"]=last[-9:] if len(last)>9 else last
        data["samples"]=data["samples"][:65]
    return {"file_exists":True,"path":str(path),"lines_examined":count,
            "first_time_s":first_time,"matched_time_blocks":time_matches,
            "targets":kept}

def dict_extract(root):
    paths={
        "motion_ref":"fluid/system/preciceDict",
        "precice_xml":"precice-config.xml",
        "control":"fluid/system/controlDict",
        "solvers":"fluid/system/fvSolution",
    }
    patterns={
        "motion_ref":(r"\brestartFromDeformed\s+(?:true|false)\s*;",r"\breadData\s*\([^)]*\)\s*;"),
        "precice_xml":(r"<exchange\s+[^>]*data=\"(?:Force|Displacement)\"[^>]*/>",),
        "control":(r"\bdeltaT\s+[^;]+;",r"\bpurgeWrite\s+[^;]+;"),
        "solvers":(r"\bcorrectPhi\s+[^;]+;",r"\bmoveMeshOuterCorrectors\s+[^;]+;"),
    }
    result={}
    for key,path in paths.items():
        p=root/path
        if not p.is_file():
            result[key]={"file_exists":False}
            continue
        text=p.read_text(errors="replace")
        result[key]=[m.group(0) for pat in patterns[key] for m in re.finditer(pat,text)][:15]
    return result

def watch(path):
    if not path.is_file():return {}
    data={}
    for line in path.open(errors="replace"):
        p=line.split()
        if len(p)<7:continue
        try:
            t=float(p[0]); vals=[float(x) for x in p[1:7]]
        except ValueError:continue
        if not all(math.isfinite(v) for v in [t,*vals]):continue
        data[round(t,9)]=vals
    return data

def motion_slope(result):
    source=result["source91006"]["watch"]
    live=result["continuous91543"]["watch"]
    restarted=result["restart91819"]["watch"]
    t_before=round(.03-.000125,9)
    t0=.03
    dt=.000125
    def slope(rows,t1,t2):
        a,b=rows.get(round(t1,9)),rows.get(round(t2,9))
        if a is None or b is None:return None
        return {"Force0_slope_N_per_s":(b[0]-a[0])/(t2-t1),
                "Displacement0_integral_slope_per_s":(b[3]-a[3])/(t2-t1),
                "Displacement2_integral_slope_per_s":(b[5]-a[5])/(t2-t1)}
    return {
      "91006_prior_to_restart":slope(source,t_before,t0),
      "91543_prior_to_restart":slope(live,t_before,t0),
      "91543_first_after_restart_point":slope(live,t0,t0+dt),
      "91819_first_new_window":slope(restarted,0,dt),
      "91543_second_window":slope(live,t0+dt,t0+2*dt),
      "91819_second_new_window":slope(restarted,dt,2*dt),
      "caution":"Watchintegral displacement slope is integrated interface quantity, not local node velocity."
    }

def audit(base):
    result={}
    for key,rel in REL.items():
        folder=base/rel
        case=folder/"runs/hpcc-implicit-002"
        result[key]={
            "trace":compact_trace(folder/"fluid.log",key),
            "settings":dict_extract(case),
            "watch":watch(case/"solid/precice-Solid-watchintegral-Interface-Integral.log")
        }
    slopes=motion_slope(result)
    summary={}
    for key,info in result.items():
        trace=info["trace"]
        summary[key]={"settings":info["settings"],
                      "line_count_examined":trace.get("lines_examined"),
                      "first_log_time_s":trace.get("first_time_s"),
                      "trace_targets":trace.get("targets"),
                      "source_or_trial_watch_at_003":info["watch"].get(.03) if "restart" not in key else info["watch"].get(0.0)}
    return {
      "audit":"READ_ONLY_DIFFERENTIAL_PRESSURE_SOLVE",
      "cases":summary,
      "accepted_integral_derivatives":slopes,
      "no_files_modified":True,
      "no_solver_or_Slurm_invoked":True,
    }

def concise_summary(data):
    lines=["READ_ONLY_DIFFERENTIAL_PRESSURE_SOLVE_SUMMARY"]
    for case,entry in data["cases"].items():
        lines.append(f"=== {case} ===")
        lines.append("REFERENCE_SETTINGS="+json.dumps(entry["settings"],ensure_ascii=False))
        lines.append(f"LOG_LINES={entry['line_count_examined']} FIRST_LOG_T={entry['first_log_time_s']}")
        for t,block in entry["trace_targets"].items():
            lines.append(f"TIME={t} FLUID_TIME_RECORDS={block['matching_time_blocks']} "
                         f"FORCE_EVALUATIONS={block['force_evaluations']} "
                         f"FIRST_PROVISIONAL_FORCE_COMPONENTS={block['first_forces'][:3]} "
                         f"LAST_FLUID_FORCE_COMPONENTS={block['last_forces'][-3:]}")
            # The last fluid force is still not automatically a validated
            # accepted preCICE value: compare the accepted Solid watch log.

            selected=[d["text"] for d in block["samples"]
                      if "Solving for p" in d["text"] or "Courant Number" in d["text"]]
            lines.extend("  SOLVER "+x for x in selected[:8])
    lines.append("COUPLED_INTEGRAL_WINDOW_SLOPES="+
                 json.dumps(data["accepted_integral_derivatives"],ensure_ascii=False))
    lines.append("NO_SBATCH_NO_SOLVER_NO_FILE_WRITES")
    return "\n".join(lines)

def self_test():
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)/"fluid.log"
        p.write_text(
          "Time = 0.032625\n"
          "Courant Number mean: 0.01 max: 0.2\n"
          "GAMG: Solving for p, Initial residual = 0.1, Final residual = 1e-6\n"
          "forces bladeForces write:\n"
          "    Sum of forces\n"
          "        Total    : (11.515 0 -0.1)\n"
          "        Pressure : (11.514 0 -0.1)\n"
          "        Viscous  : (0.001 0 0)\n"
          "    Sum of moments\n"
          "        Total    : (1e-10 0 0)\n"
          "        Pressure : (2e-10 0 0)\n"
          "        Viscous  : (-1e-10 0 0)\n"
          "forces bladeForces write:\n"
          "    Sum of forces\n"
          "        Total    : (0.018 0 -0.0001)\n"
          "        Pressure : (0.017 0 -0.0001)\n"
          "        Viscous  : (0.001 0 0)\n"
          "    Sum of moments\n"
          "        Total    : (-1e-12 0 0)\n"
          "        Pressure : (-2e-12 0 0)\n"
          "        Viscous  : (1e-12 0 0)\n"
          "Time = 0.03275\n"
        )
        x=compact_trace(p,"mock")
        a=x["targets"]["0.032625"]
        assert a["matching_time_blocks"]==1
        assert a["force_evaluations"]==2
        assert a["first_forces"]==[["Total",11.515],
                                   ["Pressure",11.514],["Viscous",0.001]]
        assert a["last_forces"][-3:]==[["Total",0.018],
                                       ["Pressure",0.017],["Viscous",0.001]]
        assert "Solving for p" in str(a["samples"])
    print("READ_ONLY_PRESSURE_SOLVER_TRACE_SELFTEST_PASS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--base",type=Path,default=Path.home()/"hpcc-fsi")
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--summary",action="store_true")
    opt=p.parse_args()
    if opt.self_test:return self_test()
    result=audit(opt.base.expanduser().resolve(strict=True))
    print(concise_summary(result) if opt.summary
          else json.dumps(result,ensure_ascii=False,indent=2))
    print("NO_SBATCH_NO_SOLVER_NO_FS_MUTATIONS")

if __name__=="__main__":main()
