#!/usr/bin/env python3
"""STRICTLY READ ONLY: compare first failure of 98512 with earlier C2 runs.

Does not start Slurm, modify any file, change FSI state, or repair the mesh.
"""
from pathlib import Path
from collections import deque
import json
import os
import re

ROOT=Path("/data/icto")/os.environ["USER"]/"seagrass-fsi558-runs.sNIpi9"

TRIALS=[
 ("reference C2 job97576","trial-97576-repair96764-c2-stage1"),
 ("repeat C2 job97854","trial-97854-repair96764-c2-stage1"),
 ("bed2758 job98512","trial-98512-bed2758-s1"),
]

def forensics(label,dirname):
    trial=ROOT/dirname
    fluid=trial/"fluid.log"
    print("\n===== "+label+" =====")
    if not fluid.is_file():
        print("LOG_ABSENT",fluid)
        return
    count=0
    first=None
    last=None
    first_failed=None
    capture=0
    errors=0
    context=deque(maxlen=7)
    for line in fluid.open(errors="replace"):
        x=line.rstrip("\n")
        if "SEAGRASS_MESH_GUARD " in x:
            count+=1
            if first is None:first=x
            last=x
            if "concave=1" in x or "qualityFailed=1" in x or "tetFailed=1" in x:
                if first_failed is None:first_failed=x
        if capture>0:
            print("FATAL_CONTEXT",x[:350])
            capture-=1
        if ("FOAM FATAL ERROR" in x or
            ("Mesh" in x and "failed" in x.lower()) or
            "FOAM parallel run exiting" in x) and errors<2:
            errors+=1
            print("PRECEDING_FATAL_CONTEXT")
            for older in context:print("FATAL_CONTEXT",older[:350])
            print("FATAL_CONTEXT",x[:350])
            capture=12
        context.append(x)
    print("TOTAL_NATIVE_GUARDS",count)
    print("FIRST_GUARD",first)
    print("LAST_GUARD",last)
    print("FIRST_FAILED_GUARD",first_failed)
    state=trial/"STATE.json"
    if state.is_file():
        try:
            obj=json.loads(state.read_text())
            print("STATE",json.dumps({key:obj.get(key) for key in
                ("status","restart_from_time_s","final_time_s","failure")},ensure_ascii=False))
        except (OSError,ValueError) as e:print("STATE_NOT_PARSEABLE",str(e))
    proc=trial/"runs/hpcc-implicit-002/fluid/processor5"
    for t in ("0.5635","0.563625","0.5805","0.58075"):
        pts=proc/t/"polyMesh/points"
        print("RANK5_MESH_SNAPSHOT",t, "PRESENT" if pts.is_file() else "NOT_SAVED",pts)
    print("CHECKPOINT_NOT_PROVEN_BY_MESH_TIMES_ALONE")

def main():
    for label,dirname in TRIALS:
        forensics(label,dirname)
    print("\nREADONLY_AUDIT_COMPLETE_NO_NEW_JOB_NO_FILES_MODIFIED")
    print("IMPORTANT: The first concave flag does NOT identify the cell; do not assume it is cell2758.")
    print("IMPORTANT: sacct database unavailability is a separate scheduler accounting issue.")

if __name__=="__main__":
    main()
