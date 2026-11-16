#!/usr/bin/env python3
"""Read-only compare source/continuous/restarted coupled displacement and force.

No solver, SLURM, mesh mutation, time-step modifications, writing or renaming.
Used after 91819 falsified the hypothesis that keeping 15 time directories fixes
cross-job force continuity. Python stdlib only; safe on HPCC login node.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import tempfile

ROOTS={
    "source_91006":"fsi-long-stage0-job91006/runs/hpcc-implicit-002",
    "continuous_91543":"three-day-proven/long-job-91543/runs/hpcc-implicit-002",
    "restart_91767":"crossjob-fix-20261116/trials/trial-91767/runs/hpcc-implicit-002",
    "restart_91819":"crossjob-fix-20261116/trials/trial-91819/runs/hpcc-implicit-002",
}
COLS=("Force0","Force1","Force2","Displacement0","Displacement1","Displacement2")
FIELDS=("U","p","phi","Uf","meshPhi","V0","cellDisplacement","pointDisplacement",
        "polyMesh/points","uniform/time")

def watch_rows(path):
    if not path.is_file():return []
    records=[]
    with path.open(errors="replace") as handle:
        for line in handle:
            p=line.split()
            if len(p)<7:continue
            try:
                t=float(p[0]); values=[float(x) for x in p[1:7]]
            except ValueError:continue
            if not all(math.isfinite(x) for x in (t,*values)):continue
            records.append({"relative_time_s":t,**dict(zip(COLS,values))})
    return records

def pick(records,t):
    candidates=[r for r in records if abs(r["relative_time_s"]-t)<1e-8]
    return candidates[-1] if candidates else None

def diff(a,b):
    if a is None or b is None:return None
    return {"absolute_difference":a-b,
            "relative_difference":abs(a-b)/abs(b) if abs(b)>1e-14 else None}

def sha(path):
    if not path.is_file():return None
    dig=hashlib.sha256()
    with path.open("rb") as stream:
        for data in iter(lambda:stream.read(1<<20),b""):
            dig.update(data)
    return dig.hexdigest()

def compare_checkpoint_fields(source, trial):
    result={}
    for field in FIELDS:
        src_count=0;trial_count=0;equal=0;unequal_ranks=[]
        for rank in range(8):
            p=source/f"fluid/processor{rank}/0.0325"/field
            q=trial/f"fluid/processor{rank}/0.0325"/field
            a=sha(p);b=sha(q)
            src_count+=int(a is not None);trial_count+=int(b is not None)
            equal+=int(a is not None and a==b)
            if a and b and a!=b:unequal_ranks.append(rank)
        result[field]={"source_present":src_count,"trial_present":trial_count,
                       "sha_equal_ranks":equal,"different_ranks":unequal_ranks}
    return result

def first_force_parts(log):
    if not log.is_file():return None
    found=False;lines=[];time=None
    with log.open(errors="replace") as f:
        for line in f:
            m=re.match(r"\s*Time\s*=\s*([0-9.eE+-]+)\s*$",line)
            if m:time=float(m.group(1))
            if "forces bladeForces write:" in line:found=True
            if found:
                lines.append(line)
                if len(lines)>=16:break
    if not lines:return None
    joined="".join(lines)
    values={}
    for label in ("Total","Pressure","Viscous"):
        m=re.search(r"\b"+label+r"\s*:\s*\(\s*([0-9.+eE-]+)\s+([0-9.+eE-]+)\s+([0-9.+eE-]+)\s*\)",joined)
        if m:values[label+"_Fx_N"]=float(m.group(1))
    values["physical_time_s"]=time
    if values.get("Total_Fx_N") and values.get("Pressure_Fx_N") is not None:
        values["pressure_fraction_of_total_Fx"]=values["Pressure_Fx_N"]/values["Total_Fx_N"]
    return values

def report(base):
    paths={key:base/rel for key,rel in ROOTS.items()}
    for key,path in paths.items():
        if not path.is_dir():raise RuntimeError(f"Missing case {key}: {path}")
    watches={}
    for name,path in paths.items():
        watches[name]=watch_rows(path/"solid/precice-Solid-watchintegral-Interface-Integral.log")
    src=pick(watches["source_91006"],.03)
    live0=pick(watches["continuous_91543"],.03)
    windows=[]
    for i in range(1,3):
        trial_t=i*.000125
        continuous_t=.03+trial_t
        baseline=pick(watches["continuous_91543"],continuous_t)
        info={"window":i,"physical_time_s":.0325+trial_t,
              "continuous_relative_time_s":continuous_t,
              "continuous_reference":baseline}
        for trial in ("restart_91767","restart_91819"):
            current=pick(watches[trial],trial_t)
            info[trial]={"accepted":current,
                         "component_differences":{
                              key:diff(current[key],baseline[key]) if current and baseline else None
                              for key in COLS}}
        windows.append(info)
    trial_inputs={}
    for trial in ("restart_91767","restart_91819"):
        case=paths[trial]
        trial_inputs[trial]={
            "source_vs_initial_fields":compare_checkpoint_fields(paths["source_91006"],case),
            "first_computed_blade_force_components":
                first_force_parts(case.parent.parent/"fluid.log"),
            "initial_solid_watch":pick(watches[trial],0.0)
        }
    return {
      "report":"READ_ONLY_CROSS_JOB_ACCEPTED_DISPLACEMENT_AND_PRESSURE",
      "source_at_00325":src,"continuous_at_00325":live0,
      "source_vs_continuous_at_00325":{
          c:diff(src[c],live0[c]) if src and live0 else None for c in COLS},
      "accepted_window_comparisons":windows,
      "initial_field_comparisons_and_pressure":trial_inputs,
      "scope":"Four existing cases; source and live jobs read-only; no Slurm or solver calls"
    }

def self_test():
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)/"w.log"
        p.write_text(
            "Time Force0 Force1 Force2 Displacement0 Displacement1 Displacement2\n"
            "0.0 .017 0 -.001 30.0 0 -1.5\n"
            "0.000125 .018 0 -.002 30.1 0 -1.6\n"
        )
        rows=watch_rows(p)
        assert len(rows)==2 and pick(rows,.000125)["Displacement0"]==30.1
        assert diff(.018,.017)["relative_difference"]>0.05
        assert pick(rows,.00025) is None
        assert sha(p)==hashlib.sha256(p.read_bytes()).hexdigest()
    print("ACCEPTED_DISPLACEMENT_PRESSURE_AUDIT_SELFTEST_PASS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--base",type=Path,default=Path.home()/"hpcc-fsi")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:return self_test()
    result=report(a.base.expanduser().resolve(strict=True))
    if any(row["continuous_reference"] is None for row in result["accepted_window_comparisons"]):
        print("CAUTION: CONTINUOUS_91543_REFERENCE_MISSING; do not infer match.")
    print(json.dumps(result,indent=2,ensure_ascii=False))
    print("NO_SOURCE_NO_LIVE_JOB_NO_SOLVER_MODIFICATIONS")
if __name__=="__main__":main()
