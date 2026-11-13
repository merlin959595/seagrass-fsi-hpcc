#!/usr/bin/env python3
"""Read-only re-audit of the completed 88107 single-thread real FSI run.

Does not rewrite the FAILED original STATE.json or backfill a PASS into the
original benchmark directory. Prints a JSON report; optional --out writes to
a distinct, new file only after all checks pass.
"""
import argparse
import importlib.util
import json
import math
from pathlib import Path

def read(path):
    return json.loads(path.read_text())

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--job", type=int, default=88107)
    p.add_argument("--base", type=Path, default=Path.home() / "hpcc-fsi")
    p.add_argument("--benchmark", type=Path)
    p.add_argument("--out", type=Path)
    args = p.parse_args()

    script = args.benchmark or args.base / "benchmark-short-fsi.py"
    spec = importlib.util.spec_from_file_location("short_fsi_tools", script)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    base = args.base / f"performance-threads-job-{args.job}"
    trial = base / "threads-1"
    run = trial / "runs/hpcc-implicit-002"
    original = read(trial / "STATE.json")
    if original.get("status") != "FAILED" or original.get("accepted_windows") != 6:
        raise RuntimeError(f"Unexpected state: {original.get('status')}, accepted={original.get('accepted_windows')}")
    if original.get("participant_exit_codes") != {"fluid": 0, "solid": 0}:
        raise RuntimeError("Incomplete/nonzero solver exit evidence")
    if "SPOOLES did not confirm 1 threads" not in original.get("reason", ""):
        raise RuntimeError(f"Unexpected original failure reason: {original.get('reason')}")

    # Read frozen baseline and the already-validated 2-thread result; no mutation.
    baseline = helper.BASELINE.resolve(strict=True)
    two = read(base / "threads-2/PERFORMANCE_RESULT.json")
    if two.get("status") != "SHORT_FSI_PERFORMANCE_PASS" or two.get("windows") != 6:
        raise RuntimeError("Missing trusted thread-2 comparator")
    trial_variant = read(run / "PERFORMANCE_VARIANT.json")
    if trial_variant.get("threads") != 1 or trial_variant.get("windows") != 6:
        raise RuntimeError("Unexpected experiment config")
    for relative, digest in trial_variant["frozen_input_sha256"].items():
        if helper.digest(baseline / relative) != digest:
            raise RuntimeError(f"Original baseline input has changed: {relative}")
    for relative, info in trial_variant["mutations"].items():
        if helper.digest(run / relative) != info["candidate_sha256"]:
            raise RuntimeError(f"Modified trial input has changed: {relative}")

    thread = helper.verify_spooles_threads(run / "solid", run / "solid.log", 1)
    gate = read(run / "GATE-0006.json")
    windows = read(run / "WINDOWS.json")
    if gate.get("status") != "LIVE_GATE_PASS" or len(windows) != 6:
        raise RuntimeError("FSI gate / window count not PASS")
    t = 6 * helper.DT
    if not math.isclose(gate["gate_s"], t, abs_tol=1e-10):
        raise RuntimeError("Unexpected gate physical time")
    if any(w["force_residual"] > helper.TOL or w["displacement_residual"] > helper.TOL
           for w in windows):
        raise RuntimeError("Coupling residual above tolerance")
    q = gate["quality"]
    if not (q["min_volume_m3"] > 0 and q["max_nonorthogonality_deg"] <= 65
            and q["max_Co"] <= .5 and q["max_mesh_Co"] <= .5):
        raise RuntimeError("Gate quality failure")

    solid = run / "solid"
    tip = helper.verify_normed("tip_m",
        helper.snapshot_at(solid / "precice-Solid-watchpoint-Blade-Tip.log", "Displacement", t),
        helper.snapshot_at(baseline / "solid/precice-Solid-watchpoint-Blade-Tip.log", "Displacement", t),
        2e-6, .02)
    loads = helper.verify_normed("interface_load_N",
        helper.snapshot_at(solid / "precice-Solid-watchintegral-Interface-Integral.log", "Force", t),
        helper.snapshot_at(baseline / "solid/precice-Solid-watchintegral-Interface-Integral.log", "Force", t),
        5e-4, .02)
    wall = float(gate["wall_s"])
    if not math.isfinite(wall) or wall <= 0:
        raise RuntimeError("Invalid wallclock")
    result = {
        "status": "READ_ONLY_RETROSPECTIVE_AUDIT_PASS",
        "original_state_unchanged": original["status"],
        "original_failure_reason": original["reason"],
        "job": args.job,
        "threads": 1,
        "windows": 6,
        "wall_s": wall,
        "s_per_window": wall / 6,
        "coupling_iterations": sum(w["iterations"] for w in windows),
        "spooles_thread_evidence": thread,
        "participant_exit_codes": original["participant_exit_codes"],
        "quality": q,
        "tip_and_load_comparison": {"tip": tip, "loads": loads},
        "baseline": str(baseline),
        "trial": str(trial),
        "restart_verified": False,
    }
    if args.out is not None:
        target = args.out.expanduser().resolve()
        if target.exists():
            raise RuntimeError(f"Refusing overwrite: {target}")
        if target.is_relative_to(trial) or target.is_relative_to(baseline):
            raise RuntimeError("Audit report must stay outside trial and baseline")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, indent=2) + "\n")
    print("THREAD1_88107_RETROSPECTIVE_AUDIT_PASS")
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
