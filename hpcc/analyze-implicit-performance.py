#!/usr/bin/env python3
"""READ-ONLY performance triage of a completed OpenFOAM-preCICE-CalculiX FSI pilot.

No case modifications, job submissions, meshing, or external dependencies.
Run: python3 hpcc/analyze-implicit-performance.py PILOT_DIR
"""
import collections
import json
import re
import statistics as stats
import sys
from pathlib import Path

def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 analyze-implicit-performance.py PILOT_DIR")
    pilot = Path(sys.argv[1]).expanduser().resolve(strict=True)
    work = pilot / "production"
    run = work / "runs" / "hpcc-implicit-002"
    state = json.loads((work / "STATE.json").read_text())
    windows = json.loads((run / "WINDOWS.json").read_text())
    assert all(r["window"] == i for i, r in enumerate(windows, 1)), "Non-contiguous accepted windows"
    assert state["accepted_windows"] == len(windows), "State and windows count do not match"
    it = [int(r["iterations"]) for r in windows]
    elapsed = float(state.get("elapsed_s", 0))
    print("=== FROZEN 0.02s BASELINE / read only ===")
    print("status:", state["status"])
    print("target_t_s:", state.get("target_time_s"), "accepted_t_s:", state.get("accepted_time_s"))
    print("accepted:", len(it), "ranks:", state.get("fluid_mpi_ranks"), "dt_s:", state["dt_s"])
    print("total_accepted_iterations:", sum(it))
    print("wall_s:", round(elapsed, 2), "wall_h:", round(elapsed / 3600, 3))
    print("mean_wall_per_accepted_window_s:", round(elapsed / len(it), 3) if it else "N/A")
    print("approx_wall_per_coupling_iteration_s:", round(elapsed / sum(it), 3) if it else "N/A")
    print("min/median/max_iterations:", min(it), stats.median(it), max(it))
    print("mean_iterations:", round(stats.mean(it), 3))
    print("iterations_frequency_top:", collections.Counter(it).most_common(12))
    for lo, hi in [(1, 10), (11, 40), (41, 80), (81, 120), (121, 160)]:
        group = it[lo-1:hi]
        if group:
            print(f"window_{lo:03d}_to_{min(hi,len(it)):03d}",
                  "mean_iterations:", round(stats.mean(group), 3),
                  "min/max:", min(group), max(group))
    for key, value in (state.get("mesh_and_rollbacks") or {}).items():
        print("metric", key, value)
    print("=== Fluid solver effort (sampled all recorded log lines) ===")
    totals = collections.Counter()
    samples = collections.defaultdict(list)
    guard = 0
    outer = 0
    fluid_log = run / "fluid.log"
    if fluid_log.is_file():
        pattern = re.compile(r"\bSolving for (p|pcorr|Ux|Uy|Uz|k|omega)\b.*?No Iterations (\d+)")
        with fluid_log.open(errors="replace") as stream:
            for line in stream:
                m = pattern.search(line)
                if m:
                    field, n = m.group(1), int(m.group(2))
                    totals[field] += n
                    if len(samples[field]) < 10000:
                        samples[field].append(n)
                if line.startswith("SEAGRASS_MESH_GUARD"):
                    guard += 1
                if "PIMPLE: iteration" in line:
                    outer += 1
    else:
        print("fluid.log missing")
    for field, total in totals.most_common():
        vals = samples[field]
        print(f"{field}: cumulative_linear_iterations={total}, logged_solver_calls~{len(vals)},"
              f" mean_iterations_per_call~{round(stats.mean(vals), 2) if vals else 0}")
    print("guard_count_from_fluid_log:", guard)
    print("logged_PIMPLE_iteration_lines:", outer)
    print("=== Existing preCICE profiling artifacts ===")
    for part in ("fluid", "solid"):
        d = run / part / "precice-profiling"
        print(part, "exists:", d.is_dir(), "sample_files:",
              [p.name for p in sorted(d.glob("*"))[:8]] if d.is_dir() else [])
    print("=== Next step ===")
    print("Use window trend to decide whether IQN-ILS history is improving.")
    print("Do NOT change mesh, 1e-5 tolerance, dt, or validated initial velocity during performance tests.")

if __name__ == "__main__":
    main()
