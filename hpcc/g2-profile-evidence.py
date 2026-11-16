#!/usr/bin/env python3
"""G2 evidence-only profiler: rank preCICE traces + solver accounting + SPOOLES counts.

Offline, Python stdlib, no Slurm, solver, mesh edits, or changes to old results.
This tool DOES NOT measure SPOOLES factorization wall-clock unless instrumented.
Never sum per-rank parallel wall times. Missing evidence is reported as missing,
not as zero activity.
"""
import argparse
import datetime
import importlib.util
import json
import math
from pathlib import Path
import re
import statistics
import sys

DEFAULT_CASES={
 "87186":"implicit-pilot-002-8mpi-timefix-87186/production/runs/hpcc-implicit-002",
 "89038":"performance-full160-job-89038/optimized-160/runs/hpcc-implicit-002",
 "89270":"performance-omp12-iqn15-job-89270/optimized-20/runs/hpcc-implicit-002",
}


def wallclock(raw):
    # GNU time -v emits either h:mm:ss or m:ss and may include fraction.
    pieces=raw.strip().split(":")
    if len(pieces) not in (2,3):
        return None
    try:ints=[float(i) for i in pieces]
    except ValueError:return None
    if any(not math.isfinite(i) or i<0 for i in ints):
        return None
    return sum(v*60**i for i,v in enumerate(reversed(ints)))


def time_accounting(path):
    if not path.is_file():
        return {"status":"MISSING"}
    content=path.read_text(errors="replace")
    def last(pattern,kind=float):
        matches=re.findall(pattern,content,flags=re.M)
        if not matches:return None
        try:return kind(matches[-1])
        except (TypeError,ValueError):return None
    raw=last(r"^\s*Elapsed \(wall clock\) time \(h:mm:ss or m:ss\):\s*(\S+)",str)
    return {
        "status":"PRESENT",
        "gnu_elapsed_seconds":wallclock(raw) if raw else None,
        "gnu_user_cpu_seconds":last(r"^\s*User time \(seconds\):\s*(\S+)"),
        "gnu_system_cpu_seconds":last(r"^\s*System time \(seconds\):\s*(\S+)"),
        "gnu_max_resident_kb":last(r"^\s*Maximum resident set size \(kbytes\):\s*(\S+)",int),
        "gnu_exit_status":last(r"^\s*Exit status:\s*(\d+)",int),
    }


def solid_cost_evidence(path):
    if not path.is_file():return {"status":"MISSING"}
    count=0
    marker=0
    errors=[]
    first_last=None
    for l in path.open(errors="replace"):
        if "Factoring the system of equations using the symmetric spooles solver" in l:
            count+=1
        if re.search(r"Using up to \d+ cpu\(s\) for spooles",l):
            marker+=1
        if re.search(r"\*ERROR|Segmentation fault",l,re.I):
            errors.append(l.strip()[:200])
    return {
        "status":"PRESENT",
        "symmetric_spooles_factorization_log_lines":count,
        "spooles_cpu_limit_log_lines":marker,
        "possible_fatal_lines":errors[:10],
        "factorization_wall_seconds":"UNMEASURED_BY_EXISTING_TEXT_LOG",
        "reason":"SPOOLES factorization messages have no paired wall-clock timestamps; counts are not durations",
    }


def trace_evidence(case,analyzer):
    files=sorted(case.glob("*/precice-profiling/*.txt"))
    if not files:
        return {"status":"NO_RANK_PROFILE_TXT","rank_count":0,
                "note":"No rank profile data available; cannot infer numerical solver share"}
    spec=importlib.util.spec_from_file_location("existing_precice_profiler",analyzer)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result={}
    for f in files:
        meta,totals=module.parse(f)
        name=str(meta["name"])
        rank=int(meta["rank"])
        key=f"{name}:{rank}"
        if key in result:raise RuntimeError(f"Duplicate participant/rank in profile: {key}")
        global_us=totals.get("_GLOBAL",[0,0,0])[1]
        selection=sorted(totals.items(),key=lambda x:x[1][2],reverse=True)[:30]
        result[key]={
            "participant":name,"rank":rank,"size":int(meta["size"]),
            "mode":str(meta["mode"]),"global_wall_seconds":global_us/1e6,
            "top_exclusive_events":[
                {"name":label,"calls":data[0],
                 "inclusive_seconds":data[1]/1e6,"exclusive_seconds":data[2]/1e6}
                for label,data in selection],
            "solver_advance_candidates":[
                {"name":label,"calls":data[0],
                 "inclusive_seconds":data[1]/1e6,"exclusive_seconds":data[2]/1e6}
                for label,data in totals.items()
                if any(tok in label.lower()
                       for tok in ("advance","wait","accelerat","map","m2n","communicat"))
            ][:60],
        }
    # Pick maximum across rank global times, never sum wall times across ranks.
    per_participant={}
    for participant in sorted({v["participant"] for v in result.values()}):
        entries=[r for r in result.values() if r["participant"]==participant]
        per_participant[participant]={
            "ranks":len(entries),
            "global_min_seconds":min(r["global_wall_seconds"] for r in entries),
            "global_median_seconds":statistics.median(r["global_wall_seconds"] for r in entries),
            "global_max_seconds":max(r["global_wall_seconds"] for r in entries),
        }
    return {"status":"PARSED","rank_count":len(result),
            "participant_summaries":per_participant,"rank_detail":result,
            "warning":"Trace inclusive values nest and overlap; solver periods may include blocking, so they do not directly measure SPOOLES."}


