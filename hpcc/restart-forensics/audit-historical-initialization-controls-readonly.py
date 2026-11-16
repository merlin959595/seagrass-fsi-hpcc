#!/usr/bin/env python3
"""Read-only audit of previously executed isolated restart-initialization tests.

Compares true/false restartFromDeformed and Force/Displacement initialize flags
against an uninterrupted same-physical-time accepted-force reference.
Read only. No Slurm, solver, adapter operations, library writes, file mutations.
"""
from pathlib import Path
import argparse, json, math, re

CASES={
 "91504_ref_false_only":("ale-restart-reference-tests/trial-91504",2),
 "91538_true_disp_init":("ale-nonzero-initial-data/trial-91538",8),
 "91542_true_both_init":("ale-both-initial-data/trial-91542",2),
 "91767_false_both_init":("crossjob-fix-20261116/trials/trial-91767",2),
 "91819_false_both_init_fullhistory":("crossjob-fix-20261116/trials/trial-91819",2),
}
SOURCE="fsi-long-stage0-job91006/runs/hpcc-implicit-002"
LIVE="three-day-proven/long-job-91543/runs/hpcc-implicit-002"
DT=.000125

def accepted(path):
    if not path.is_file():return []
    rows=[]
    with path.open(errors="replace") as f:
        for line in f:
            p=line.split()
            if len(p)<7:continue
            try: vals=[float(x) for x in p[:7]]
            except ValueError:continue
            if all(math.isfinite(x) for x in vals):
                rows.append(vals)
    return rows

def nearest(rows,t):
    x=[row for row in rows if abs(row[0]-t)<1e-8]
    return x[-1] if x else None

def cfg(path):
    p=path/"fluid/system/preciceDict"
    xml=path/"precice-config.xml"
    if not p.is_file() or not xml.is_file():return {"case_inputs_found":False}
    foam=p.read_text(errors="replace")
    data=xml.read_text(errors="replace")
    flag=re.findall(r"\brestartFromDeformed\s+(true|false)\s*;",foam)
    exchange={}
    for name in ("Force","Displacement"):
        tags=re.findall(r'<exchange\b[^>]*\bdata="'+name+r'"[^>]*/>',data)
        exchange[name]={"count":len(tags),"initialize_yes":
                         len(tags)==1 and bool(re.search(r'initialize\s*=\s*"yes"',tags[0]))}
    return {"case_inputs_found":True,"restartFromDeformed":flag,"exchange":exchange}

def first_meshCo(path):
    if not path.is_file():return None
    with path.open(errors="replace") as f:
        for line in f:
            if "Mesh Courant Number" in line:
                m=re.search(r"max:\s*([-+\deE.]+)",line)
                if m:return float(m.group(1))
    return None

def count_force_evals(path,maxscan=100_000):
    if not path.is_file():return None
    count=0
    with path.open(errors="replace") as f:
        for k,line in enumerate(f):
            if k>=maxscan:break
            if "forces bladeForces write:" in line:count+=1
    return count

def status(root):
    names=("STATE.json","REFERENCE_ALIGNED_BOTH_FIELDS_RESULT.json",
           "BOTH_INITIAL_FIELDS_2WINDOW_RESULT.json",
           "INITIAL_DISPLACEMENT_TEST_RESULT.json",
           "REFERENCE_RESTART_RESULT.json")
    out={}
    for name in names:
        p=root/name
        if p.is_file():
            try:
                q=json.loads(p.read_text())
                out[name]={"status":q.get("status"),"failure":q.get("failure"),
                           "exception":str(q.get("exception"))[:180] if q.get("exception") else None}
            except (ValueError,OSError):out[name]={"invalid_json":True}
    return out

