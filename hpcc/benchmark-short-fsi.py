#!/usr/bin/env python3
"""Independent short, fully coupled, fail-closed seagrass FSI CPU benchmark.

Uses the frozen controller for prepare/solve and injects ONLY:
  1. Shorter final time and final-output interval (in a NEW staged run),
  2. CalculiX OMP_NUM_THREADS for its *solid* subprocess,
  3. Optional IQN-ILS time-windows-reused in the NEW preCICE XML.
It never edits frozen source, mesh, or reference 87186. No restart is claimed.
"""
import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import traceback

SOURCE = Path.home() / "hpcc-fsi/seagrass-implicit-20261111"
BASELINE = (Path.home() / "hpcc-fsi/implicit-pilot-002-8mpi-timefix-87186"
            / "production/runs/hpcc-implicit-002")
INVARIANTS = [
    "fluid/constant/polyMesh/points",
    "fluid/constant/polyMesh/faces",
    "fluid/constant/polyMesh/owner",
    "fluid/constant/polyMesh/neighbour",
    "fluid/constant/polyMesh/boundary",
    "fluid/constant/dynamicMeshDict",
    "fluid/constant/motionReferenceDiffusivity",
    "fluid/system/fvSolution",
    "fluid/system/meshQualityDict",
    "fluid/system/blockMeshDict",
    "fluid/0/U",
    "fluid/0/p",
    "fluid/0/pointDisplacement",
    "solid/config.yml",
    "solid/seagrass.inp",
    "fluid/system/controlDict",
    "precice-config.xml",
]
TOL = 1e-5
DT = 0.000125


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def replace_one(pattern, replacement, source, name):
    updated, count = re.subn(pattern, replacement, source, count=0, flags=re.M)
    if count != 1:
        raise RuntimeError(f"{name}: expected exactly one substitution, got {count}")
    return updated


def patch_deck(source, end, steps):
    pattern = r"(?im)^(\*DYNAMIC,DIRECT[^\n]*\n)([^\n]+)"
    m = re.search(pattern, source)
    if not m:
        raise RuntimeError("Missing *DYNAMIC,DIRECT with next-line step sizes")
    entries = m.group(2).split(",")
    if len(entries) < 2 or abs(float(entries[0]) - DT) > 1e-12 or abs(float(entries[1]) - .02) > 1e-12:
        raise RuntimeError(f"Unexpected dynamic step parameters: {m.group(2)!r}")
    entries[1] = f" {end:.12g}"
    result = source[:m.start(2)] + ",".join(entries) + source[m.end(2):]
    result, n = re.subn(r"FREQUENCY=\d+", f"FREQUENCY={steps}", result)
    if n < 2:
        raise RuntimeError(f"Expected >=2 existing solid frequency fields, got {n}")
    return result


def snapshot_at(path, data, target):
    rows = path.read_text(errors="replace").splitlines()
    if len(rows) < 2:
        raise RuntimeError(f"Missing probe rows: {path}")
    fields = rows[0].split()
    for line in reversed(rows[1:]):
        vals = line.split()
        if len(vals) != len(fields):
            continue
        try:
            record = dict(zip(fields, map(float, vals)))
        except ValueError:
            continue
        if abs(record.get("Time", -1.0) - target) <= 1e-9:
            return [record[f"{data}{i}"] for i in range(3)]
    raise RuntimeError(f"No {data} observation at t={target:.9g} in {path}")