def inspect(base,analyzer):
    results={}
    for name,rel in DEFAULT_CASES.items():
        root=base/rel
        results[name]={
            "source":str(root),
            "exists":root.is_dir(),
            "solid_process_accounting":time_accounting(root/"solid.log"),
            "fluid_process_accounting":time_accounting(root/"fluid.log"),
            "spooles":solid_cost_evidence(root/"solid.log"),
            "precice":trace_evidence(root,analyzer) if root.is_dir()
                else {"status":"CASE_ABSENT"},
        }
    return {
        "schema":"g2-profiler-evidence-v1",
        "created_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "mode":"READ_ONLY_OFFLINE",
        "jobs":results,
        "interpretation_rules":[
            "Concurrent fluid and solid wall durations must never be added.",
            "GNU time user CPU seconds are summed CPU core seconds, not wall seconds.",
            "SPOOLES factorization counts do NOT measure solver wall time.",
            "preCICE trace nested inclusive duration may overlap; exclusive is within one rank only.",
            "A bottleneck selection requires actual solver timing, not an assertion based on message count.",
            "Do not recommend a new thread scan based solely on this report.",
        ],
        "g2_actual_factorization_fraction_of_wall":
            "UNMEASURED_UNTIL_TIMED_SOLVER_PROFILING",
        "g2_new_solver_speedup_verified":False,
        "g1_running_job_90873_unmodified":True,
    }


def self_test():
    assert wallclock("0:12.45")==12.45
    assert wallclock("1:01:05")==3665.
    assert wallclock("bad") is None
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)/"solid.log"
        p.write_text("Factoring the system of equations using the symmetric spooles solver\n"
                     "Using up to 4 cpu(s) for spooles.\n"
                     "\tUser time (seconds): 20.01\n"
                     "\tSystem time (seconds): 0.10\n"
                     "\tElapsed (wall clock) time (h:mm:ss or m:ss): 0:08.02\n"
                     "\tMaximum resident set size (kbytes): 10012\n"
                     "\tExit status: 0\n")
        q=solid_cost_evidence(p)
        assert q["symmetric_spooles_factorization_log_lines"]==1
        assert q["factorization_wall_seconds"]=="UNMEASURED_BY_EXISTING_TEXT_LOG"
        z=time_accounting(p)
        assert z["gnu_elapsed_seconds"]==8.02
        assert z["gnu_user_cpu_seconds"]==20.01
        assert z["gnu_exit_status"]==0
    print("G2_PROFILE_EVIDENCE_STATIC_SELF_TEST_PASS")


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base",type=Path,default=Path.home()/"hpcc-fsi")
    ap.add_argument("--out",type=Path)
    ap.add_argument("--self-test",action="store_true")
    args=ap.parse_args()
    if args.self_test:
        self_test();return
    base=args.base.expanduser().resolve(strict=True)
    helper=base/"analyze-precice-trace.py"
    if not helper.is_file():
        raise SystemExit(f"Missing existing trace parser {helper}: download unchanged repository script")
    report=inspect(base,helper)
    for job,data in report["jobs"].items():
        print(f"JOB={job} PROFILE={data['precice']['status']} "
              f"SPOOLES_FACTOR_MESSAGES={data['spooles'].get('symmetric_spooles_factorization_log_lines')}")
        print("  SOLID_TIME_ACCOUNTING",json.dumps(data["solid_process_accounting"],ensure_ascii=False))
        print("  FLUID_TIME_ACCOUNTING",json.dumps(data["fluid_process_accounting"],ensure_ascii=False))
        if data["precice"]["status"]=="PARSED":
            print("  PROFILE_RANKS",data["precice"]["rank_count"])
            print("  PROFILE_PARALLEL_RANK_GLOBALS",
                  json.dumps(data["precice"]["participant_summaries"],ensure_ascii=False))
    print("G2_FACTOR_WALL_SHARE=NOT_YET_MEASURED")
    print("G2_SOLVER_SPEEDUP=UNVERIFIED")
    if args.out:
        dest=args.out.expanduser().resolve()
        if dest.suffix.lower()!=".json":
            raise SystemExit("Output must use .json extension")
        if any(dest.is_relative_to(base/rel) or (base/rel).is_relative_to(dest)
               for rel in DEFAULT_CASES.values()):
            raise SystemExit("Refusing output under old case")
        if dest.exists():raise SystemExit("Refusing to overwrite existing report")
        dest.parent.mkdir(parents=True,exist_ok=True)
        with dest.open("x") as out:
            json.dump(report,out,ensure_ascii=False,indent=2)
            out.write("\n")
        print("G2_PROFILE_REPORT",dest)


if __name__=="__main__":
    main()
