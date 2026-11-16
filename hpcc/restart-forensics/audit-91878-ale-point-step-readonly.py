#!/usr/bin/env python3
"""Compare first restarted ALE mesh point motion to final prior source step.

Read-only across 8 MPI ranks. Does not invoke Slurm, OpenFOAM, preCICE, or CCX.
Requires audit-binary-ale-coordinates.py from the same repo / local directory.
"""
import argparse
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import hashlib

SOURCE_REL="fsi-long-stage0-job91006/runs/hpcc-implicit-002/fluid"
TRIAL_REL="crossjob-fix-20261116/force-ab-tests/trial-91878/runs/hpcc-implicit-002/fluid"
TIMES=(("source_prior", "0.032375", "0.0325"),
       ("trial_first","0.0325","0.032625"),
       ("trial_second","0.032625","0.03275"))
FILES=("polyMesh/points","pointDisplacement")

def time_dir(processor, number):
    """Resolve actual numeric time-folder spelling, never invent .0325."""
    if not processor.is_dir():
        raise FileNotFoundError(f"Missing processor directory {processor}")
    target=float(number)
    matches=[]
    for entry in processor.iterdir():
        if not entry.is_dir(): continue
        try: value=float(entry.name)
        except ValueError: continue
        if math.isfinite(value) and abs(value-target)<1e-11:
            matches.append(entry)
    if len(matches)!=1:
        raise RuntimeError(f"Time {number} in {processor}: {len(matches)} "
                           f"matching directories; existing numeric folders="
                           f"{sorted(x.name for x in processor.iterdir() if x.is_dir())}")
    return matches[0]

def parser_module():
    path=Path(__file__).resolve().with_name("audit-binary-ale-coordinates.py")
    if not path.is_file():
        path=Path(__file__).resolve().parent.parent/"clean-production/audit-binary-ale-coordinates.py"
    if not path.is_file():
        raise RuntimeError("Missing pinned read-only native OpenFOAM binary reader: "+str(path))
    spec=importlib.util.spec_from_file_location("native_foam_binary_reader",path)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def delta_stats(a,b):
    if len(a)!=len(b) or len(a)%3:
        raise RuntimeError(f"Mismatch in point-list size: {len(a)} {len(b)}")
    norms=[]
    signed_x=0.0
    for k in range(0,len(a),3):
        dx=b[k]-a[k];dy=b[k+1]-a[k+1];dz=b[k+2]-a[k+2]
        norms.append(math.sqrt(dx*dx+dy*dy+dz*dz))
        signed_x+=dx
    norms.sort()
    n=len(norms)
    return {
        "nodes":n,
        "mean_m":sum(norms)/n if n else None,
        "p99_m":norms[min(n-1,int(n*.99))] if n else None,
        "max_m":norms[-1] if n else None,
        "signed_mean_dx_m":signed_x/n if n else None,
        "nodes_moved_over_1um":sum(x>1e-6 for x in norms),
    }

def normmax_residual(x,d,ref):
    if len(x)!=len(d) or len(x)!=len(ref) or len(x)%3:
        return None
    maxres=0.0
    for k in range(0,len(x),3):
        res=math.sqrt(sum((x[k+j]-d[k+j]-ref[k+j])**2 for j in range(3)))
        if res>maxres:maxres=res
    return maxres

def digest(path):
    if not path.is_file():return None
    h=hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda:stream.read(1<<20),b""):
            h.update(block)
    return h.hexdigest()

def rank_one(base,rank,readvec):
    old=base/SOURCE_REL/f"processor{rank}"
    now=base/TRIAL_REL/f"processor{rank}"
    result={"rank":rank,"windows":{},"saved_t0_byte_equal":{},
            "geometry_reference_residuals":{}}
    source0=time_dir(old,"0.0325")
    trial0=time_dir(now,"0.0325")
    for field in FILES:
        p=source0/field
        q=trial0/field
        a=digest(p);b=digest(q)
        result["saved_t0_byte_equal"][field]=(a==b) if a and b else None
    for label,t0,t1 in TIMES:
        root=old if label=="source_prior" else now
        section={}
        from_time=time_dir(root,t0)
        to_time=time_dir(root,t1)
        for field in FILES:
            p=from_time/field
            q=to_time/field
            if not p.is_file() or not q.is_file():
                section[field]={"available":False,"missing":[str(f)
                           for f in (p,q) if not f.is_file()]}
                continue
            a=readvec(p);b=readvec(q)
            section[field]={"available":True,"change":delta_stats(a,b)}
            if field=="polyMesh/points":
                ref=root/"constant/polyMesh/points"
                field_d=to_time/"pointDisplacement"
                if ref.is_file() and field_d.is_file():
                    section["saved_geometry_minus_reference_plus_displacement_max_m"] = (
                       normmax_residual(b,readvec(field_d),readvec(ref)))
        result["windows"][label]=section
    return result

