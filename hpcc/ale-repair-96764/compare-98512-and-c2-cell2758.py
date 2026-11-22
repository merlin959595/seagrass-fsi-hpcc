#!/usr/bin/env python3
"""Read-only, zero-Slurm forensic comparison of the *same* concave cell 2758.

Uses native checkMesh copies (98512 first failure, C2 97576 later failure)
and the already CI-tested OpenFOAM binary/compact polyMesh reader in
audit-cell2758-geometry-readonly.py. NEVER edits checkpoints or solver files.
No FSI and no additional checkMesh runs.
"""
from pathlib import Path
import hashlib
import itertools
import importlib.util
import math
import os
import sys
import re

RANK=5
CELL=2758
CRITICAL=(9315,9306)
CASE_NAMES=(
    ("98512 targeted bed+2x", "native-first-window-98512", "0.5635", "0.563625"),
    ("97576 C2 reference", "native-concavity-97576-c2", "0.5805", "0.58075"),
)

def fail(msg):
    raise RuntimeError("READ_ONLY_2758_DIAGNOSTIC_ABORTED: "+msg)

def load_shared():
    path=Path(__file__).resolve().parent/"audit-cell2758-geometry-readonly.py"
    if not path.is_file():
        fail("MISSING_PINNED_SHARED_BINARY_MESH_READER "+str(path))
    spec=importlib.util.spec_from_file_location("fsi_bed2758_binary_mesh",path)
    reader=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    return reader

def projection(reader,face1,face2,owner,coords):
    sign=1 if owner[CRITICAL[0]]==CELL else -1
    return reader.projection_of_face_pair(coords,face1,face2,sign)


def exact_vertex_contribution(reader,p0,p1,face1,face2,sign):
    """Exact Shapley-style projection decomposition over the moving vertices.

    Each of the at-most-six joint-face vertices is swapped from the earlier to
    the later observed coordinate, one at a time. Average the *difference* in
    the signed face-centre-normal projection over all permutations of moving
    vertices. This exactly telescopes to the observed endpoint delta, avoids
    approximate gradient/quadrature error for large (~1 mm) mesh motions, and
    is symmetric across vertex orderings. Counterfactual intermediate faces
    are diagnostic constructs, NOT reconstructed OpenFOAM simulation steps,
    and the resulting attributions are not a unique physical causal split.
    """
    vertices=sorted(set(face1+face2))
    moving=[i for i in vertices
            if any(abs(p1[i][j]-p0[i][j])>1e-15 for j in range(3))]
    if len(moving)>7:fail("EXACT_VERTEX_ATTRIBUTION_TOO_MANY_VERTICES")
    base=reader.projection_of_face_pair(p0,face1,face2,sign)
    end=reader.projection_of_face_pair(p1,face1,face2,sign)
    contribution={i:0. for i in vertices}
    count=0
    for ordering in itertools.permutations(moving):
        hybrid=list(p0)
        prev=base
        for i in ordering:
            hybrid[i]=p1[i]
            current=reader.projection_of_face_pair(hybrid,face1,face2,sign)
            contribution[i]+=(current-prev)
            prev=current
        if abs(prev-end)>1e-10:
            fail("EXACT_VERTEX_FINAL_HYBRID_NOT_MATCHED")
        count+=1
    for i in moving:
        contribution[i]/=count
    total=sum(contribution.values())
    err=total-(end-base)
    if abs(err)>1e-12:
        fail("EXACT_VERTEX_CONTRIBUTION_TELESCOPING_MISMATCH "+repr(err))
    return {
      "method":"exact_permutation_averaged_counterfactual_shapley",
      "number_of_moving_vertices":len(moving),
      "number_of_vertex_orders":count,
      "start_projection_m":base,
      "end_projection_m":end,
      "net_observed_change_m":end-base,
      "sum_vertex_contributions_m":total,
      "closure_error_m":err,
      "vertex_contributions_m":dict(sorted(contribution.items(),
                                key=lambda kv:abs(kv[1]),reverse=True)),
      "interpretation":"attribution diagnostic only; not a physical force, solver fix or trajectory",
    }

