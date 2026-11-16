#!/usr/bin/env python3
"""Read-only evidence audit for failed 91819 cross-Slurm ALE-FSI restart.

Examines OUR input preparation, serialized native restart files, frame policy,
and first fluid force decomposition. Never calls Slurm, solvers, or writes to
any FSI work directory. Run on HPCC login with system Python 3.9+.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import tempfile

FILES = ("U","p","phi","cellDisplacement","pointDisplacement","polyMesh/points")
SAVED_HISTORY_CANDIDATES=("meshPhi","phiMesh","oldPoints","V0","V00",
                          "polyMesh/oldPoints","polyMesh/points0")
RELATIVE = {
 "source91006":"fsi-long-stage0-job91006/runs/hpcc-implicit-002",
 "trial91767":"crossjob-fix-20261116/trials/trial-91767/runs/hpcc-implicit-002",
 "trial91819":"crossjob-fix-20261116/trials/trial-91819/runs/hpcc-implicit-002",
}

def hash_file(path):
    if not path.is_file():return None
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1<<20),b""):
            h.update(block)
    return h.hexdigest()

def numeric_times(processor):
    times=[]
    if not processor.is_dir():return []
    for d in processor.iterdir():
        if not d.is_dir():continue
        try:x=float(d.name)
        except ValueError:continue
        if math.isfinite(x):times.append((x,d.name))
    return sorted(times)

def history_overview(root):
    rows={}
    for rank in range(8):
        p=root/f"fluid/processor{rank}"
        times=numeric_times(p)
        earlier=[t for t,name in times if t<.0325-1e-9]
        nearest=max(earlier) if earlier else None
        snap=p/"0.0325"
        rows[str(rank)]={
          "times":[name for _,name in times],
          "nearest_previous_s":nearest,
          "previous_snapshot_gap_s":round(.0325-nearest,9) if nearest is not None else None,
          "previous_snapshot_steps_at_dt000125":(
             round((.0325-nearest)/.000125,6) if nearest is not None else None),
          "required_fields_present":{key:(snap/key).is_file() for key in FILES},
          "history_candidate_files_present":{key:(snap/key).is_file()
                                              for key in SAVED_HISTORY_CANDIDATES},
        }
    return rows

def cross_state(source,trial):
    result={}
    for tag,old,new in (
      ("structural_restart_rout_to_rin",
       source/"solid/seagrass.rout",trial/"solid/seagrass.rin"),
      ("persistent_structure_to_input",
       source/"solid/kinematic_state.bin",trial/"solid/kinematic_state.input.bin"),
      ("solid_mesh_reference",
       source/"restart_reference/Solid-Mesh.coords",
       trial/"restart_reference/Solid-Mesh.coords")):
        a,b=hash_file(old),hash_file(new)
        result[tag]={"old_present":a is not None,"new_present":b is not None,
                     "same_sha256":a==b if a and b else None,
                     "old_sha256":a,"new_sha256":b}
    return result

def compact_config(root):
    patterns={
      "controlDict":(
          "fluid/system/controlDict",
          [r"\bstartFrom\s+\w+\s*;",r"\bstartTime\s+[\d.eE+-]+\s*;",
           r"\bendTime\s+[\d.eE+-]+\s*;",r"\bdeltaT\s+[\d.eE+-]+\s*;",
           r"\bwriteControl\s+\w+\s*;",r"\bwriteInterval\s+\d+\s*;",
           r"\bpurgeWrite\s+\d+\s*;",
           r"\bcorrectPhi\s+\w+\s*;",
           r"\bmoveMeshOuterCorrectors\s+\w+\s*;"]),
      "fvSchemes":(
          "fluid/system/fvSchemes",
          [r"(?s)\bddtSchemes\s*\{[^}]*\}",
           r"(?s)\bdivSchemes\s*\{[^}]*\}"]),
      "fvSolution":(
          "fluid/system/fvSolution",
          [r"(?s)\bPIMPLE\s*\{[^}]*\}"]),
      "dynamicMeshDict":(
          "fluid/constant/dynamicMeshDict",
          [r"\bdynamicFvMesh\s+\w+\s*;",
           r"\bsolver\s+\w+\s*;",
           r"(?s)\bdiffusivity\s+[^;]*;"]),
      "preciceDict":(
          "fluid/system/preciceDict",
          [r"\brestartFromDeformed\s+(?:true|false)\s*;",
           r"\bnamePointDisplacement\s+\w+\s*;",
           r"\bnameCellDisplacement\s+\w+\s*;"]),
      "preciceXML":(
          "precice-config.xml",
          [r"<exchange[^>]*\bdata=\"(?:Force|Displacement)\"[^>]*/>",
           r"<max-time\s+value=\"[^\"]+\"",
           r"<time-windows-reused\s+value=\"[^\"]+\""]),
      "solidInp":(
          "solid/seagrass.inp",
          [r"(?m)^\s*\*RESTART\s*,\s*READ[^\n]*",
           r"(?m)^\s*\*RESTART\s*,\s*WRITE[^\n]*",
           r"(?m)^\s*\*DYNAMIC\s*,\s*DIRECT[^\n]*\n[^\n]*"])
    }
    result={}
    for key,(rel,terms) in patterns.items():
        path=root/rel
        if not path.is_file():
            result[key]={"exists":False};continue
        contents=path.read_text(errors="replace")
        result[key]={"exists":True,"sha256":hash_file(path),
                     "relevant_lines":[re.sub(r"\s+"," ",m.group(0)).strip()[:400]
                            for regex in terms for m in re.finditer(regex,contents,re.I)][:36]}
    return result

def first_force_block(root):
    log=root.parent.parent/"fluid.log"
    if not log.is_file():return {"exists":False}
    with log.open(errors="replace") as f:
        found=False; sample=[]; seen_time=None
        for line in f:
            m=re.match(r"\s*Time\s*=\s*([\d.eE+-]+)",line)
            if m:seen_time=m.group(1)
            if "forces bladeForces write:" in line:
                found=True
            if found:
                sample.append(line.rstrip("\n")[:280])
                if len(sample)>=22:break
    return {"exists":True,"first_block_time":seen_time,
            "first_force_log_lines":sample}

def watch_first(root):
    log=root/"solid/precice-Solid-watchintegral-Interface-Integral.log"
    if not log.is_file():return []
    data=[]
    with log.open(errors="replace") as f:
        for line in f:
            a=line.split()
            if len(a)<7:continue
            try:t,fx=float(a[0]),float(a[1])
            except ValueError:continue
            data.append({"relative_time_s":t,"Fx_N":fx})
            if len(data)>=3:break
    return data

def audit(base):
    source=base/RELATIVE["source91006"]
    if not source.is_dir():raise RuntimeError("Missing immutable 91006 source")
    cases={}
    for label,relative in RELATIVE.items():
        path=base/relative
        if not path.is_dir():raise RuntimeError(f"Missing case {label}: {path}")
        cases[label]={"history":history_overview(path),
                      "config":compact_config(path),
                      "first_force_block":first_force_block(path) if label!="source91006" else None,
                      "first_accepted_watch":watch_first(path)}
    cases["trial91767"]["solid_source_copy"]=cross_state(source,base/RELATIVE["trial91767"])
    cases["trial91819"]["solid_source_copy"]=cross_state(source,base/RELATIVE["trial91819"])
    return {"audit":"READ_ONLY_91819_RESTART_STATE_EVIDENCE",
      "cases":cases,
      "interpretation":{
        "missing_previous_native_step_is_not_proof_of_bug":
          "Inspect fvSchemes, actual time gaps, movePoints and flux behavior; directories are not in-memory state.",
        "file_history_not_equal_to_solver_time_memory":
          "Old mesh volume and mesh flux may be reconstructed, not stored as named checkpoint files.",
        "model_and_solver_sources_unmodified":True,
        "91543_not_read_or_modified":True,
      },
      "NO_WRITES_NO_SLURM_NO_SOLVER":True}

def self_test():
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp)/"fluid/processor0"
        (p/"0.03").mkdir(parents=True)
        (p/"0.0325").mkdir(parents=True)
        (p/"garbage").mkdir()
        assert numeric_times(p)==[(.03,"0.03"),(.0325,"0.0325")]
        f=Path(tmp)/"checkpoint"
        f.write_bytes(b"abc")
        assert hash_file(f)==hashlib.sha256(b"abc").hexdigest()
        assert not hash_file(Path(tmp)/"absent")
    print("READ_ONLY_91819_RESTART_EVIDENCE_SELFTEST_PASS")

def main():
    a=argparse.ArgumentParser()
    a.add_argument("--base",type=Path,default=Path.home()/"hpcc-fsi")
    a.add_argument("--self-test",action="store_true")
    opt=a.parse_args()
    if opt.self_test:return self_test()
    print(json.dumps(audit(opt.base.expanduser().resolve(strict=True)),indent=2,ensure_ascii=False))
    print("NO_SOURCE_NO_LIVE_JOB_NO_THIRD_PARTY_SOLVER_MODIFICATIONS")

if __name__=="__main__":main()
