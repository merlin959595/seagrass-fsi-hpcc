#!/usr/bin/env python3
"""STRICT READ ONLY: ALE diffusivity ramp library and cellDisplacement restart evidence.

After actual C2 vs 98512 first-step geometry + SHA comparisons.
Makes no filesystem changes and submits no Slurm jobs. Does not import or
execute the .so. Does not assume custom 6 coefficient parameters' meanings.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess

def sha(path):
    if not path.is_file():return None
    h=hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda:stream.read(1<<20),b""):h.update(block)
    return h.hexdigest()

def status(paths):
    d={k:sha(v) for k,v in paths.items()}
    present={k:v for k,v in d.items() if v is not None}
    state="ALL_IDENTICAL" if len(present)==len(d) and len(set(present.values()))==1 else (
      "SOME_FILES_ABSENT" if len(present)!=len(d) else "DIFFERENT")
    return state,{k:(v[:20] if v else "ABSENT") for k,v in d.items()}

def main():
    user=os.environ.get("USER")
    if not user:raise RuntimeError("USER_ENV_MISSING")
    root=Path("/data/icto")/user/"seagrass-fsi558-runs.sNIpi9"
    home=Path.home()
    workspace=home/"hpcc-fsi/three-day-resume-20261119/.mesh-repair558-data.29CSy1"
    lib=workspace/"lib/libseagrass558RampDiffusivity.so"
    source={
      "source96763":root/"trial-96763/runs/hpcc-implicit-002/fluid",
      "C2_97576":root/"trial-97576-repair96764-c2-stage1/runs/hpcc-implicit-002/fluid",
      "bad98512":root/"trial-98512-bed2758-s1/runs/hpcc-implicit-002/fluid",
    }
    for k,p in source.items():
        if not p.is_dir():raise RuntimeError("REQUIRED_CASE_MISSING "+k+" "+str(p))
    print("========== CUSTOM_LIBRARY_EVIDENCE ==========")
    print("PATH",lib)
    print("SHA256",sha(lib) or "ABSENT")
    print("WARNING_CUSTOM_LIBRARY_BINARY_IS_NOT_SOURCE_CODE_AND_SYMBOL_NAMES_DO_NOT_PROVE_SEMANTICS")
    for utility,args in (
        ("nm",["nm","-DC",str(lib)]),
        ("strings",["strings","-a",str(lib)]),
    ):
        if not lib.is_file() or not shutil.which(utility):
            print("BINARY_SYMBOL_AUDIT_UNAVAILABLE",utility)
            continue
        try:
            run=subprocess.run(args,capture_output=True,text=True,timeout=18,check=False,errors="replace")
            lines=run.stdout.splitlines()
            matches=[line.strip()[:260] for line in lines
              if re.search(r"seagrass|RampFile|motionReference|diffusivity|readScalar|lookUp|lookup",
                           line,re.I)]
            print("BINARY_LIBRARY_SCAN",utility,"exit",run.returncode,"matches",len(matches))
            for line in matches[:45]:print("LIBRARY_MATCH",line)
        except (OSError,subprocess.TimeoutExpired) as exc:
            print("BINARY_LIBRARY_SCAN_UNAVAILABLE",utility,str(exc))
    print("========== RAMP_CONFIG_MATCHED_TO_ALL_THREE_CASES ==========")
    for name,case in source.items():
        cfg=case/"constant/dynamicMeshDict"
        if cfg.is_file():
            data=cfg.read_text(errors="replace")
            m=re.search(r"diffusivity\s+seagrass558RampFile\s+([^;]+);",data,re.S)
            print("CONFIG",name,"sha256",sha(cfg),"parameters",m.group(1).split() if m else "NO_CUSTOM_MODEL_PATTERN")
        else:
            print("CONFIG_MISSING",name)
    print("NOTE_0P5535_AND_0P5565_ARE_BEFORE_0P5635_BUT_THEIR_MEANING_IS_UNPROVEN_WITHOUT_CUSTOM_CPP_SOURCE")
    print("========== ALL_RANKS_INITIAL_MOTION_FIELDS ==========")
    rels={
      "cellDisplacement_0p5635":"0.5635/cellDisplacement",
      "pointDisplacement_0p5635":"0.5635/pointDisplacement",
      "points_0p5635":"0.5635/polyMesh/points",
      "pointLocation_0p5635":"0.5635/pointLocation",
      "points0_constant":"constant/polyMesh/points0",
      "points0_0p5635":"0.5635/polyMesh/points0",
      "referenceDiffusivity_constant":"constant/motionReferenceDiffusivity",
      "cellDisplacement_0":"0/cellDisplacement",
      "pointDisplacement_0":"0/pointDisplacement",
      "points0_0":"0/polyMesh/points0",
    }
    out={}
    for key,rel in rels.items():
        stats={}
        for rank in range(8):
            roots={name:path/f"processor{rank}"/rel for name,path in source.items()}
            state,hashes=status(roots)
            stats.setdefault(state,[]).append(rank)
            if state=="DIFFERENT":
                print("FIELD_DIFFERENCE",key,"rank",rank,hashes)
        print("INITIAL_ALE_FIELD",key,stats)
        out[key]=stats
    print("IMPORTANT_ABSENT_POINTS0_OR_CELLDISPLACEMENT_ON_DISK_DOES_NOT_PROVE_RUNTIME_MESH_REFERENCE_WAS_MISSING")
    print("IMPORTANT_IDENTICAL_ON_DISK_FIELDS_DO_NOT_PROVE_IDENTICAL_SOLVER_IN_MEMORY_STATE")
    print("IMPORTANT_SAME_FIRST_TIME_MESH_DIFFERENT_AFTER_DIFFUSIVITY_CHANGE_SUPPORTS_ALE_REEQUILIBRATION_HYPOTHESIS_NOT_PROOF")
    print("AUDIT_DONE_READONLY_NO_SLURM_NO_FSI_NO_FILES_MODIFIED")

if __name__=="__main__":
    main()
