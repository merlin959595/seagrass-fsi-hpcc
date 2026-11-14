#!/usr/bin/env python3
"""Run immutable 0.02 s / 8-MPI implicit FSI gate using the transferred WSL controller.

No edits to the frozen controller, input tree, original SIF, or local WSL job.
This deliberately does not claim a verified persistent coupled restart.
"""
import argparse
import datetime
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import sys
import traceback

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--mode", choices=("preflight", "run"), required=True)
    p.add_argument("--ranks", choices=(8, 16, 24), type=int, default=8)
    args = p.parse_args()
    root = args.root.resolve(strict=True)
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)

    source = root / "fsi-implicit-production/run_production.py"
    assert source.is_file(), source
    assert (root / "fsi-explicit-test/inputs/SOURCE_BINDING.json").is_file()
    assert (root / "runs/fsi-0.02s-20261102T030440Z-10ae15/checkpoint_manifest.json").is_file()
    assert os.environ.get("WM_PROJECT_VERSION") == "v2512"
    assert "5.0.7" in os.popen("mpirun --version").read()
    assert os.path.exists("/opt/precice-3.4.1-ompi5/lib/libprecice.so.3")

    spec = importlib.util.spec_from_file_location("frozen_implicit_controller", source)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    # Override ONLY orchestration settings in memory, not source files.
    assert runner.ROOT == root
    runner.WORK = work
    runner.HISTORY = root / "runs/fsi-0.02s-20261102T030440Z-10ae15"
    runner.RANKS = args.ranks
    runner.DT = 0.000125
    runner.END = 0.02
    runner.OFFSET = 0.0
    runner.GATES = (160,)
    runner.CHECKPOINT_STEPS = 80
    assert round(runner.END / runner.DT) == runner.GATES[-1]

    run = work / "runs" / "hpcc-implicit-002"
    run.parent.mkdir()
    run.mkdir()
    state = {
        "status": "PREFLIGHT",
        "mode": args.mode,
        "run": str(run),
        "fluid_mpi_ranks": runner.RANKS,
        "calculix_omp_threads": 2,
        "dt_s": runner.DT,
        "target_time_s": runner.END,
        "gate_windows": runner.GATES[-1],
        "checkpoint_restart": "UNVERIFIED",
        "source_controller": str(source),
        "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    runner.save(work / "STATE.json", state)
    with (work / "pilot.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            fluid, solid = runner.prepare(run)
            state["status"] = "PREFLIGHT_PASS"
            runner.save(work / "STATE.json", state)
            if args.mode == "preflight":
                print("FSI_002_PREFLIGHT_PASS", flush=True)
                print(f"case={run}", flush=True)
                return 0

            print("FSI_002_REAL_COUPLING_START", flush=True)
            runner.solve(run, fluid, solid, state)
            assert (run / "GATE-0160.json").is_file()
            gate = json.loads((run / "GATE-0160.json").read_text())
            assert gate["status"] == "LIVE_GATE_PASS" and abs(gate["gate_s"]-0.02) < 1e-10
            state["status"] = "HPCC_0P02_IMPLICIT_PASS_RESTART_UNVERIFIED"
            runner.save(work / "STATE.json", state)
            print("FSI_002_REAL_COUPLING_PASS", flush=True)
            print(f"case={run}", flush=True)
            return 0
        except BaseException as err:
            state["status"] = "FAILED"
            state["pilot_failure"] = repr(err)
            runner.save(work / "STATE.json", state)
            traceback.print_exc()
            raise

if __name__ == "__main__":
    sys.exit(main())
