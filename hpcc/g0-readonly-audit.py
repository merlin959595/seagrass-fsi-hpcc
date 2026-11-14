#!/usr/bin/env python3
"""Read-only G0 audit for the validated three-dimensional seagrass ALE-FSI HPC cases.

Reads actual deployed HPCC results and controller; does NOT submit jobs,
run solvers, touch frozen inputs, or claim that persistent restart works.
Optional --out stores a NEW JSON report and a same-name .md summary.
Standard library only. Intended to run on the HPCC login node.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import sys

RELATIVE_CASES = {
    "87186": "implicit-pilot-002-8mpi-timefix-87186/production",
    "89038": "performance-full160-job-89038/optimized-160",
    "89270": "performance-omp12-iqn15-job-89270/optimized-20",
}
HASHED_INPUTS = (
    "fluid/0/U",
    "fluid/0/p",
    "fluid/constant/polyMesh/points",
    "fluid/constant/polyMesh/faces",
    "fluid/constant/polyMesh/boundary",
    "fluid/constant/dynamicMeshDict",
    "fluid/system/preciceDict",
    "fluid/system/controlDict",
    "solid/config.yml",
    "solid/seagrass.inp",
    "precice-config.xml",
)
CHECKPOINT_NAMES = (
    "solid/seagrass.rout",
    "solid/seagrass.rin",
    "solid/kinematic_state.bin",
    "fluid/constant/motionReferenceDiffusivity",
    "restart_reference",
)
REQUIRED_WIN = {"87186": 160, "89038": 160, "89270": 20}


def stat(path):
    try:
        x = path.stat()
        return {"exists": True, "kind": "dir" if path.is_dir() else "file",
                "bytes": x.st_size, "mtime_utc": dt.datetime.fromtimestamp(
                    x.st_mtime, dt.timezone.utc).isoformat()}
    except (OSError, ValueError) as ex:
        return {"exists": False, "error": str(ex)}


def safe_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as ex:
        return {"_read_error": str(ex)}


def digest(path):
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError as ex:
        return "UNREADABLE: " + str(ex)


def sample_text(path, max_bytes=32768):
    """Bound the amount read even when solver logs are huge."""
    try:
        with path.open("rb") as f:
            size = f.seek(0, 2)
            f.seek(max(size - max_bytes, 0))
            raw = f.read(max_bytes)
        return raw.decode("utf-8", errors="replace")
    except OSError:
        return ""


def time_dirs(processor):
    result = []
    if not processor.is_dir():
        return result
    for entry in processor.iterdir():
        if not entry.is_dir():
            continue
        try:
            t = float(entry.name)
            if math.isfinite(t) and t >= 0:
                result.append((t, entry.name))
        except ValueError:
            continue
    return sorted(result)


def read_windows(path, expected):
    data = safe_json(path)
    result = {"file": stat(path)}
    if not isinstance(data, list):
        result["error"] = "Invalid WINDOWS.json: expected array"
        return result
    result["count"] = len(data)
    number = [r.get("window") for r in data if isinstance(r, dict)]
    result["contiguous"] = number == list(range(1, len(number) + 1))
    iters = [r.get("iterations") for r in data if isinstance(r, dict)
             and isinstance(r.get("iterations"), int)]
    if len(iters) == len(data) and iters:
        result["total_iterations"] = sum(iters)
        result["mean_iterations"] = statistics.mean(iters)
        result["median_iterations"] = statistics.median(iters)
        result["max_iterations"] = max(iters)
        groups = []
        for i in range(0, len(iters), 20):
            g = iters[i:i+20]
            groups.append({"first": i+1, "last": i+len(g),
                           "mean": statistics.mean(g), "max": max(g)})
        result["blocks_of_20"] = groups
    else:
        result["error"] = "Missing/noninteger iteration entries"
    residuals = []
    for r in data:
        if not isinstance(r, dict):
            continue
        a, b = r.get("force_residual"), r.get("displacement_residual")
        if isinstance(a, (float, int)) and isinstance(b, (float, int)):
            residuals.append((a, b))
    if len(residuals) == len(data) and residuals:
        result["max_force_residual"] = max(x[0] for x in residuals)
        result["max_disp_residual"] = max(x[1] for x in residuals)
        result["all_windows_below_1e-5"] = all(
            math.isfinite(x) and math.isfinite(y) and x <= 1e-5 and y <= 1e-5
            for x, y in residuals)
    result["expected_count"] = expected
    result["count_matches"] = len(data) == expected
    return result


def audit_case(base, name, rel):
    root = base / rel
    run = root / "runs/hpcc-implicit-002"
    state = safe_json(root / "STATE.json")
    result = {"state_path": str(root / "STATE.json"),
              "run_path": str(run),
              "state": state,
              "windows": read_windows(run / "WINDOWS.json", REQUIRED_WIN[name]),
              "quality_gate": safe_json(run / ("GATE-%04d.json" % REQUIRED_WIN[name])),
              "files": {}, "input_sha256": {}, "fluid_time_directories": {}}
    for item in HASHED_INPUTS:
        f = run / item
        result["files"][item] = stat(f)
        if f.is_file():
            result["input_sha256"][item] = digest(f)
    for item in CHECKPOINT_NAMES:
        result["files"][item] = stat(run / item)
    procs = sorted((p for p in (run / "fluid").glob("processor[0-9]*")
                    if p.is_dir() and re.fullmatch(r"processor[0-9]+", p.name)),
                   key=lambda x: int(x.name[len("processor"):]))
    result["processor_count"] = len(procs)
    result["processor_names"] = [p.name for p in procs]
    max_times = {}
    for p in procs:
        ts = time_dirs(p)
        latest = ts[-1] if ts else None
        max_times[p.name] = latest[0] if latest else None
        if latest:
            last = p / latest[1]
            result["fluid_time_directories"][p.name] = {
                "latest_time_s": latest[0],
                "latest_folder": latest[1],
                "latest_dir": stat(last),
                "pointDisplacement": stat(last / "pointDisplacement"),
                "mesh_points": stat(last / "polyMesh/points"),
                "U": stat(last / "U"), "p": stat(last / "p"),
            }
    result["checkpoint_evidence"] = {
        "fluid_eight_processors": len(procs) == 8,
        "latest_time_all_equal": bool(max_times) and None not in max_times.values()
                                 and max(max_times.values())-min(max_times.values()) < 1e-10,
        "latest_processor_times_s": max_times,
        "solid_rout_present": (run / "solid/seagrass.rout").is_file(),
        "solid_kinematic_state_present": (run / "solid/kinematic_state.bin").is_file(),
        "restart_reference_present": (run / "restart_reference").exists(),
        "continuation_verified": False,
    }
    for part in ("fluid", "solid"):
        profiler = run / part / "precice-profiling"
        if profiler.is_dir():
            files = sorted(p.name for p in profiler.iterdir() if p.is_file())
        else:
            files = []
        result["files"][part + "/precice-profiling"] = {
            "exists": profiler.is_dir(),
            "count": len(files),
            "sample_names": files[:8],
        }
    solid_log = sample_text(run / "solid.log", 256 * 1024)
    spooles = sample_text(run / "solid/spooles.out", 16 * 1024)
    result["solid_thread_evidence"] = {
        "ccx_spooles_max_cpu_mentions_tail": sorted(set(
            int(x) for x in re.findall(
                r"Using\s+up\s+to\s+(\d+)\s+cpu\(s\)\s+for\s+spooles",
                solid_log, re.I))),
        "spooles_actual_thread_mentions_tail": sorted(set(
            int(x) for x in re.findall(r"Using\s+(\d+)\s+threads?\b",
                                       spooles, re.I))),
        "solid_log": stat(run / "solid.log"),
        "spooles_out": stat(run / "solid/spooles.out"),
        "note": "Tail samples only; this is not a full factorization-time profile.",
    }
    result["restart_deck_indicators"] = {}
    deck = run / "solid/seagrass.inp"
    if deck.is_file():
        txt = deck.read_text(errors="replace")
        for key, pattern in {
            "restart_write": r"(?im)^\s*\*RESTART\s*,\s*WRITE",
            "restart_read": r"(?im)^\s*\*RESTART\s*,\s*READ",
            "dynamic_direct": r"(?im)^\s*\*DYNAMIC\s*,\s*DIRECT",
        }.items():
            result["restart_deck_indicators"][key] = bool(re.search(pattern, txt))
    precice_dict = run / "fluid/system/preciceDict"
    if precice_dict.is_file():
        txt = precice_dict.read_text(errors="replace")
        m = re.search(r"\brestartFromDeformed\s+(true|false)\s*;", txt)
        result["restart_deck_indicators"]["restartFromDeformed"] = (
            m.group(1) if m else "NOT_EXPLICIT_DEFAULT_TRUE_PER_DOC")
    return result


def inspect_controller(path):
    info = {"path": str(path), "stat": stat(path), "review_needed": True}
    if not path.is_file():
        return info
    lines = path.read_text(errors="replace").splitlines()
    keywords = re.compile(
        r"restart|checkpoint|rollback|precice|kinematic_state|rout|rin|"
        r"subprocess|Popen|writeInterval|startTime|solid|bash -c", re.I)
    hits = [{"line": i, "text": s[:220]} for i, s in enumerate(lines, 1)
            if keywords.search(s)]
    info.update({"sha256": digest(path), "total_lines": len(lines),
                 "matching_lines": len(hits), "selected_lines": hits[:90],
                 "note": "Keyword hits cannot prove persistent restart; full controller/adapter review required."})
    return info


def audit(base):
    base = base.expanduser().resolve()
    cases = {name: audit_case(base, name, rel) for name, rel in RELATIVE_CASES.items()}
    controller = (base / "seagrass-implicit-20261111"
                  / "fsi-implicit-production/run_production.py")
    src = inspect_controller(controller)
    trial = cases["89038"]["state"]
    old = cases["87186"]["state"]
    wall_old = old.get("elapsed_s") if isinstance(old, dict) else None
    wall_new = trial.get("elapsed_s") if isinstance(trial, dict) else None
    comparison = {}
    if isinstance(wall_old, (int,float)) and isinstance(wall_new, (int,float)) and wall_old > 0:
        comparison = {"reference_87186_wall_s": wall_old,
                      "optimized_89038_wall_s": wall_new,
                      "optimized_saved_pct": 100 * (wall_old-wall_new)/wall_old,
                      "optimized_seconds_per_window": wall_new/160}
    hashes = {name: v["input_sha256"] for name,v in cases.items()}
    same_mesh = {item: hashes["87186"].get(item)==hashes["89038"].get(item)
                 for item in ("fluid/constant/polyMesh/points",
                              "fluid/constant/polyMesh/faces",
                              "fluid/constant/polyMesh/boundary")}
    errors = []
    for key,c in cases.items():
        if not c["windows"].get("contiguous") or not c["windows"].get("count_matches"):
            errors.append(key + ": window log incomplete or noncontiguous")
    if not all(same_mesh.values()):
        errors.append("87186 vs 89038 native mesh hashes differ; investigate before restart")
    if trial.get("status") != "OPTIMIZED_0P02_FSI_PASS":
        errors.append("89038 final pass status missing")
    return {
        "schema": "seagrass-fsi-g0-audit-v1",
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "mode": "READ_ONLY_NO_SLURM_NO_SOLVER",
        "base": str(base),
        "cases": cases,
        "controller": src,
        "comparison": comparison,
        "native_mesh_87186_89038_same_hash": same_mesh,
        "audit_errors": errors,
        "g0_complete": False,
        "g1_restart_verified": False,
        "g1_blockers": [
            "No independent stop/resume vs uninterrupted trajectory comparison",
            "Custom CalculiX persistent adapter restart semantics not verified",
            "preCICE new-session interface initialization and IQN history not verified",
            "OpenFOAM dynamic ALE mesh/field time-consistent restoration not verified",
        ],
        "important": "File presence or single-run success is NOT proof of three-participant persistent restart.",
    }


def markdown_report(a):
    def case_row(k):
        c=a["cases"][k]; s=c["state"]; w=c["windows"]
        return (f"| {k} | {s.get('status', 'MISSING')} | "
                f"{w.get('count', 'N/A')}/{REQUIRED_WIN[k]} | "
                f"{s.get('elapsed_s', 'N/A')} | "
                f"{c['processor_count']} |")
    lines=[
        "# G0只读审计：三维海草ALE–FSI",
        "",
        f"生成时间：{a['generated_utc']}",
        "",
        "注意：这是**证据收集**，不是通过重启验收，也不提交计算。",
        "",
        "| Job | 状态 | 连续窗口 | 墙钟秒 | 分区目录数 |",
        "|---|---|---:|---:|---:|",
        *(case_row(k) for k in RELATIVE_CASES),
        "",
        "## 原87186与89038的原生网格哈希一致性",
        *(f"- {k}: {'一致' if v else '不一致/缺失'}"
          for k,v in a["native_mesh_87186_89038_same_hash"].items()),
        "",
        "## 重启候选文件（不代表能续算）",
    ]
    c=a["cases"]["89038"]["checkpoint_evidence"]
    lines += [f"- {key}: {value}" for key,value in c.items() if key != "latest_processor_times_s"]
    lines += [
        "", "## 已识别审计问题",
        *([f"- {e}" for e in a["audit_errors"]] or ["- 尚未从静态输出中发现致命缺失，仍需动态审计。"]),
        "",
        "## 重启阻断项",
        *[f"- {e}" for e in a["g1_blockers"]],
        "",
        f"原控制器：{a['controller']['path']}",
        f"控制器存在：{a['controller']['stat']['exists']}",
        "",
        "**当前结论：G0仅完成自动证据收集；G1未通过。禁止将rollback当作多作业persistent restart。**",
        "",
    ]
    return "\n".join(lines)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base", type=Path, default=Path.home()/"hpcc-fsi")
    p.add_argument("--out", type=Path, help="NEW JSON result path outside frozen cases")
    p.add_argument("--self-test", action="store_true", help="Check pure parser invariants")
    args=p.parse_args()
    if args.self_test:
        assert not re.fullmatch(r"processor[0-9]+", "processor_x")
        assert re.fullmatch(r"processor[0-9]+", "processor10")
        assert len(REQUIRED_WIN)==3
        print("G0_READ_ONLY_STATIC_SELF_TEST_PASS")
        return
    a=audit(args.base)
    print("G0_READ_ONLY_AUDIT_COMPLETED")
    c=a["cases"]
    for k in RELATIVE_CASES:
        s=c[k]["state"]
        w=c[k]["windows"]
        print(f"JOB={k} status={s.get('status','MISSING')} "
              f"windows={w.get('count','?')}/{REQUIRED_WIN[k]} "
              f"processors={c[k]['processor_count']}")
    print("MESH_HASH_EQUAL:", a["native_mesh_87186_89038_same_hash"])
    print("G1_PERSISTENT_RESTART=UNVERIFIED")
    print("AUDIT_ERRORS=", json.dumps(a["audit_errors"],ensure_ascii=False))
    if args.out is not None:
        dest=args.out.expanduser().resolve()
        base=args.base.expanduser().resolve()
        # Explicitly forbid any output inside frozen source/results subtree.
        protected=[
            (base / rel).resolve() for rel in RELATIVE_CASES.values()
        ] + [(base/"seagrass-implicit-20261111").resolve()]
        if any(dest.is_relative_to(x) for x in protected):
            raise SystemExit("STOP: output would alter a frozen project directory")
        md=dest.with_suffix(".md")
        if dest.exists() or md.exists():
            raise SystemExit("STOP: report already exists, refusing overwrite")
        dest.parent.mkdir(parents=True,exist_ok=True)
        with dest.open("x", encoding="utf-8") as out:
            json.dump(a,out,indent=2,ensure_ascii=False)
            out.write("\n")
        with md.open("x",encoding="utf-8") as out:
            out.write(markdown_report(a))
        print("G0_JSON_REPORT=",dest)
        print("G0_MD_REPORT=",md)


if __name__=="__main__":
    main()