def audit(base):
    source=base/SOURCE
    live=base/LIVE
    ref=accepted(live/"solid/precice-Solid-watchintegral-Interface-Integral.log")
    last_source=nearest(accepted(source/"solid/precice-Solid-watchintegral-Interface-Integral.log"),.03)
    if not ref or last_source is None:
        raise RuntimeError("Missing immutable reference accepted watch data")
    output={"report":"HISTORICAL_RESTART_INITIALIZATION_CONTROLS_READONLY",
            "source_91006_last_Fx_N":last_source[1],"cases":{}}
    for label,(rel,n) in CASES.items():
        root=base/rel
        case=root/"runs/hpcc-implicit-002"
        if not case.is_dir():
            output["cases"][label]={"available":False};continue
        w=accepted(case/"solid/precice-Solid-watchintegral-Interface-Integral.log")
        record={"available":True,"settings":cfg(case),
                "initial_mesh_Co_max":first_meshCo(root/"fluid.log"),
                "total_force_evaluations":count_force_evals(root/"fluid.log"),
                "existing_result_status":status(root),
                "watch_initial":nearest(w,0.0),
                "accepted_comparisons":[]}
        for i in range(1,min(n,2)+1):
            t=i*DT
            x=nearest(w,t)
            y=nearest(ref,.03+t)
            record["accepted_comparisons"].append({
              "window":i,
              "accepted_trial":x[:7] if x else None,
              "accepted_91543":y[:7] if y else None,
              "force0_relative_error_to_continuous":(
                  abs(x[1]-y[1])/abs(y[1]) if x and y and abs(y[1])>1e-12 else None),
              "displacement0_relative_error_to_continuous":(
                  abs(x[4]-y[4])/abs(y[4]) if x and y and abs(y[4])>1e-12 else None)})
        output["cases"][label]=record
    output["limitations"]=[
      "Unavailable old trial is NOT evidence that it never ran.",
      "Missing accepted windows means numerical viability is undetermined.",
      "A first Mesh Courant value may be a provisional PIMPLE iteration.",
      "Existing tests vary combinations of setup flags; do not make causal claims from non-matched groups.",
      "No third-party solver, adapter, or 91543 data was modified."
    ]
    return output

def summarize(packet):
    lines=["HISTORICAL_INITIALIZATION_CONTROLS_READONLY",
           "91006 source last accepted Fx="+str(packet["source_91006_last_Fx_N"])]
    for label,case in packet["cases"].items():
        if not case.get("available"):
            lines.append(label+" NOT_FOUND; no inference");continue
        setting=case["settings"]
        frame=setting.get("restartFromDeformed")
        exchange=setting.get("exchange",{})
        flags={k:v["initialize_yes"] for k,v in exchange.items()}
        lines.append(f"{label} frame={frame} init={flags} "
                     f"first_meshCo={case['initial_mesh_Co_max']} "
                     f"force_evals={case['total_force_evaluations']}")
        for p in case["accepted_comparisons"]:
            a=p["accepted_trial"];b=p["accepted_91543"]
            lines.append(f"  WINDOW_{p['window']} "
                         f"trial_Fx={a[1] if a else None} "
                         f"ref_91543_Fx={b[1] if b else None} "
                         f"Fx_rel_err={p['force0_relative_error_to_continuous']} "
                         f"Disp0_integral_rel_err={p['displacement0_relative_error_to_continuous']}")
        lines.append("  existing_status="+json.dumps(case["existing_result_status"],ensure_ascii=False))
    lines.append("READ_ONLY; NO Slurm/SOLVER/JOB CHANGES")
    return "\n".join(lines)

def selftest():
    assert nearest([[0,1],[.000125,2]],.000125)==[.000125,2]
    assert nearest([],0) is None
    assert abs(.03+DT-.030125)<1e-12
    sample='<exchange data="Force" mesh="Solid-Mesh" from="Fluid" to="Solid" initialize="yes" />'
    assert re.search(r'initialize\s*=\s*"yes"',sample)
    print("HISTORICAL_INITIALIZATION_CONTROL_READONLY_SELFTEST_PASS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--base",type=Path,default=Path.home()/"hpcc-fsi")
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--summary",action="store_true")
    args=p.parse_args()
    if args.self_test:return selftest()
    out=audit(args.base.expanduser().resolve(strict=True))
    print(summarize(out) if args.summary else json.dumps(out,ensure_ascii=False,indent=2))
    print("NO_SOLVER_NO_SLURM_NO_SOURCE_OR_LIVE_MUTATION")

if __name__=="__main__": main()
