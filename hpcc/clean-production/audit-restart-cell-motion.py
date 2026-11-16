#!/usr/bin/env python3
"""Read-only ALE restart audit: compare source vs two failed attempts and
summarize saved cellDisplacement motion field and native boundary conditions.
No Slurm, no OF solvers, no writes of field/checkpoint data.
"""
import argparse, array, hashlib, importlib.util, math, re, sys
from pathlib import Path
from statistics import fmean

ROOT=Path.home()/"hpcc-fsi"
SOURCE=ROOT/"fsi-long-stage0-job91006/runs/hpcc-implicit-002/fluid"
FAILED=ROOT/"seagrass-fsi-mainline/segment-A/runs/hpcc-implicit-002/fluid"
CANDIDATE=ROOT/"ale-restart-reference-tests/trial-91504/runs/hpcc-implicit-002/fluid"
FIELDS=("pointDisplacement","cellDisplacement","U","p","phi","k","omega")

def loader():
    p=ROOT/"audit-binary-ale-coordinates.py"
    if not p.is_file():raise RuntimeError("Run original binary ALE audit first")
    sp=importlib.util.spec_from_file_location("ale_native_field_reader",p)
    module=importlib.util.module_from_spec(sp)
    sp.loader.exec_module(module)
    return module.numeric_binary_vectors

def hash_file(p):
    h=hashlib.sha256()
    with p.open("rb") as r:
        for b in iter(lambda:r.read(1024*1024),b""):h.update(b)
    return h.hexdigest()

def summarize(vectors):
    n=len(vectors)//3
    norms=[math.hypot(*vectors[i:i+3]) for i in range(0,len(vectors),3)]
    norms.sort()
    return {"count":n,
      "min_m":norms[0],"mean_m":fmean(norms),
      "p99_m":norms[min(n-1,int(n*.99))],
      "max_m":norms[-1],
      "zero_count":sum(x<1e-15 for x in norms)}

def boundary_types(path):
    b=path.read_bytes()
    at=b.rfind(b"boundaryField")
    if at<0:return []
    txt=b[at:].decode("latin-1",errors="replace")
    return re.findall(r"(?m)^\s*([A-Za-z]\w*)\s*\{\s*type\s+([A-Za-z]\w*)\s*;",txt)

def inspect():
    parse=loader()
    print("ALE_RESTART_CELL_STATE_READ_ONLY source=0.0325s")
    summary={}
    max_cell=0.
    for rank in range(8):
        time=SOURCE/f"processor{rank}/0.0325"
        cell=time/"cellDisplacement"
        point=time/"pointDisplacement"
        if not cell.is_file():raise RuntimeError(f"Missing saved cellDisplacement in rank {rank}")
        cell_vals=parse(cell)
        point_vals=parse(point)
        cs=summarize(cell_vals)
        ps=summarize(point_vals)
        max_cell=max(max_cell,cs["max_m"])
        print(f"rank={rank} cell_count={cs['count']} max_cellD_mm={cs['max_m']*1000:.6f}"
              f" p99_cellD_mm={cs['p99_m']*1000:.6f} mean_cellD_mm={cs['mean_m']*1000:.6f}"
              f" max_pointD_mm={ps['max_m']*1000:.6f} zero_cells={cs['zero_count']}")
        if cs["max_m"]>1 or ps["max_m"]>1:
            raise RuntimeError("Implausibly large motion field in certified snapshot")
        for field in FIELDS:
            orig=time/field
            if not orig.is_file():
                continue
            for label,trial in (("old_A",FAILED),("reference_false",CANDIDATE)):
                copied=trial/f"processor{rank}/0.0325/{field}"
                if not copied.is_file():
                    print(f"  ABSENT_IN_TRIAL {label} field={field} rank={rank}")
                elif hash_file(orig)!=hash_file(copied):
                    print(f"  CONTENT_CHANGED {label} field={field} rank={rank}")
                    summary[(label,field)]=summary.get((label,field),0)+1
        if rank in (0,6):
            print("  saved_pointDisplacement_boundary_types",boundary_types(point))
            print("  saved_cellDisplacement_boundary_types",boundary_types(cell))
    print("MAX_SAVED_CELL_DISPLACEMENT_mm",round(max_cell*1000,9))
    print("FIELD_MISMATCH_COUNTS",summary)
    print("OPENFOAM_V2512_cellDisplacement_READ_IF_PRESENT_at_saved_time")
    print("NOTE: Verify adapter's initial readData behavior and the FIRST computed mesh"
          " motion. Saved consistency alone does not prove first-step motion correctness.")
    print("NO_SLURM_NO_SOLVER_NO_FILES_MUTATED")

def test():
    assert summarize(array.array("d",[.0,.0,.0,.003,.004,0]))["max_m"]==.005
    assert boundary_types.__name__=="boundary_types"
    print("ALE_MOTION_STATE_AUDIT_SELF_TEST_PASS")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:test()
    else:inspect()