def verify_normed(name, observed, reference, abs_tol, rel_tol):
    err = math.dist(observed, reference)
    magnitude = math.sqrt(sum(v*v for v in reference))
    limit = abs_tol + rel_tol * magnitude
    if not math.isfinite(err) or err > limit:
        raise RuntimeError(f"{name} disagreement: norm(diff)={err:.8g} > {limit:.8g}; "
                           f"trial={observed}; baseline={reference}")
    return {"trial": observed, "baseline": reference, "error_norm": err, "limit": limit}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--work", required=True, type=Path, help="NEW non-existing variant directory")
    p.add_argument("--threads", type=int, choices=[1, 2, 4], required=True)
    p.add_argument("--windows", type=int, default=6, choices=[5, 6, 8, 10, 20, 24])
    p.add_argument("--iqn-reuse", type=int, choices=[5, 10, 15], default=5)
    args = p.parse_args()

    if args.iqn_reuse != 5 and args.windows < 20:
        raise RuntimeError("IQN history variations require at least 20 windows")
    root = SOURCE.resolve(strict=True)
    reference = BASELINE.resolve(strict=True)
    original = root / "fsi-implicit-production/run_production.py"
    if not original.is_file():
        raise RuntimeError(f"Frozen controller missing: {original}")
    baseline_state = json.loads((reference.parent.parent / "STATE.json").read_text())
    assert baseline_state.get("status") == "HPCC_0P02_IMPLICIT_PASS_RESTART_UNVERIFIED"
    assert baseline_state.get("accepted_windows") == 160
    assert baseline_state.get("participant_exit_codes") == {"fluid": 0, "solid": 0}
    assert baseline_state.get("dt_s") == DT
    assert Path("/usr/bin/time").is_file()
    assert os.environ.get("WM_PROJECT_VERSION") == "v2512"
    work = args.work.expanduser().resolve()
    if work.exists():
        raise RuntimeError(f"Refusing existing directory: {work}")
    if work.is_relative_to(reference) or work.is_relative_to(root):
        raise RuntimeError("Benchmark must be isolated from frozen sources and baseline")
    work.mkdir(parents=True, exist_ok=False)
    statefile = work / "STATE.json"
    state = {
        "status": "STAGING", "mode": "short-real-implicit-fsi-benchmark",
        "fluid_mpi_ranks": 8, "calculix_omp_threads": args.threads,
        "dt_s": DT, "target_time_s": args.windows * DT, "gate_windows": args.windows,
        "iqn_time_windows_reused": args.iqn_reuse,
        "checkpoint_restart": "UNVERIFIED", "baseline": str(reference),
        "controller": str(original),
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    def save(data):
        tmp = statefile.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n")
        tmp.replace(statefile)
    save(state)
    try:
        spec = importlib.util.spec_from_file_location("frozen_fsi_benchmark_source", original)
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        assert runner.ROOT == root
        assert runner.TOL == TOL
        runner.WORK = work
        runner.HISTORY = root / "runs/fsi-0.02s-20261102T030440Z-10ae15"
        runner.RANKS = 8
        runner.DT = DT
        runner.END = .02  # Needed by the ORIGINAL immutable three-stage input preparation
        runner.OFFSET = 0.
        runner.GATES = (160,)
        runner.CHECKPOINT_STEPS = 80
        run = work / "runs/hpcc-implicit-002"
        run.parent.mkdir()
        run.mkdir()
        fluid, solid = runner.prepare(run)

        pre_patch_hashes = {}
        for relative in INVARIANTS:
            a, b = run / relative, reference / relative
            if not a.is_file() or not b.is_file():
                raise RuntimeError(f"Required input for comparison is missing: {relative}")
            if digest(a) != digest(b):
                raise RuntimeError(f"Frozen 87186 input mismatch BEFORE any trial changes: {relative}")
            pre_patch_hashes[relative] = digest(a)
        print("FROZEN_87186_INPUT_BYTEWISE_MATCH_PASS", flush=True)

        n = args.windows
        t = n * DT
        xml = run / "precice-config.xml"
        doc = xml.read_text()
        doc = replace_one(r'(<max-time value=")0\.02(")', rf'\g<1>{t:.12g}\2', doc, "preCICE max-time")
        if args.iqn_reuse != 5:
            doc = replace_one(r'(<time-windows-reused value=")5(")',
                              rf'\g<1>{args.iqn_reuse}\2', doc, "IQN reuse")
        if doc.count('limit="1e-05"') != 2 or 'coupling-scheme:parallel-implicit' not in doc:
            raise RuntimeError("Strict convergence controls changed unexpectedly")
        xml.write_text(doc)

        control = fluid / "system/controlDict"
        txt = control.read_text()
        txt = replace_one(r"(^\s*endTime\s+)0\.02(\s*;)", rf"\g<1>{t:.12g}\2", txt, "controlDict endTime")
        txt = replace_one(r"(writeControl timeStep; writeInterval )80",
                          rf"\g<1>{n}", txt, "controlDict writeInterval")
        control.write_text(txt)

        deck = solid / "seagrass.inp"
        deck.write_text(patch_deck(deck.read_text(), t, n))

        # Log every permitted mutation, including original and new content hashes.
        mutated = {}
        for path in (xml, control, deck):
            relative = path.relative_to(run).as_posix()
            mutated[relative] = {"baseline_sha256": pre_patch_hashes[relative],
                                 "candidate_sha256": digest(path)}
        variant = {
            "threads": args.threads, "windows": n, "t_end_s": t,
            "iqn_reuse": args.iqn_reuse, "mutations": mutated,
            "frozen_input_sha256": pre_patch_hashes, "original_baseline": str(reference),
            "notes": "Only final time, output frequency, and optional IQN history changed in staged copies. "
                     "Only solid OMP_NUM_THREADS changed at process launch.",
        }
        (run / "PERFORMANCE_VARIANT.json").write_text(json.dumps(variant, indent=2) + "\n")
        binding_file = run / "INPUT_BINDING.json"
        binding = json.loads(binding_file.read_text())
        if "inputs_sha256" in binding:
            for rel in mutated:
                if rel in binding["inputs_sha256"]:
                    binding["inputs_sha256"][rel] = mutated[rel]["candidate_sha256"]
            binding["short_fsi_performance_variant"] = "PERFORMANCE_VARIANT.json"
            binding_file.write_text(json.dumps(binding, indent=2) + "\n")

        for name in ("Fluid", "Solid"):
            runner.command(run, f"perf-validate-{name}",
                           ["precice-config-validate", str(xml), name], run)
        print("SHORT_FSI_CONFIG_VALIDATION_PASS", flush=True)

        # Intercept ONLY one matching CalculiX launch; never modify frozen controller.
        actual_popen = subprocess.Popen
        hits = []
        class SubprocessProxy:
            def __getattr__(self, name):
                return getattr(subprocess, name)
            def Popen(self, cmd, **kw):
                cwd = Path(kw.get("cwd", "/")).resolve()
                if cwd == solid.resolve():
                    if str(runner.CCX) not in [str(x) for x in cmd]:
                        raise RuntimeError("Unexpected process in the solid working directory")
                    env = dict(kw["env"])
                    if env.get("OMP_NUM_THREADS") != "2":
                        raise RuntimeError("Frozen controller thread baseline unexpectedly changed")
                    env["OMP_NUM_THREADS"] = str(args.threads)
                    kw["env"] = env
                    hits.append(True)
                    print(f"VERIFIED_SOLID_THREAD_OVERRIDE={args.threads}", flush=True)
                return actual_popen(cmd, **kw)
        runner.subprocess = SubprocessProxy()
        runner.END = t
        runner.GATES = (n,)
        runner.CHECKPOINT_STEPS = n
        state.update(status="PREFLIGHT_PASS", run=str(run))
        save(state)

        print(f"BEGIN_REAL_FSI_VARIANT threads={args.threads} windows={n} iqn={args.iqn_reuse}", flush=True)
        runner.solve(run, fluid, solid, state)
        if len(hits) != 1:
            raise RuntimeError(f"Expected exactly one intercepted solid launch, observed {len(hits)}")
        gate_file = run / f"GATE-{n:04d}.json"
        gate = json.loads(gate_file.read_text())
        windows = json.loads((run / "WINDOWS.json").read_text())
        assert len(windows) == n
        assert gate["status"] == "LIVE_GATE_PASS"
        assert abs(gate["gate_s"] - t) < 1e-10
        assert all(w["force_residual"] <= TOL and w["displacement_residual"] <= TOL
                   for w in windows)
        final_state = json.loads(statefile.read_text())
        assert final_state.get("participant_exit_codes") == {"fluid": 0, "solid": 0}
        quality = gate["quality"]
        assert 0 < quality["min_volume_m3"]
        assert quality["max_nonorthogonality_deg"] <= 65
        assert quality["max_Co"] <= .5 and quality["max_mesh_Co"] <= .5

        actual_tips = snapshot_at(solid / "precice-Solid-watchpoint-Blade-Tip.log",
                                  "Displacement", t)
        base_tips = snapshot_at(reference / "solid/precice-Solid-watchpoint-Blade-Tip.log",
                                "Displacement", t)
        actual_loads = snapshot_at(solid / "precice-Solid-watchintegral-Interface-Integral.log",
                                   "Force", t)
        base_loads = snapshot_at(reference / "solid/precice-Solid-watchintegral-Interface-Integral.log",
                                 "Force", t)
        comparison = {
            "tip": verify_normed("tip_m", actual_tips, base_tips, 2e-6, .02),
            "loads": verify_normed("interface_load_N", actual_loads, base_loads, 5e-4, .02),
        }
        result = {
            "status": "SHORT_FSI_PERFORMANCE_PASS", "threads": args.threads,
            "windows": n, "time_s": t, "iqn_reuse": args.iqn_reuse,
            "wall_s": gate["wall_s"], "s_per_window": gate["wall_s"]/n,
            "coupling_iterations": sum(w["iterations"] for w in windows),
            "iterations_per_window": sum(w["iterations"] for w in windows)/n,
            "tip_and_load_comparison": comparison,
            "participant_exit_codes": final_state["participant_exit_codes"],
            "quality": quality, "mesh_recreated": False,
            "restart_verified": False,
        }
        (work / "PERFORMANCE_RESULT.json").write_text(json.dumps(result, indent=2)+"\n")
        state.update(status="SHORT_FSI_PERFORMANCE_PASS",
                     performance_result=str(work / "PERFORMANCE_RESULT.json"),
                     checkpoint_restart="UNVERIFIED")
        save(state)
        print("SHORT_FSI_PERFORMANCE_PASS", json.dumps(result, sort_keys=True), flush=True)
    except BaseException as exc:
        state.update(status="FAILED", reason=repr(exc))
        save(state)
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
