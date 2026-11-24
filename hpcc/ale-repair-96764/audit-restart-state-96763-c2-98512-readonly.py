#!/usr/bin/env python3
"""Read-only eight-rank restart-state difference audit for proven first-step ALE failure.

Compares the same t=0.5635 snapshot in original accepted source, C2 (first
step mesh PASS) and failed bed+2x (first step mesh FAIL). Hashes exact
pointDisplacement, polyMesh/points, U/p/phi, points0 if present, and
motionReferenceDiffusivity. Prints ONLY mismatches and summary. Does not
infer physical equivalence from byte equivalence. NO writes or Slurm jobs.
"""
from pathlib import Path
import hashlib
import json
import os
import sys

REL={
  "initial_polyMesh_points":"0.5635/polyMesh/points",
  "initial_pointDisplacement":"0.5635/pointDisplacement",
  "initial_U":"0.5635/U",
  "initial_p":"0.5635/p",
  "initial_phi":"0.5635/phi",
  "reference_points0_polyMesh":"constant/polyMesh/points0",
  "reference_points0_time":"0.5635/polyMesh/points0",
  "reference_motion_diffusivity":"constant/motionReferenceDiffusivity",
  "constant_dynamicMeshDict":"constant/dynamicMeshDict",
  "constant_dynamicMeshDict_system":"system/dynamicMeshDict",
  "system_fvSchemes":"system/fvSchemes",
  "system_fvSolution":"system/fvSolution",
}
REQUIRED={"initial_polyMesh_points","initial_pointDisplacement","initial_U","initial_p","initial_phi","reference_motion_diffusivity"}

def digest(path):
    if not path.is_file():return None
    h=hashlib.sha256()
    with path.open("rb") as s:
        for b in iter(lambda:s.read(1<<20),b""):h.update(b)
    return h.hexdigest()

def main():
    user=os.environ.get("USER")
    if not user:raise RuntimeError("USER unset")
    base=Path("/data/icto")/user/"seagrass-fsi558-runs.sNIpi9"
    cases={
      "source_96763":base/"trial-96763/runs/hpcc-implicit-002/fluid",
      "C2_97576":base/"trial-97576-repair96764-c2-stage1/runs/hpcc-implicit-002/fluid",
      "bad_gain2_98512":base/"trial-98512-bed2758-s1/runs/hpcc-implicit-002/fluid",
    }
    for name,path in cases.items():
        if not path.is_dir():raise RuntimeError("MISSING_EXPECTED_CASE "+name+" "+str(path))
    counts={"same_all":0,"different":0,"missing":0}
    differing={}
    missing_required=[]
    for rank in range(8):
        loc={name:root/f"processor{rank}" for name,root in cases.items()}
        for key,rel in REL.items():
            hashes={}
            actual={}
            for name,root in loc.items():
                filepath=root/rel
                if not filepath.is_file() and rel.startswith("system/"):
                    filepath=cases[name]/rel
                if not filepath.is_file() and key.startswith("constant_dynamic"):
                    filepath=cases[name]/rel
                actual[name]=str(filepath) if filepath.is_file() else None
                hashes[name]=digest(filepath)
            nonmissing=[h for h in hashes.values() if h]
            if key in REQUIRED and len(nonmissing)!=len(hashes):
                missing_required.append((rank,key,actual))
            if len(nonmissing)!=3:
                counts["missing"]+=1
                # points0 may be either polyMesh/points0 or unavailable;
                # do not fail for these optional paths.
                if key in REQUIRED:
                    print("REQUIRED_MISSING",rank,key,actual)
                continue
            if len(set(nonmissing))==1:
                counts["same_all"]+=1
            else:
                counts["different"]+=1
                differing.setdefault(key,[]).append(rank)
                print("DIFFERENT",key,"rank",rank,
                      {name:h[:16] for name,h in hashes.items()})
    if missing_required:
        raise RuntimeError("REQUIRED_RESTART_SNAPSHOT_FILES_MISSING; RESULTS_INCOMPLETE")
    for crucial in ("initial_polyMesh_points","initial_pointDisplacement"):
        if crucial in differing:
            print("WARNING_RESTART_SOURCE_STATE_NOT_IDENTICAL",crucial,differing[crucial])
    print("HASH_AUDIT_SUMMARY",json.dumps({"counts":counts,"different_ranks_by_field":differing},sort_keys=True))
    print("NO_FSI_SUBMITTED; HASH_MATCH_IS_NOT_NATIVE_RESTART_VALIDATION")
    print("NO_FIELD_MESH_OR_CHECKPOINT_FILES_MODIFIED")

if __name__=="__main__":
    main()
