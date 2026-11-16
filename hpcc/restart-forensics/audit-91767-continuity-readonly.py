#!/usr/bin/env python3
"""Read-only differential audit of the 91767 cross-job result and 91543 control.

No solver calls, Slurm submissions, deletion, state edits, or live-job writes.
Focus on provisional vs accepted force, ALE/CFD state retention, and shell log.
"""
import argparse
import hashlib
import json
import math
import re
from pathlib import Path

def watch(path):
    if not path.is_file():
        return []
    result = []
    for line in path.read_text(errors="replace").splitlines():
        words = line.split()
        if len(words) < 2:
            continue
        try:
            t, fx = float(words[0]), float(words[1])
        except ValueError:
            continue
        if math.isfinite(t) and math.isfinite(fx):
            result.append((t, fx))
    return result

def matching(rows, t):
    return [fx for time,fx in rows if abs(time-t) < 1e-8]

def forces(log):
    markers = list(re.finditer(r"(?m)^\s*forces bladeForces write:", log))
    timepat = re.compile(r"(?m)^\s*Time\s*=\s*([+\-\d.eE]+)\s*$")
    vpat = re.compile(r"\bTotal\s*:\s*\(([+\-\d.eE]+)\s+([+\-\d.eE]+)\s+([+\-\d.eE]+)\)")
    # Linear scan, not O(n^2) rescanning of prefixes of the live 91543 log.
    times=[(m.start(),float(m.group(1))) for m in timepat.finditer(log)]
    found=[]
    tindex=0
    lasttime=None
    for i, marker in enumerate(markers):
        while tindex<len(times) and times[tindex][0]<marker.start():
            lasttime=times[tindex][1]
            tindex+=1
        end=markers[i+1].start() if i+1<len(markers) else len(log)
        block=log[marker.end():end]
        force=vpat.search(block)
        if not force:
            continue
        found.append({"physical_time_s":lasttime,
                      "Fx_N":float(force.group(1)),
                      "Fy_N":float(force.group(2)),
                      "Fz_N":float(force.group(3))})
    return found

def files_at_time(fluid, timestamp):
    result={}
    for rank in range(8):
        folder=fluid/f"processor{rank}"
        times=[]
        if folder.is_dir():
            for sub in folder.iterdir():
                if sub.is_dir():
                    try: times.append(float(sub.name))
                    except ValueError: pass
        result[str(rank)]={"numeric_time_dirs":len(times),
                           "target_exists":(folder/timestamp).is_dir()}
    return result

def hash_file(path):
    if not path.is_file():
        return None
    dig=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1<<20),b""):
            dig.update(b)
    return dig.hexdigest()

def field_check(source,trial):
    fields=("U","p","phi","cellDisplacement","pointDisplacement","polyMesh/points")
    rows={}
    for name in fields:
        count_src=0
        count_trial=0
        equal=0
        for i in range(8):
            orig=source/f"fluid/processor{i}/0.0325/{name}"
            new=trial/f"fluid/processor{i}/0.0325/{name}"
            a=hash_file(orig)
            b=hash_file(new)
            count_src+=a is not None
            count_trial+=b is not None
            equal+=a is not None and b is not None and a==b
        rows[name]={"source_ranks":count_src,"trial_ranks":count_trial,
                    "byte_identical_ranks":equal}
    return rows

def bounded_early_log(path, stop_time=.033, max_lines=180000):
    """Read only beginning of long-run log through the comparison time."""
    if not path.is_file():return ""
    time_rx=re.compile(r"^\s*Time\s*=\s*([+\-\d.eE]+)\s*$")
    lines=[]
    with path.open(errors="replace") as f:
        for n,line in enumerate(f):
            if n>=max_lines:break
            m=time_rx.match(line)
            if m and float(m.group(1))>stop_time:break
            lines.append(line)
    return "".join(lines)

