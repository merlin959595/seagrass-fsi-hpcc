#!/usr/bin/env python3
"""One-stage, fail-closed HPCC implicit FSI pilot.
Prep/checkMesh/decomposePar once, then run real coupling; no restart claims.
No writes to frozen 199 MB transfer files or the original WSL simulation.
"""
import argparse
import datetime as dt
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import traceback

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--ranks", choices=(8, 16, 24), type=int, default=8)
    args = p.parse_args()
    root = args.root.resolve(strict=True)
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=False)
    source = root / "fsi-implicit-production" / "run_production.py"
    assert source.is_file(), source
    assert (root / "fsi-explicit-test/inputs/SOURCE_BINDING.json").is_file()
    assert (root / "runs/fsi-0.02s-20261102T030440Z-10ae15/checkpoint_manifest.json").is_file()
    assert os.environ.get("WM_PROJECT_VERSION") == "v2512"
    assert os.popen("mpirun --version").read().find("5.0.7") != -1
    assert Path("/opt/precice-3.4.1-ompi5/lib/libprecice.so.3").exists()
    spec = importlib.util.spec_from_file_location("frozen_implicit_controller_scotch", source)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    assert Path(runner.ROOT).resolve() == root
    # Override orchestration values only in memory, leaving frozen controller untouched.
    runner.WORK = work
    runner.HISTORY = root / "runs/fsi-0.02s-20261102T030440Z-10ae15"
    runner.RANKS = args.ranks
    runner.DT = 0.000125
    runner.END = 0.02
    runner.OFFSET = 0.0
    runner.GATES = (160,)
    runner.CHECKPOINT_STEPS = 80
    assert round(runner.END / runner.DT) == 160
    run = work / "runs" / "hpcc-implicit-002-scotch"
    run.parent.mkdir()
    run.mkdir()
    state = {
       "status": "PREFLIGHT",
       "run": str(run), "ranks": args.ranks, "dt_s": runner.DT,
       "target_time_s": runner.END, "target_windows": 160,
       "source_controller": str(source), "persistent_restart": "UNVERIFIED",
       "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    runner.save(work / "STATE.json", state)
    with (work / "pilot.lock").open("a") as lock:
      fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
      try:
        print("BEGIN_REAL_FSI_PREPARATION", flush=True)
        fluid, solid = runner.prepare(run)
        fluid_path = Path(fluid)
        # Ensure the staged mesh was actually split for requested ranks;
        # changing launcher -np without decomposeParDict is NOT sufficient.
        part_ids = sorted(int(m.group(1)) for d in fluid_path.iterdir()
                          if d.is_dir() and (m := re.fullmatch(r"processor(\d+)", d.name)))
        expected = list(range(args.ranks))
        if part_ids != expected:
            raise RuntimeError(f"DECOMPOSE_RANK_MISMATCH: {part_ids} != {expected}")
        meshlog = run / "initial-native-check.log"
        if not meshlog.is_file() or "Mesh OK." not in meshlog.read_text(errors="replace"):
            raise RuntimeError("NO_NATIVE_CHECKMESH_PASS")
        state["verified_fluid_subdomains"] = args.ranks
        state["status"] = "PREFLIGHT_PASS"
        runner.save(work / "STATE.json", state)
        print("FSI_002_SCOTCH_PREFLIGHT_PASS", flush=True)
        print(f"fluid={fluid_path} solid={solid}", flush=True)
        print("BEGIN_REAL_160_WINDOW_IMPLICIT_COUPLING", flush=True)
        state["status"] = "RUNNING"
        runner.save(work / "STATE.json", state)
        runner.solve(run, fluid, solid, state)
        gate_file = run / "GATE-0160.json"
        if not gate_file.is_file():
            raise RuntimeError(f"MISSING_REAL_COUPLING_GATE: {gate_file}")
        gate = json.loads(gate_file.read_text())
        if gate.get("status") != "LIVE_GATE_PASS" or abs(float(gate.get("gate_s",-1)) - 0.02) > 1e-10:
            raise RuntimeError(f"COUPLING_GATE_FAILED: {gate}")
        state["status"] = "HPCC_0P02_IMPLICIT_PASS_RESTART_UNVERIFIED"
        runner.save(work / "STATE.json", state)
        print("HPCC_IMPLICIT_0P02_ACCEPTED_160_WINDOWS_PASS", flush=True)
        return 0
      except BaseException as exc:
        state["status"] = "FAILED"
        state["failure"] = repr(exc)
        runner.save(work / "STATE.json", state)
        traceback.print_exc()
        raise

if __name__ == "__main__":
    sys.exit(main())
