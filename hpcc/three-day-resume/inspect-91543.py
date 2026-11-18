#!/usr/bin/env python3
"""Read-only truth audit of uninterrupted 3-day FSI Slurm job 91543.

Never infer endpoint from the final watch line. Cross-check 8 OpenFOAM MPI
checkpoint times and files against accepted preCICE time and CalculiX state.
No filesystem writes or sbatch; never modify the source. Emit evidence and
explicitly separate known checkpoint time from admissible restart.
"""
import argparse
import json
import math
from pathlib import Path
import re
import subprocess

WATCH="precice-Solid-watchintegral-Interface-Integral.log"
DT=.000125
ORIGIN=.0025

def q(path):
    try:return json.loads(path.read_text())
    except (OSError,ValueError):return None

def numeric_time_dirs(path):
    if not path.is_dir():return []
    result=[]
    for p in path.iterdir():
        if p.is_dir():
            try:
                x=float(p.name)
                if math.isfinite(x):result.append((x,p))
            except ValueError:pass
    return sorted(result)

def accepted_last(path):
    if not path.is_file():return (None,None,0)
    last=None;prev=None;count=0
    with path.open(errors="replace") as f:
        for line in f:
            p=line.split()
            if len(p)<7:continue
            try:
                vals=list(map(float,p[:7]))
            except ValueError:continue
            if not all(math.isfinite(x) for x in vals):continue
            prev=last;last=vals;count+=1
    return (prev,last,count)

def inspect(base):
    root=base/"three-day-proven/long-job-91543"
    source=root/"runs/hpcc-implicit-002"
    if not source.is_dir():raise RuntimeError(f"MISSING_91543_CASE: {source}")
    ranks={}
    for rank in range(8):
        processor=source/f"fluid/processor{rank}"
        times=numeric_time_dirs(processor)
        valid=[]
        for t,p in times:
            if all((p/field).is_file() for field in
                   ("U","p","phi","pointDisplacement","polyMesh/points","uniform/time")):
                valid.append(t)
        ranks[str(rank)]={"latest_numeric_time_s":times[-1][0] if times else None,
                         "latest_complete_time_s":valid[-1] if valid else None,
                         "complete_time_directories":len(valid)}
    latest=[r["latest_complete_time_s"] for r in ranks.values()]
    same=(all(t is not None for t in latest) and max(latest)-min(latest)<1e-9)
    t=latest[0] if same else None
    previous,last,num=accepted_last(source/"solid"/WATCH)
    rel=last[0] if last else None
    last_physical=rel+ORIGIN if rel is not None else None
    time_aligned=(t is not None and last_physical is not None
                  and abs(t-last_physical)<1e-9)
    solid=source/"solid"
    deck=solid/"seagrass.inp"
    deck_data=deck.read_text() if deck.is_file() else ""
    restart=re.search(r"(?im)^\s*\*RESTART\s*,\s*READ\s*,\s*STEP=(\d+)",deck_data)
    step=int(restart.group(1)) if restart else None
    fluid_dict=source/"fluid/system/preciceDict"
    foam=fluid_dict.read_text() if fluid_dict.is_file() else ""
    xmlpath=source/"precice-config.xml"
    xml=xmlpath.read_text() if xmlpath.is_file() else ""
    yaml=solid/"config.yml"
    solid_yaml=yaml.read_text() if yaml.is_file() else ""
    structural={
        "restart_step_read_in_original_inp":step,
        "next_read_step_if_end_matches_structural_state":step+1 if step is not None else None,
        "rout_exists":(solid/"seagrass.rout").is_file(),
        "persistent_kinematic_state_exists":(solid/"kinematic_state.bin").is_file(),
        "original_reference_coords_exists":(source/"restart_reference/Solid-Mesh.coords").is_file()
    }
    protocol={
        "fluid_absolute_Displacement":bool(re.search(r"readData\s*\(\s*Displacement\s*\)",foam)),
        "fluid_restartFromDeformed_true":"restartFromDeformed true;" in foam,
        "solid_absolute_Displacement":"Displacement" in solid_yaml,
        "xml_absolute_Displacement":'name="Displacement"' in xml,
        "xml_implicit_coupling":"coupling-scheme:parallel-implicit" in xml,
    }
    original_state=q(root/"STATE.json")
    original_native=q(root/"FSI_SEGMENT_RESULT.json")
    original_stage=q(root/"FSI_SEGMENT_STAGE.json")
    out={
      "job":91543,"root":str(root),
      "status_from_original_state":original_state,
      "original_native_status":original_native.get("status") if original_native else None,
      "original_stage":original_stage,
      "complete_fluid_MPI_time_aligned":same,
      "last_complete_MPI_fluid_time_s":t,
      "fluid_ranks":ranks,
      "accepted_watch_rows":num,
      "last_accepted_relative_time_s":rel,
      "last_accepted_physical_time_s_from_origin_0p0025":last_physical,
      "checkpoint_time_matches_latest_accepted_watch":time_aligned,
      "last_accepted_Fx_N":last[1] if last else None,
      "original_structural_restart_state":structural,
      "original_protocol":protocol,
      "possible_full_backup":True,
      "safe_to_start_new_coupled_continuation_without_further_validation":False,
      "explanation":"Fluid/solid synchronization and structural restart binary step cannot be proven by file presence alone; require immutable backup and native end-state or independent restart certification."
    }
    print(json.dumps(out,indent=2,ensure_ascii=False))
    return out

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--base",type=Path,default=Path.home()/"hpcc-fsi")
    args=p.parse_args()
    inspect(args.base.expanduser().resolve(strict=True))

if __name__=="__main__":
    main()
