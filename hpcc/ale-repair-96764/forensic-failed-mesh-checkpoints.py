#!/usr/bin/env python3
"""Read-only 96764 FSI failure forensics and intermediate checkpoint salvage audit.

No solver, no Slurm jobs, no cleanup, no checkpoint writes.
Reports facts required to design a NEW ALE repair, not another coefficient scan.
"""
from __future__ import annotations
from pathlib import Path
import json
import os
import re
import sys

SOURCE_T = 0.5635
FAILED_T = 0.580750

def finite_time(s: str):
    if not re.fullmatch(r"(?:0|[1-9]\d*)(?:\.\d+)?", s):
        return None
    try:
        return float(s)
    except ValueError:
        return None

def times(path: Path):
    if not path.is_dir():
        return {}
    d = {}
    for f in path.iterdir():
        if f.is_dir() and (t := finite_time(f.name)) is not None:
            d[t] = f
    return d

def checkpoint_candidates(fluid: Path):
    per = [times(fluid/f"processor{i}") for i in range(8)]
    if any(not x for x in per):
        return [],[len(x) for x in per]
    # floats are used only as directory selectors. Count exact normalized
    # values; no invented physical checkpoints or rounding.
    common = sorted(set.intersection(*(set(x) for x in per)))
    return common,[len(x) for x in per]

def checkpoint_file_coverage(fluid:Path, instant:float):
    fields = ("U","p","pointDisplacement","polyMesh/points")
    rows = []
    for i in range(8):
        d = times(fluid/f"processor{i}").get(instant)
        missing = [f for f in fields if d is None or not (d/f).is_file()]
        rows.append({"rank":i,"missing_expected_files":missing})
    return rows

def first_failure(f:Path):
    if not f.is_file():
        return {"status":"MISSING_LOG"}
    # Read binary-contaminated OpenFOAM stdout as escaped text, never OCR.
    data = f.read_bytes().replace(b"\x00",b" ")
    lines=data.decode("utf-8","replace").splitlines()
    pat=re.compile(r"SEAGRASS_MESH_GUARD\s+time=(\d+(?:\.\d+)?)\b.*concave=1")
    hits=[(i,pat.search(s)) for i,s in enumerate(lines)]
    hits=[(i,m) for i,m in hits if m]
    if not hits:
        return {"status":"NO_CONCAVITY_GUARD_FOUND",
                "other_native_fatal":sum("FOAM FATAL" in x for x in lines),
                "log_lines":len(lines)}
    i,m=hits[0]
    # Failing cell identity requires a native mesh-debug face/cell list.
    # A Boolean guard alone does not locate the cell.
    region=lines[max(0,i-90):min(len(lines),i+30)]
    interesting=[
        x[:320] for x in region if re.search(
            r"concav|cells?|faces?|non.?ortho|skew|volume|tet|rank|processor|"
            r"mesh.*fail|quality|SEAGRASS_MESH_GUARD",x,re.I)
    ]
    return {"status":"NATIVE_CONCAVITY_REJECTED",
            "first_concavity_time_s":float(m.group(1)),
            "offending_cell_id_in_log":"NOT_ESTABLISHED",
            "near_failure_geometry_lines":interesting[-22:],
            "last_log_lines":lines[-8:]}

def candidate(root:Path,job:int,k:int):
    w=root/f"trial-{job}-repair96764-c{k}-stage1"
    if not w.is_dir():
        return {"job":job,"candidate":k,"status":"NOT_CREATED"}
    fluid=w/"runs/hpcc-implicit-002/fluid"
    solid=w/"runs/hpcc-implicit-002/solid"
    common,counts=checkpoint_candidates(fluid)
    at=common[-1] if common else None
    record={
      "job":job,"candidate":k,"trial":str(w),
      "fluid_failure":first_failure(w/"fluid.log"),
      "per_rank_saved_time_directory_counts":counts,
      "last_common_fluid_saved_time_s":at,
      "last_common_fluid_time_is_accepted_FSI_checkpoint":"NOT_PROVEN",
      "solid_restart_files_present":{
       x:(solid/x).is_file() for x in ("seagrass.rout","kinematic_state.bin")
      },
      "native_result_written":(w/"FSI_SEGMENT_RESULT.json").is_file(),
      "accepted_native_segment_verdict":None,
    }
    if at is not None:
        record["latest_common_saved_time_file_coverage"]=checkpoint_file_coverage(fluid,at)
        record["saved_fluid_times_above_original_t0"]=[x for x in common if x>SOURCE_T][-8:]
    r=w/"FSI_SEGMENT_RESULT.json"
    if r.is_file():
        try:
            x=json.loads(r.read_text())
            record["accepted_native_segment_verdict"]=x.get("status")
            record["accepted_native_final_time_s"]=x.get("final_time_s")
        except (ValueError,OSError):
            record["accepted_native_segment_verdict"]="MALFORMED"
    return record

def main():
    uid=os.environ.get("USER")
    if not uid:
        raise SystemExit("USER_ENV_MISSING")
    base=Path("/data/icto")/uid/"seagrass-fsi558-runs.sNIpi9"
    rows=[candidate(base,j,k) for j in (97576,97854) for k in (1,2,3)]
    report={"type":"READONLY_ALE96764_NATIVE_FAILURE_AND_CHECKPOINT_AUDIT",
     "checked_trials":rows,
     "rules":[
       "A failed mesh guard prohibits accepting that step as a production checkpoint.",
       "A common fluid time folder alone does NOT prove coupling acceptance or synchronized CCX restart.",
       "Never reuse a candidate as a restart source without full force, displacement, mesh, eight-rank and CCX checks.",
       "Do not repeat failed fixed diffusivity scalars as a purported new ALE repair."
     ]}
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