def inspect(label,proc,t0,t1,reader):
    poly=proc/"constant/polyMesh"
    owner=reader.labels(poly/"owner")
    neighbour=reader.labels(poly/"neighbour")
    p0=reader.points(proc/t0/"polyMesh/points")
    p1=reader.points(proc/t1/"polyMesh/points")
    if len(p0)!=len(p1):fail("POINT_COUNT_CHANGED "+label)
    faces=reader.faces(poly/"faces",len(owner),len(p0))
    if not all(0<=a<len(neighbour) for a in CRITICAL):fail("CRITICAL_FACES_NOT_INTERNAL")
    cell_faces=sorted(set(
        [i for i,a in enumerate(owner) if a==CELL]
        +[i for i,a in enumerate(neighbour) if a==CELL]))
    if len(cell_faces)!=6:fail("EXPECTED_CELL_HAS_NOT_SIX_FACES "+label+" "+str(cell_faces))
    if not all(i in cell_faces for i in CRITICAL):fail("CRITICAL_FACES_DIFFER "+label)
    if any(v<0 or v>=len(p0) for fid in cell_faces for v in faces[fid]):
        fail("POLYMESH_VERTEX_INDEX_OUT_OF_RANGE")
    facepairs=[(fi,faces[fi]) for fi in cell_faces]
    pairdata=[]
    print("\n========",label,"========")
    print("CELL",CELL,"FACES",cell_faces,"TIMES",t0,t1)
    for t,coords in ((t0,p0),(t1,p1)):
        scores=reader.cell_face_centre_concavity_proxy(facepairs,coords,CELL,owner)
        print("CRITICAL_MAX_FACE_CENTRE_PAIR time=",t," pair=",scores[0],sep="")
        for score in scores[:3]:
            print("TOP_FACE_CENTRE_PAIR",t,score)
        r=reader.geom(facepairs,None,coords,CELL,owner)
        print("CELL_CENTROID_M",t,r["centroid_m"])
        sign=1 if owner[CRITICAL[0]]==CELL else -1
        crit=reader.projection_of_face_pair(coords,faces[CRITICAL[0]],faces[CRITICAL[1]],sign)
        print("PAIR_9315_TO_9306_PROJECTED_NORMAL_UM",t,crit*1e6)
        pairdata.append((scores[0],crit))
    sign=1 if owner[CRITICAL[0]]==CELL else -1
    motion=reader.critical_face_pair_motion_decomposition(
        p0,p1,faces[CRITICAL[0]],faces[CRITICAL[1]],outward_sign=sign)
    print("CRITICAL_PAIR_DECOMPOSITION",
          {k:v for k,v in motion.items() if
            k in ("projection_change_m",
                  "due_to_relative_face_centre_m",
                  "due_to_face1_normal_rotation_m",
                  "face1_normal_angle_deg")})
    tracked=sorted(set(faces[CRITICAL[0]]+faces[CRITICAL[1]]))
    for v in tracked:
        dv=tuple((p1[v][d]-p0[v][d])*1e6 for d in range(3))
        print("CRITICAL_VERTEX_DELTA_UM",v,dv)
    # Exact endpoint decomposition avoids the first-order 16-step path
    # quadrature failure at nearly one millimetre of observed motion.
    sensitivity=exact_vertex_contribution(
        reader,p0,p1,faces[CRITICAL[0]],faces[CRITICAL[1]],sign)
    print("EXACT_SYMMETRIC_VERTEX_PROJECTION_ATTRIBUTION",{
        "orders":sensitivity["number_of_vertex_orders"],
        "method":sensitivity["method"],
        "signed_vertex_contributions_um":{
            k:round(v*1e6,9) for k,v in sensitivity["vertex_contributions_m"].items()},
        "sum_um":sensitivity["sum_vertex_contributions_m"]*1e6,
        "net_um":sensitivity["net_observed_change_m"]*1e6,
        "closure_um":sensitivity["closure_error_m"]*1e6,
        "warning":sensitivity["interpretation"],
    })
    print("DELTA_PROJECTION_UM",motion["projection_change_m"]*1e6)
    # Native checkMesh records are the authoritative pass/fail indicators.
    for t in (t0,t1):
        if label.startswith("97576"):
            log=proc.parent/f"checkMesh-r1-{t}.log"
        else:
            log=proc.parent/f"checkMesh-{t}.log"
        if log.is_file():
            txt=log.read_text(errors="replace")
            relevant=[line.strip() for line in txt.splitlines()
                       if re.search(r"Concave cell check OK|Concave cells|Error in face tets|Mesh OK|Failed \d+ mesh checks",line,re.I)]
            print("NATIVE_CHECKMESH_VERDICT",t,relevant[-8:])
        else:
            print("NATIVE_CHECKMESH_LOG_NOT_FOUND",t,"skip")
    return {"start_pts":p0,"end_pts":p1,
            "start_critical_um":pairdata[0][1]*1e6,
            "end_critical_um":pairdata[1][1]*1e6,
            "start_best":pairdata[0][0],"end_best":pairdata[1][0]}

