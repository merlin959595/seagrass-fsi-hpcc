#!/usr/bin/env python3
"""Read-only 8-rank native OpenFOAM binary ALE restart coordinate-consistency audit.

Checks:
    saved current points X(t) vs the motion-solver equation X0 + D(t)
    pointDisplacement in all eight fluid ranks; no OCR, FOAM tools or solver.
    Detects optional polyMesh/points0 at saved time or constant.
    Reports max and high quantile physical displacements and residuals, and
    highlights source-copied 0.0325s input vs failed candidate.

OpenFOAM v2512 displacementLaplacianFvMotionSolver::curPoints uses
    points0() + pointDisplacement_.primitiveField()
in absence of pointLocation override. The solver's actual points0 selection
depends on the points0MotionSolver implementation; report alternate choices
instead of silently assuming how the restart picks X0.

Never writes or deletes user field files. Can run on HPCC login node
using the system Python stdlib; avoids needing external NumPy.
"""
import argparse
import array
import hashlib
import math
from pathlib import Path
import re
import statistics
import sys
import traceback

DEFAULT_SOURCE="fsi-long-stage0-job91006/runs/hpcc-implicit-002/fluid"

def numeric_binary_vectors(path):
    """Read raw OpenFOAM binary vector-list body, requiring closing ')'."""
    b=path.read_bytes()
    if not re.search(rb"\bformat\s+binary\s*;",b[:4096]):
        raise ValueError(f"{path}: only OpenFOAM binary format is supported")
    if not re.search(rb'arch\s+"[^"]*scalar=64[^"]*";',b[:4096]):
        raise ValueError(f"{path}: not 64-bit OpenFOAM scalar storage")
    # List/vector internalField and polyMesh/points use same numeric-list
    # body: count, '(', N x (3 doubles), ')'. Bound to line starts.
    starts=list(re.finditer(
        rb"(?m)^[ \t]*(\d{1,9})[ \t]*\r?\n[ \t]*\(",b[:65536]))
    choices=[]
    for m in starts:
        n=int(m.group(1))
        for offset in (0,1,2):
            start=m.end()+offset
            if offset==1 and b[m.end():m.end()+1] not in (b"\n",b"\r"):
                continue
            if offset==2 and b[m.end():m.end()+2]!=b"\r\n":
                continue
            size=24*n
            if start+size+1>len(b):continue
            trailer=b[start+size:start+size+12]
            if re.match(rb"[ \t\r\n]*\)",trailer):
                choices.append((n,start))
    if not choices:
        raise ValueError(f"{path}: OpenFOAM vector-list binary data was not found")
    # The header/internalField vector list is the first numeric list. Later
    # boundaryField lists may also be valid and must not be selected.
    n,start=choices[0]
    values=array.array("d")
    values.frombytes(b[start:start+n*24])
    if sys.byteorder!="little":values.byteswap()
    if len(values)!=3*n:
        raise RuntimeError(f"Wrong binary length in {path}")
    if any(not math.isfinite(v) for v in values):
        raise RuntimeError(f"Nonfinite coordinate/displacement values in {path}")
    return values

def stats_difference(origin,disp,current):
    if len(origin)!=len(disp) or len(disp)!=len(current):
        raise RuntimeError(
          f"Mesh points and displacement sizes differ: {len(origin)}, {len(disp)}, {len(current)}")
    residuals=[]
    displacement=[]
    xdiff=[]
    for i in range(0,len(origin),3):
        dx,dy,dz=disp[i:i+3]
        rx=origin[i]+dx-current[i]
        ry=origin[i+1]+dy-current[i+1]
        rz=origin[i+2]+dz-current[i+2]
        residuals.append(math.sqrt(rx*rx+ry*ry+rz*rz))
        displacement.append(math.sqrt(dx*dx+dy*dy+dz*dz))
        p=current[i:i+3];q=origin[i:i+3]
        xdiff.append(math.sqrt(sum((p[j]-q[j])**2 for j in range(3))))
    return {"point_count":len(residuals),
       "max_coordinate_residual_m":max(residuals),
       "p99_coordinate_residual_m":sorted(residuals)[min(len(residuals)-1,int(len(residuals)*.99))],
       "mean_coordinate_residual_m":statistics.fmean(residuals),
       "residual_above_1e-6_count":sum(x>1e-6 for x in residuals),
       "max_saved_displacement_m":max(displacement),
       "max_current_minus_reference_m":max(xdiff),
       "max_abs_difference_between_saved_displacement_and_actual_motion_m":
          max(abs(a-b) for a,b in zip(displacement,xdiff)),
    }

