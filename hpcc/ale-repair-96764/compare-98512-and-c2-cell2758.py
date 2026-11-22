#!/usr/bin/env python3
"""Read-only, zero-Slurm forensic comparison of the *same* concave cell 2758.

Uses native checkMesh copies (98512 first failure, C2 97576 later failure)
and the already CI-tested OpenFOAM binary/compact polyMesh reader in
audit-cell2758-geometry-readonly.py. NEVER edits checkpoints or solver files.
No FSI and no additional checkMesh runs.
"""
from pathlib import Path
import hashlib
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
    sensitivity=reader.finite_difference_vertex_attribution(
        p0,p1,faces[CRITICAL[0]],faces[CRITICAL[1]],sign)
    if abs(sensitivity["closure_error_m"])>5e-9:fail("SENSITIVITY_NUMERIC_CLOSURE_FAILURE")
    print("CRITICAL_VERTEX_SIGNED_SENSITIVITY_UM",{
        k:round(v*1e6,10) for k,v in sensitivity["vertex_contributions_m"].items()})
    print("DELTA_PROJECTION_UM",motion["projection_change_m"]*1e6)
    # Native checkMesh records are the authoritative pass/fail indicators.
    for t in (t0,t1):
        log=proc.parent/f"checkMesh-{t}.log"
        if not log.is_file() and label.startswith("97576"):
            log=proc.parent/f"checkMesh-r1-{t}.log"
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
    print("WARNING_TIMEPOINTS_DIFFER: cannot infer relative C2 vs 98512 response "
          "at t=0.563625 because C2 first step was not saved")
    print("CONCLUSIONS_ONLY_AFTER_CHECKING_NATIVE_PAIR_CROSSING_AND_CELL_SETS")
    print("READONLY_ANALYSIS_FINISHED_NO_OUTPUT_FILES_CHANGED_NO_SLURM_SUBMITTED")

if __name__=="__main__":
    try:main()
    except Exception as exc:
        print("AUDIT_FATAL",type(exc).__name__,str(exc),file=sys.stderr)
        raise