def main():
    user=os.environ.get("USER")
    if not user:fail("USER_NOT_SET")
    root=Path("/data/icto")/user/"seagrass-fsi558-runs.sNIpi9/diagnostics"
    reader=load_shared()
    out={}
    for label,dirname,t0,t1 in CASE_NAMES:
        proc=root/dirname/"processor5"
        if not proc.is_dir():fail("SAVED_NATIVE_GEOMETRY_DIAGNOSTIC_MISSING "+str(proc))
        out[dirname]=inspect(label,proc,t0,t1,reader)
    left=out["native-first-window-98512"]
    right=out["native-concavity-97576-c2"]
    # Careful: C2's comparable stored snapshot at 0.5805 is a LATER TIME
    # and must never be called "same-time" reference.
    print("\n======== SUMMARY ========")
    print("98512_FIRST_STEP_PROJECTION_START_UM",left["start_critical_um"])
    print("98512_FIRST_STEP_PROJECTION_END_UM",left["end_critical_um"])
    print("C2_LATER_SNAPSHOT_BEFORE_FAILURE_PROJECTION_UM",right["start_critical_um"])
    print("C2_LATER_SNAPSHOT_AFTER_FAILURE_PROJECTION_UM",right["end_critical_um"])
    base98512=Path("/data/icto")/user/"seagrass-fsi558-runs.sNIpi9/trial-98512-bed2758-s1/runs/hpcc-implicit-002/fluid/processor5/0.5635/polyMesh/points"
    base97576=Path("/data/icto")/user/"seagrass-fsi558-runs.sNIpi9/trial-97576-repair96764-c2-stage1/runs/hpcc-implicit-002/fluid/processor5/0.5635/polyMesh/points"
    if base98512.is_file() and base97576.is_file():
        ptsa=reader.points(base98512)
        ptsb=reader.points(base97576)
        if len(ptsa)!=len(ptsb): fail("SOURCE_CHECKPOINT_VERTEX_COUNT_CHANGED")
        maxdiff=max(math.dist(a,b) for a,b in zip(ptsa,ptsb))
        print("C2_VS_98512_SAME_TIME_0P5635_INITIAL_MESH_MAX_VERTEX_DIFF_M",maxdiff)
        print("CAUTION_THIS_IS_ONLY_FLUID_MESH_ALIGNMENT_NOT_FULL_FSI_RESTART_EQUIVALENCE")
    else:
        print("C2_VS_98512_INITIAL_MESH_COMPARISON_UNAVAILABLE")
    print("WARNING_TIMEPOINTS_DIFFER: cannot infer relative C2 vs 98512 response "
          "at t=0.563625 because C2 first step was not saved")
    failedset=root/"native-first-window-98512/processor5/0.563625/polyMesh/sets/concaveCells"
    if not failedset.is_file():fail("EXPECTED_NATIVE_98512_CONCAVE_CELLSET_MISSING")
    settxt=failedset.read_text()
    if not re.search(r"(?m)^1\(2758\)\s*$",settxt):
        fail("NATIVE_SET_IS_NOT_UNIQUE_CELL2758")
    print("NATIVE_98512_CELL2758_ONLY_CONCAVE_RANK5_CONFIRMED")
    print("CONCLUSIONS_ONLY_AFTER_CHECKING_NATIVE_PAIR_CROSSING_AND_CELL_SETS")
    print("READONLY_ANALYSIS_FINISHED_NO_OUTPUT_FILES_CHANGED_NO_SLURM_SUBMITTED")

if __name__=="__main__":
    try:main()
    except Exception as exc:
        print("AUDIT_FATAL",type(exc).__name__,str(exc),file=sys.stderr)
        raise