def rank_one(folder,idx):
    rank=folder/f"processor{idx}"
    time=rank/"0.0325"
    dispfile=time/"pointDisplacement"
    points=time/"polyMesh/points"
    if not dispfile.is_file() or not points.is_file():
        raise FileNotFoundError(f"Missing critical checkpoint in {rank}")
    disp=numeric_binary_vectors(dispfile)
    now=numeric_binary_vectors(points)
    candidates=[]
    for label,path in (
        ("time_points0",time/"polyMesh/points0"),
        ("constant_points0",rank/"constant/polyMesh/points0"),
        ("zero_points0",rank/"0/polyMesh/points0"),
        ("fallback_constant_points",rank/"constant/polyMesh/points"),
    ):
        if path.is_file():
            origin=numeric_binary_vectors(path)
            diff=stats_difference(origin,disp,now)
            candidates.append((label,path,diff))
    if not candidates:
        raise RuntimeError(f"No points0/constant points available for processor{idx}")
    return candidates,{"has_saved_cellDisplacement":(time/"cellDisplacement").is_file(),
                       "has_constant_points0":(rank/"constant/polyMesh/points0").is_file(),
                       "has_time_points0":(time/"polyMesh/points0").is_file(),
                       "has_pointLocation":(time/"pointLocation").is_file()}

def audit(root):
    worst=0
    allbad=0
    print("READ_ONLY_ALE_COORDINATE_AUDIT_ROOT",root)
    for rank in range(8):
        choices,extras=rank_one(root,rank)
        print(f"RANK={rank} MOTION_STATE={extras}")
        for label,p,s in choices:
            print("  REFERENCE",label,
                  "MAX_RESIDUAL_m={:.9g}".format(s["max_coordinate_residual_m"]),
                  "P99_RESIDUAL_m={:.9g}".format(s["p99_coordinate_residual_m"]),
                  "OUTLIERS_OVER_1um={}".format(s["residual_above_1e-6_count"]),
                  "MAX_SAVED_DISPLACEMENT_m={:.9g}".format(s["max_saved_displacement_m"]),
                  "MAX_GEOMETRIC_MOVEMENT_m={:.9g}".format(s["max_current_minus_reference_m"]),
                  "NUM_POINTS={}".format(s["point_count"]))
            if label=="fallback_constant_points":
                worst=max(worst,s["max_coordinate_residual_m"])
                allbad+=s["residual_above_1e-6_count"]
    print("FALLBACK_CONSTANT_POINTS_MAX_RESIDUAL_m",f"{worst:.10g}")
    print("FALLBACK_CONSTANT_POINTS_TOTAL_ABOVE_1um",allbad)
    if allbad:
        print("EVIDENCE_OF_ALERESUME_REFERENCE_INCONSISTENCY_IN_FALLBACK")
    else:
        print("FALLBACK_REFERENCE_CONSISTENCY_PASSES_1um_CHECK")
    print("CAUTION: Need to confirm which points0 path native solver selected.")
    print("NO_SOLVER_RUN_NO_FILE_MODIFICATIONS")

def self_test():
    import tempfile
    def binary_vectors(path,vectors,field=True):
        # Minimal stand-in 64bit OpenFOAM binary field with real header/trailer.
        n=len(vectors)//3
        hd=(b"FoamFile\n{\n  version 2.0;\n  format binary;\n"
            b"  arch \"LSB;label=32;scalar=64\";\n"
            b"  class pointVectorField;\n  object pointDisplacement;\n}\n")
        if field:hd+=b"dimensions [0 1 0 0 0 0 0];\ninternalField nonuniform List<vector>\n"
        raw=array.array("d",vectors)
        if sys.byteorder!="little":raw.byteswap()
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(hd+str(n).encode()+b"\n("+raw.tobytes()+b"\n)\n;\n")
    with tempfile.TemporaryDirectory() as d:
        d=Path(d)
        a=[0.,0.,0.,1.,0.,0.]
        disp=[.1,0.,0.,.2,0.,0.]
        cur=[.1,0.,0.,1.2,0.,0.]
        for name,data,field in (("a",a,False),("d",disp,True),("p",cur,False)):
            binary_vectors(d/name,data,field)
        parsed={f:numeric_binary_vectors(d/f) for f in ("a","d","p")}
        check=stats_difference(parsed["a"],parsed["d"],parsed["p"])
        assert check["max_coordinate_residual_m"]<1e-14
        bad=stats_difference(parsed["p"],parsed["d"],parsed["p"])
        assert bad["max_coordinate_residual_m"]>.1
    print("BINARY_ALE_COORDINATE_READER_TEST_PASS")

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base",type=Path,default=Path.home()/"hpcc-fsi")
    p.add_argument("--source",type=Path,help="Absolute fluid folder; default certified 91006")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:self_test();return
    base=a.base.expanduser().resolve(strict=True)
    root=(a.source or base/DEFAULT_SOURCE).expanduser().resolve(strict=True)
    if not root.is_relative_to(base):
        raise RuntimeError("Refusing data outside approved hpcc-fsi folder")
    audit(root)

if __name__=="__main__":
    main()
