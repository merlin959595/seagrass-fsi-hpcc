#!/usr/bin/env python3
"""Parallel G1-B failure + G2 preCICE critical-event triage, read-only.

Never launches Slurm/solver, changes case data, or claims a successful restart
or measured SPOOLES factorization duration. Only extracts bounded evidence.
"""
import argparse
import json
import math
from pathlib import Path
import re

LOG_NAMES=(
 "logs/fsi-g1-b10-90873.out",
 "logs/fsi-g1-b10-90873.err",
 "g1-b10-job-90873/fluid.log",
 "g1-b10-job-90873/solid.log",
)
FATAL=re.compile(r"Traceback|Error|ERROR|FATAL|not found|failed|restart|Cannot|"
                 r"Segmentation fault|exception|timeout|could not|No such file",
                 re.I)

def read_json(p):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError,ValueError,UnicodeError):
        return None

def bounded_tail(path,cap_bytes=524288,lines=28):
    if not path.is_file():
        return ["FILE_ABSENT"]
    with path.open("rb") as f:
        f.seek(0,2)
        size=f.tell()
        f.seek(max(0,size-cap_bytes))
        block=f.read().decode("utf-8","replace")
    lines_in=block.splitlines()
    if size>cap_bytes:
        lines_in=lines_in[1:]
    matched=[(i,l) for i,l in enumerate(lines_in) if FATAL.search(l)]
    anchors={i for idx,_ in matched[-12:] for i in range(max(0,idx-1),min(len(lines_in),idx+2))}
    selected=[lines_in[i][:300] for i in sorted(anchors)]
    selected+=["---LOG LAST 16 LINES---"]
    selected.extend(l[:300] for l in lines_in[-16:])
    return selected[-lines*3:]

def top_rank_events(report,job,rank,n):
    job_info=(report.get("jobs") or {}).get(job,{})
    profile=job_info.get("precice") or {}
    if profile.get("status")!="PARSED":
        return profile.get("status","NO_PROFILE")
    item=(profile.get("rank_detail") or {}).get(rank)
    if not isinstance(item,dict):
        return f"Rank {rank} unavailable"
    entries=item.get("top_exclusive_events") or []
    return [{
        "event":record.get("name"),
        "calls":record.get("calls"),
        "exclusive_s":round(record.get("exclusive_seconds",0),3),
        "inclusive_s":round(record.get("inclusive_seconds",0),3),
    } for record in entries[:n]]

def self_test():
    assert FATAL.search("FOAM FATAL ERROR")
    assert FATAL.search("No such file")
    assert not FATAL.search("coupling converged")
    sample={"jobs":{"89038":{"precice":{"status":"PARSED","rank_detail":{
        "Fluid:0":{"top_exclusive_events":[{"name":"foo","calls":1,
        "exclusive_seconds":7.125,"inclusive_seconds":7.125}]}}}}}}
    assert top_rank_events(sample,"89038","Fluid:0",5)[0]["exclusive_s"]==7.125
    print("G1B_G2_PARALLEL_TRIAGE_STATIC_SELF_TEST_PASS")

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base",type=Path,default=Path.home()/"hpcc-fsi")
    p.add_argument("--profile",type=Path)
    p.add_argument("--self-test",action="store_true")
    args=p.parse_args()
    if args.self_test:
        self_test()
        return
    base=args.base.expanduser().resolve(strict=True)
    state=read_json(base/"g1-b10-job-90873/STATE.json")
    manifest=read_json(base/"g1-b10-job-90873/G1_B_RESULT.json")
    stage=read_json(base/"g1-b10-job-90873/G1_B_STAGE_EVIDENCE.json")
    print("===== G1B 90873 =====")
    if not state:
        print("STATUS: STATE.json missing: inspect Slurm logs below")
    else:
        print("STATE:",json.dumps({k:state.get(k) for k in (
            "status","failure","resume_from_time_s","target_time_s",
            "participant_exit_codes","wall_s","restart_verified","participants"
        )},ensure_ascii=False))
    print("STAGING:",stage.get("status") if stage else "MISSING")
    print("FINAL_ACCEPTANCE:",manifest.get("status") if manifest else "ABSENT")
    root=base/"g1-b10-job-90873/runs/hpcc-implicit-002"
    for label,path in (
        ("NEW_SOLID_RIN",root/"solid/seagrass.rin"),
        ("NEW_SOLID_ROUT",root/"solid/seagrass.rout"),
        ("NEW_SOLID_PERSISTENT_STATE",root/"solid/kinematic_state.bin"),
        ("NEW_SOLID_PREVIOUS_STATE_INPUT",root/"solid/kinematic_state.input.bin"),
        ("FLUID_P0_T00125",root/"fluid/processor0/0.00125/U"),
        ("FLUID_P0_T0025",root/"fluid/processor0/0.0025/U")):
        print(label,"PRESENT",path.stat().st_size if path.is_file() else "ABSENT")
    for rel in LOG_NAMES:
        print("\n===== FILE",rel,"=====")
        for line in bounded_tail(base/rel):
            print(line)
    print("\n===== G2 PRECISE EVENT RANKINGS =====")
    pf=args.profile
    if not pf:
        options=sorted(base.glob("g2-profile-*.json"))
        pf=options[-1] if options else None
    report=read_json(pf) if pf else None
    if report:
        print("PROFILE:",pf)
        for job in ("89038","87186"):
            for rank in ("Solid:0","Fluid:0"):
                print(job,rank)
                events=top_rank_events(report,job,rank,12)
                if isinstance(events,str):
                    print(events)
                else:
                    for event in events:
                        print("  EXCLUSIVE_S",event["exclusive_s"],
                              "CALLS",event["calls"],"EVENT",event["event"])
        print("G2_SPOOLES_FACTORIZATION_WALL_FRACTION=UNMEASURED")
    else:
        print("G2_PROFILE_JSON_NOT_AVAILABLE")
    print("READ_ONLY_NO_SLURM_NO_MUTATION")

if __name__=="__main__":
    main()