def summarise(results):
    lines=["READ_ONLY_ALE_MOTION_STEP_COMPARE source_91006 vs trial_91878"]
    for r in results["per_rank"]:
        lines.append(f"RANK={r['rank']} t0_fields_identical={r['saved_t0_byte_equal']}")
        for k,w in r["windows"].items():
            d=w.get("polyMesh/points",{})
            if d.get("available"):
                lines.append(f"  {k} ACTUAL_MESH_NODE_DELTA={d['change']}")
            else:
                lines.append(f"  {k} ACTUAL_MESH_NODE_DELTA=UNAVAILABLE {d.get('missing')}")
            d=w.get("pointDisplacement",{})
            if d.get("available"):
                lines.append(f"  {k} POINT_DISPLACEMENT_FIELD_DELTA={d['change']}")
            else:
                lines.append(f"  {k} POINT_DISPLACEMENT_FIELD_DELTA=UNAVAILABLE {d.get('missing')}")
            lines.append(f"  {k} GEOMETRY_REFERENCE_RESIDUAL_M="
                         f"{w.get('saved_geometry_minus_reference_plus_displacement_max_m')}")
    lines.append("IMPORTANT: source_prior is actual physical delta 0.032375->0.0325; "
                 "trial_first actual delta 0.0325->0.032625. They are neighboring "
                 "different steps, not identical physical states.")
    lines.append("IMPORTANT: no 91543 t=0.032625 mesh snapshot is assumed available; "
                 "this is not an exact continuous-vs-restart mesh comparison.")
    lines.append("NO_SLURM_NO_SOLVER_NO_SOURCE_OR_LIVE_DATA_WRITES")
    return "\n".join(lines)

def check_input(base):
    root=base/SOURCE_REL
    if not root.is_dir(): raise RuntimeError("Missing original 91006 fluid source")
    trial=base/TRIAL_REL
    if not trial.is_dir():raise RuntimeError("Missing 91878 FSI trial fluid case")
    return root,trial

def self_test():
    assert abs(delta_stats([0,0,0,1,0,0],[.001,0,0,1.002,0,0])["max_m"]-.002)<1e-12
    assert normmax_residual([1,2,3],[.2,.3,.4],[.8,1.7,2.6])<1e-12
    assert normmax_residual([1,2,3],[.2,.3,.4],[.7,1.7,2.6])>.09
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)/"sample"
        p.write_bytes(b"abc")
        assert digest(p)==hashlib.sha256(b"abc").hexdigest()
        proc=Path(d)/"processor0"
        (proc/"0.0325").mkdir(parents=True)
        (proc/"0.032375").mkdir()
        assert time_dir(proc,".0325").name=="0.0325"
        assert time_dir(proc,"0.032375").name=="0.032375"
        assert time_dir(proc,"0.0325").name=="0.0325"
        (proc/".0325").mkdir()
        try: time_dir(proc,"0.0325")
        except RuntimeError as err:assert "matching directories" in str(err)
        else:raise AssertionError("Ambiguous numeric time directory accepted")
    print("ALE_POINT_STEP_DIFFERENTIAL_SELFTEST_PASS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--base",type=Path,default=Path.home()/"hpcc-fsi")
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--summary",action="store_true")
    a=p.parse_args()
    if a.self_test:return self_test()
    base=a.base.expanduser().resolve(strict=True)
    check_input(base)
    reader=parser_module().numeric_binary_vectors
    result={
      "audit":"READ_ONLY_91878_ALE_RESTART_POINT_AND_DISPLACEMENT_HISTORY",
      "per_rank":[rank_one(base,i,reader) for i in range(8)],
      "comparison_window_s":.000125,
      "changes_to_inputs":False
    }
    print(summarise(result) if a.summary else
          json.dumps(result,indent=2,ensure_ascii=False))
    print("NO_SOLVER_NO_SBATCH_NO_SOURCE_OR_LIVE_FILES_MODIFIED")
if __name__=="__main__":main()
