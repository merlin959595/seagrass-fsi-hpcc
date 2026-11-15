#!/usr/bin/env python3
"""Read-only postmortem for long stage0 91006; no solver, no data edits.

Locate *all* maximum mesh-Courant values by physical time and trace each
around its neighboring diagnostic lines. Cross-check 240 preCICE accepted
windows, 8 fluid checkpoints, and CalculiX new restart state; distinguish
coupling success from mandatory mesh-motion safety qualification.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import statistics

RUN="fsi-long-stage0-job91006"
START=.0025
FINAL=.0325
DT=.000125
FLOAT=r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
TIME=re.compile(r"^\s*Time\s*=\s*("+FLOAT+r")\s*$")
MESHCO=re.compile(r"Mesh Courant Number mean:\s*("+FLOAT+r")\s+max:\s*("+FLOAT+r")")
FLUIDCO=re.compile(r"(?<!Mesh )Courant Number mean:\s*("+FLOAT+r")\s+max:\s*("+FLOAT+r")")
GUARD=re.compile(r"SEAGRASS_MESH_GUARD\s+time=("+FLOAT+r")\s+minVolume=("+FLOAT+r")"
  r"\s+concave=(\d+)\s+qualityFailed=(\d+)\s+skewFailed=(\d+)"
  r"\s+orthFailed=(\d+)\s+tetFailed=(\d+)")
ITER_HEADER="TimeWindow TotalIterations Iterations Convergence QNColumns DeletedQNColumns DroppedQNColumns"

def digest(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for x in iter(lambda:f.read(1024*1024),b""):
            h.update(x)
    return h.hexdigest()

def read_iteration(path):
    with path.open() as f:
        lines=[s.strip() for s in f if s.strip()]
    if not lines or lines[0].split()!=ITER_HEADER.split():
        raise RuntimeError("preCICE iterations header unexpected")
    rows=[]
    for index,line in enumerate(lines[1:],1):
        vals=[int(v) for v in line.split()]
        if len(vals)!=7 or vals[0]!=index or not (1<=vals[2]<=50) or vals[3]!=1:
            raise RuntimeError(f"Failed preCICE accepted iteration row {index}: {vals}")
        if vals[1]!=(rows[-1][1] if rows else 0)+vals[2]:
            raise RuntimeError(f"Cumulative preCICE total mismatch at {index}")
        rows.append(vals)
    return rows

def trace_log(path):
    events=[]
    guards=[]
    context=[]
    current_time=None
    count=0
    with path.open(errors="replace") as f:
        for line_no,line in enumerate(f,1):
            m=TIME.match(line)
            if m:current_time=float(m.group(1))
            if "Mesh Courant Number mean:" in line:
                found=MESHCO.search(line)
                if found:
                    value=float(found.group(2))
                    events.append({"source_line":line_no,
                        "time_s":current_time,"meshCo":value,
                        "mean_meshCo":float(found.group(1))})
            found=GUARD.search(line)
            if found:
                guards.append({
                    "source_line":line_no,"time_s":float(found.group(1)),
                    "min_volume_m3":float(found.group(2)),
                    "quality_counts":[int(v) for v in found.groups()[2:]],
                })
            count=line_no
    return events,guards,count

def checkpoint(root):
    solid=root/"solid"
    ss={}
    for original,new,name in (
        ("seagrass.rin","seagrass.rout","calculix"),
        ("kinematic_state.input.bin","kinematic_state.bin","persistent_kinematics"),
    ):
        a,b=solid/original,solid/new
        if a.is_file() and b.is_file():
            ha,hb=digest(a),digest(b)
            ss[name]={"input_bytes":a.stat().st_size,"output_bytes":b.stat().st_size,
                      "input_sha256":ha,"output_sha256":hb,"advanced":ha!=hb}
        else:
            ss[name]={"present":False}
    ranks=[]
    for i in range(8):
        folder=root/f"fluid/processor{i}"
        numeric=[]
        if folder.is_dir():
            for p in folder.iterdir():
                if p.is_dir():
                    try:
                        t=float(p.name)
                        if math.isfinite(t):numeric.append((t,p))
                    except ValueError:pass
        t,d=max(numeric,key=lambda x:x[0]) if numeric else (None,None)
        fields=all((d/p).is_file() for p in (
            "U","p","phi","pointDisplacement","polyMesh/points","uniform/time")) if d else False
        ranks.append({"rank":i,"latest_time_s":t,"complete_fields":fields})
    return {"solid":ss,"fluid":ranks}

def classify(records):
    if not records:return {}
    high=[r for r in records if r["meshCo"]>.5]
    assigned=0
    by_window={}
    for e in high:
        t=e["time_s"]
        if t is not None:
            index=round((t-START)/DT)
            if abs((START+index*DT)-t)<1e-8 and 1<=index<=240:
                assigned+=1
                by_window[index]=max(by_window.get(index,0),e["meshCo"])
    values=sorted(r["meshCo"] for r in records)
    return {"meshCo_count":len(records),
      "peak_meshCo":max(values),
      "meshCo_high_over_0.5_count":len(high),
      "meshCo_high_over_1_count":sum(r["meshCo"]>1 for r in records),
      "meshCo_99th_percentile":values[math.ceil(.99*len(values))-1],
      "meshCo_high_time_mapped_count":assigned,
      "max_per_high_window":dict(sorted(by_window.items())),
      "top_20_events":sorted(records,key=lambda x:x["meshCo"],reverse=True)[:20],
      "first_high_events":high[:10],
      "last_high_events":high[-10:],
      "uncertain":"Time labels identify the OpenFOAM attempted physical step. "
                  "A log label alone does NOT prove whether that nonlinear/coupling attempt was accepted."}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base",type=Path,default=Path.home()/"hpcc-fsi")
    p.add_argument("--out",type=Path)
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:
        assert MESHCO.search("Mesh Courant Number mean: 0.0001 max: 4.1804180367424")
        assert FLUIDCO.search("Courant Number mean: .012 max: 0.42")
        assert not FLUIDCO.search("Mesh Courant Number mean: .012 max: 0.42")
        assert TIME.match("Time = 0.0325")
        print("FSI_91006_MESHCO_POSTMORTEM_STATIC_PASS")
        return
    base=a.base.expanduser().resolve(strict=True)
    work=base/RUN
    root=work/"runs/hpcc-implicit-002"
    state=json.loads((work/"STATE.json").read_text())
    rows=read_iteration(root/"solid/precice-Solid-iterations.log")
    events,guards,lines=trace_log(work/"fluid.log")
    files=checkpoint(root)
    fluidco=[]
    with (work/"fluid.log").open(errors="replace") as f:
        for line in f:
            if "Courant Number mean:" in line:
                m=FLUIDCO.search(line)
                if m:fluidco.append(float(m.group(2)))
    report={
       "status":"READ_ONLY_EVIDENCE_NOT_PRODUCTION_ACCEPTANCE",
       "job":91006,"original_state":state,
       "accepted_coupling_windows":len(rows),
       "coupling_iterations_total":sum(r[2] for r in rows),
       "last_window":rows[-1] if rows else None,
       "fluid_log_lines":lines,
       "fluid_co_max":max(fluidco) if fluidco else None,
       "meshCo":classify(events),
       "guard_count":len(guards),
       "guard_failed_count":sum(1 for g in guards if g["min_volume_m3"]<=0 or any(g["quality_counts"])),
       "last_guard":guards[-1] if guards else None,
       "min_guard_volume_m3":min((g["min_volume_m3"] for g in guards),default=None),
       "checkpoints":files,
       "strict_safety_gate":"UNRESOLVED: meshCo exceeded 0.5; do not auto-promote failed case",
    }
    print("WINDOWS",report["accepted_coupling_windows"],"ITERATIONS",report["coupling_iterations_total"])
    print("PEAK_FLUID_CO",report["fluid_co_max"])
    print("PEAK_MESH_CO",report["meshCo"].get("peak_meshCo"))
    print("MESH_CO_OVER_0.5_EVENTS",report["meshCo"].get("meshCo_high_over_0.5_count"))
    print("MESH_CO_OVER_1_EVENTS",report["meshCo"].get("meshCo_high_over_1_count"))
    print("MESH_CO_HIGH_WINDOWS",json.dumps(report["meshCo"].get("max_per_high_window",{})))
    for item in report["meshCo"].get("top_20_events",[]):
        print("TOP_MESHCO",item)
    print("ALE_GUARD_COUNT",report["guard_count"],"FAILED",report["guard_failed_count"])
    print("FINAL_GUARD",report["last_guard"])
    for k,v in files["solid"].items():
        print("SOLID_CHECKPOINT",k,v)
    print("FLUID_CHECKPOINTS",files["fluid"])
    print("AUTO_CHAIN_NOT_AUTHORIZED_WITH_FAILED_COURANT_GATE")
    if a.out:
        out=a.out.expanduser().resolve()
        if not out.is_relative_to(base) or out.suffix!=".json":
            raise RuntimeError("Output must be new JSON within hpcc-fsi")
        for r in (RUN,"performance-full160-job-89038","g1-b10-job-90873"):
            if out.is_relative_to(base/r):raise RuntimeError("Cannot write into original cases")
        with out.open("x") as f:json.dump(report,f,indent=2,ensure_ascii=False)
        print("DIAG_REPORT",out)

if __name__=="__main__":
    main()