def status_report(base):
    source=base/"fsi-long-stage0-job91006/runs/hpcc-implicit-002"
    trial=base/"crossjob-fix-20261116/trials/trial-91767/runs/hpcc-implicit-002"
    live=base/"three-day-proven/long-job-91543/runs/hpcc-implicit-002"
    root=trial.parents[1] # .../trials/trial-91767
    if not source.is_dir() or not trial.is_dir():
        raise RuntimeError("Missing original 91006 or isolated trial 91767; refusing to infer absent data")
    original=watch(source/"solid/precice-Solid-watchintegral-Interface-Integral.log")
    trialw=watch(trial/"solid/precice-Solid-watchintegral-Interface-Integral.log")
    livew=watch(live/"solid/precice-Solid-watchintegral-Interface-Integral.log")
    fl=(root/"fluid.log").read_text(errors="replace") if (root/"fluid.log").is_file() else ""
    force=forces(fl)
    live_fluid=bounded_early_log(live.parents[1]/"fluid.log")
    control_fluid_forces=forces(live_fluid)
    t_abs=.032625
    control_raw=[x["Fx_N"] for x in control_fluid_forces
                 if x["physical_time_s"] is not None and
                    abs(x["physical_time_s"]-t_abs)<1e-8]
    trial_raw=[x["Fx_N"] for x in force
               if x["physical_time_s"] is not None and
                  abs(x["physical_time_s"]-t_abs)<1e-8]
    reference=matching(original,.03)
    init=matching(trialw,0.)
    first_accepted=matching(trialw,.000125)
    second_accepted=matching(trialw,.00025)
    control_first=matching(livew,.030125)
    control_second=matching(livew,.03025)
    target=reference[-1] if reference else None
    rel=lambda a,b: abs(a-b)/abs(b) if a is not None and b not in (None,0) else None
    rawstate=root/"FSI_SEGMENT_RESULT.json"
    state=json.loads(rawstate.read_text()) if rawstate.is_file() else None
    report={
      "audit":"READ_ONLY_CROSS_JOB_91767",
      "live_91543_unmodified":True,
      "source_91006_time_s":.0325,
      "original_Fx_N":target,
      "trial_initial_Fx_N":init[0] if init else None,
      "trial_first_accepted_Fx_N":first_accepted[-1] if first_accepted else None,
      "trial_second_accepted_Fx_N":second_accepted[-1] if second_accepted else None,
      "live_91543_first_Fx_N":control_first[-1] if control_first else None,
      "live_91543_second_Fx_N":control_second[-1] if control_second else None,
      "first_computed_Fx_N":force[0]["Fx_N"] if force else None,
      "first_computed_relative_error_to_source":rel(force[0]["Fx_N"] if force else None,target),
      "first_accepted_rel_error_to_control":
          rel(first_accepted[-1],control_first[-1]) if first_accepted and control_first else None,
      "second_accepted_rel_error_to_control":
          rel(second_accepted[-1],control_second[-1]) if second_accepted and control_second else None,
      "continuous_91543_raw_Fx_at_0032625_first_N":
          control_raw[0] if control_raw else None,
      "continuous_91543_raw_Fx_at_0032625_last_N":
          control_raw[-1] if control_raw else None,
      "trial_91767_raw_Fx_at_0032625_first_N":
          trial_raw[0] if trial_raw else None,
      "trial_first_raw_vs_continuous_first_relative_error":
          rel(trial_raw[0],control_raw[0]) if trial_raw and control_raw else None,
      "trial_first_raw_vs_continuous_last_relative_error":
          rel(trial_raw[0],control_raw[-1]) if trial_raw and control_raw else None,
      "forces_first_6":force[:6],
      "forces_last_6":force[-6:],
      "forces_record_count":len(force),
      "trial_watch_near_first": [(t,fx) for t,fx in trialw if -1e-9<=t<=.00025001][:40],
      "state_field_byte_equality":field_check(source,trial),
      "original_times_per_rank":files_at_time(source/"fluid","0.0325"),
      "trial_times_per_rank":files_at_time(trial/"fluid","0.0325"),
      "numeric_trial_status":state.get("status") if state else None,
      "native_job_not_promoted":True,
      "limitations":"Accepted watch force may need time semantics check; oldPoints, meshPhi, V0 and preCICE history are not proven by equal field files."
    }
    return report

def test():
    a="Time = 0.032625\nforces bladeForces write:\n Total : (11.515 -0.2 0)\n"
    b=a+"Time = 0.03275\nforces bladeForces write:\n Total : (0.018 0.0 0)\n"
    result=forces(b)
    assert len(result)==2
    assert result[0]["Fx_N"]==11.515
    assert result[1]["physical_time_s"]==.03275
    assert matching([(0.,.017),(.000125,.018)],.000125)==[.018]
    print("CROSS_JOB_91767_READ_ONLY_FORENSIC_SELF_TEST_PASS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--base",type=Path,default=Path.home()/"hpcc-fsi")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:
        test();return
    base=a.base.expanduser().resolve(strict=True)
    result=status_report(base)
    print(json.dumps(result,indent=2,ensure_ascii=False))
    print("NO_SOLVER_NO_SBATCH_NO_SOURCE_OR_LIVE_MODIFICATIONS")

if __name__=="__main__":
    main()
