#!/usr/bin/env python3
"""Conservative, restart-compatible ALE repair controller for 96764.

All production data remain immutable. This controller uses the existing
HPCC resume-cycles.py (not a substitute CFD/FSI solver) and hooks ONLY the
private staging function to adjust processor5's constant reference face field.

Explicitly experimental: no candidate is accepted without native mesh guards,
both participant exit codes, accepted time windows, and restart files.
"""
from __future__ import annotations
import argparse
from collections import deque
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import struct
import subprocess
import sys
import time

DT = 0.000125
T0 = 0.5635
FAILED = 0.579375
RANK = 5
CELL = 3535
EXPECTED_NEIGHBOURS = {3409, 3531, 3532, 3533, 3534, 20547}
EXPECTED_FACES = {11491, 11899, 11901, 11903, 11905, 11907}
EXPECTED_LIB_SHA = "1032420382c07a8138f122199017013ed0aa242410f73a41330cbff199aac1a2"
ROOT_NAME = "seagrass-fsi558-runs.sNIpi9"
REPAIR_NAME = "repair-96764-github-20261122-v3"
CANDIDATES = ((1.20, 8), (0.85, 8), (1.35, 12))
FIRST_WINDOWS, SECOND_WINDOWS = 144, 176

def die(message):
    raise RuntimeError(message)

def dump(path, data):
    if path.exists():
        die("NO_OVERWRITE_EXISTING_REPORT " + str(path))
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def source_paths():
    p = Path("/data/icto") / os.environ["USER"] / ROOT_NAME
    home = Path.home()
    a = home / "hpcc-fsi/three-day-resume-20261119/.mesh-repair558-data.29CSy1"
    src = p / "trial-96763/runs/hpcc-implicit-002"
    fail = p / "trial-96764/runs/hpcc-implicit-002"
    local = p / REPAIR_NAME
    return p, a, src, fail, local

def read_labels(path):
    data = Path(path).read_bytes()
    header = re.search(rb"FoamFile\s*\{.*?\}", data, re.S)
    if not header:
        die("FOAM_HEADER_MISSING " + str(path))
    h = header.group()
    fm = re.search(rb"\bformat\s+(\w+)\s*;", h)
    archm = re.search(rb'arch\s+"([^"]+)"', h)
    arch = archm.group(1).decode() if archm else ""
    width = 8 if "label=64" in arch else 4
    endian = ">" if "MSB" in arch else "<"
    mat = re.search(rb"(?m)^\s*(\d+)\s*\(", data[header.end():])
    if not mat:
        die("FOAM_LIST_MISSING " + str(path))
    n = int(mat.group(1))
    start = header.end() + mat.end()
    # OpenFOAM sometimes declares 'binary' while writing ASCII labelLists.
    end = data.find(b")", start)
    if end >= 0:
        body = data[start:end].strip()
        if n == 0 and not body:
            return []
        if re.fullmatch(rb"[+\-\d\s]+", body or b"_"):
            vals = [int(x) for x in body.split()]
            if len(vals) == n:
                return vals
    if fm is None or fm.group(1) != b"binary":
        die("FOAM_ASCII_LABEL_COUNT_MISMATCH " + str(path))
    starts = []
    for pos in range(start, min(start + 16, len(data))):
        if data[start:pos].strip():
            break
        z = pos + n * width
        if z <= len(data) and re.match(rb"\s*\)", data[z:z+32]):
            starts.append(pos)
    if len(starts) != 1:
        die("FOAM_BINARY_BOUNDARY_AMBIGUOUS " + str(path))
    code = "q" if width == 8 else "i"
    return [x[0] for x in struct.iter_unpack(
        endian + code, data[starts[0]:starts[0]+n*width])]

def field_values(path):
    """Read ASCII or binary OpenFOAM surfaceScalarField internal values.

    Returns (original bytes, data_start, data_end, values). Binary reading uses
    scalar width/endianness declared in FoamFile.arch, and preserves all bytes
    outside the actual internalField payload (including boundaryField).
    """
    data = Path(path).read_bytes()
    hd = re.search(rb"FoamFile\s*\{.*?\}", data, re.S)
    if not hd:
        die("REFERENCE_FIELD_HEADER_MISSING " + str(path))
    head = hd.group()
    fmt_match = re.search(rb"\bformat\s+(ascii|binary)\s*;", head)
    if not fmt_match:
        die("REFERENCE_FIELD_FORMAT_UNKNOWN " + str(path))
    fmt = fmt_match.group(1)
    arch_match = re.search(rb'arch\s+"([^"]+)"', head)
    arch = arch_match.group(1).decode("ascii") if arch_match else ""
    m = re.search(
        rb"internalField\s+nonuniform\s+List<scalar>\s*(\d+)\s*\(",
        data[hd.end():])
    if not m:
        die("REFERENCE_FIELD_INTERNAL_LIST_MISSING " + str(path))
    n = int(m.group(1))
    if not 1 <= n <= 10000000:
        die("REFERENCE_FIELD_COUNT_OUT_OF_BOUNDS " + str(n))
    list_start = hd.end() + m.end()

    def validate(values):
        if len(values) != n or not all(math.isfinite(v) and v > 0 for v in values):
            die("REFERENCE_FIELD_VALUES_INVALID " + str(path))
        return values

    if fmt == b"ascii":
        end = data.find(b")", list_start)
        if end < 0 or not re.match(rb"\s*;", data[end+1:end+64]):
            die("REFERENCE_FIELD_ASCII_TERMINATOR_INVALID " + str(path))
        try:
            values = validate([float(x) for x in data[list_start:end].split()])
        except ValueError as exc:
            die("REFERENCE_FIELD_ASCII_PARSE_FAILED " + str(exc))
        return data, list_start, end, values

    if "scalar=64" in arch:
        width, code = 8, "d"
    elif "scalar=32" in arch:
        width, code = 4, "f"
    else:
        die("REFERENCE_FIELD_BINARY_ARCH_MISSING_SCALAR_WIDTH " + str(path))
    if "MSB" in arch:
        endian = ">"
    elif "LSB" in arch:
        endian = "<"
    else:
        die("REFERENCE_FIELD_BINARY_ARCH_MISSING_ENDIANNESS " + str(path))
    candidates = []
    for start in range(list_start, min(list_start + 17, len(data))):
        if data[list_start:start].strip():
            break
        end = start + n * width
        if end <= len(data) and re.match(rb"\s*\)\s*;", data[end:end+128]):
            candidates.append((start, end))
    if len(candidates) != 1:
        die("REFERENCE_FIELD_BINARY_PAYLOAD_BOUNDARY_AMBIGUOUS " +
            f"{path} candidates={candidates} count={n} width={width}")
    start, end = candidates[0]
    values = validate([x[0] for x in struct.iter_unpack(endian + code, data[start:end])])
    return data, start, end, values

def encode_field_payload(original, values):
    hd = re.search(rb"FoamFile\s*\{.*?\}", original, re.S)
    if not hd:
        die("ENCODE_FIELD_MISSING_FOAM_HEADER")
    head = hd.group()
    fmt = re.search(rb"\bformat\s+(ascii|binary)\s*;", head)
    if not fmt:
        die("ENCODE_FIELD_FORMAT_UNKNOWN")
    if fmt.group(1) == b"ascii":
        return ("\n" + "\n".join(f"{v:.16g}" for v in values) + "\n").encode("ascii")
    a = re.search(rb'arch\s+"([^"]+)"', head)
    if not a:
        die("ENCODE_BINARY_FIELD_ARCH_MISSING")
    arch = a.group(1).decode("ascii")
    endian = ">" if "MSB" in arch else "<" if "LSB" in arch else None
    code = "d" if "scalar=64" in arch else "f" if "scalar=32" in arch else None
    if endian is None or code is None:
        die("ENCODE_BINARY_FIELD_UNSUPPORTED_ARCH " + arch)
    return struct.pack(endian + str(len(values)) + code, *values)

def neighbours_and_faces(poly):
    owner = read_labels(poly / "owner")
    neighbour = read_labels(poly / "neighbour")
    if len(owner) <= len(neighbour) or max(owner) < CELL:
        die("MESH_OWNER_NEIGHBOUR_INVALID")
    graph = {}
    for a, b in zip(owner, neighbour):
        graph.setdefault(a, []).append(b)
        graph.setdefault(b, []).append(a)
    incident = [(i, neighbour[i]) for i, a in enumerate(owner[:len(neighbour)]) if a == CELL]
    incident += [(i, owner[i]) for i, b in enumerate(neighbour) if b == CELL]
    if {x for _, x in incident} != EXPECTED_NEIGHBOURS or {i for i, _ in incident} != EXPECTED_FACES:
        die("CELL3535_LOCAL_TOPOLOGY_CHANGED_DO_NOT_PATCH")
    return owner, neighbour, graph

def plan_modifications(poly, field, gain, rings):
    if not 0.5 <= gain <= 1.5 or not 4 <= rings <= 16:
        die("MODIFICATION_OUTSIDE_CONSERVATIVE_BOUNDS")
    owner, nbr, graph = neighbours_and_faces(poly)
    data, start, end, vals = field_values(field)
    if len(vals) != len(nbr):
        die("REFERENCE_FIELD_FACE_COUNT_MISMATCH")
    dist = {CELL: 0}
    q = deque([CELL])
    while q:
        x = q.popleft()
        if dist[x] >= rings:
            continue
        for y in graph.get(x, []):
            if y not in dist:
                dist[y] = dist[x] + 1
                q.append(y)
    new_vals = vals.copy()
    changed = 0
    for face, (a, b) in enumerate(zip(owner, nbr)):
        near = min(dist.get(a, rings+1), dist.get(b, rings+1))
        if near >= rings:
            continue
        # C1-like spatial falloff within the local mesh graph. No hard edge.
        qx = 1.0 - near / rings
        weight = qx*qx*(3.0 - 2.0*qx)
        new_vals[face] *= (1.0 + (gain - 1.0)*weight)
        if new_vals[face] <= 0:
            die("NON_POSITIVE_DIFFUSIVITY_PRODUCED")
        if abs(new_vals[face] - vals[face]) > 1e-12:
            changed += 1
    if changed < 6 or changed > 15000:
        die("UNEXPECTED_NUMBER_OF_LOCAL_MODIFIED_FACES " + str(changed))
    return data, start, end, vals, new_vals, {
        "local_rank": RANK, "local_cell": CELL, "gain": gain,
        "topological_radius": rings, "changed_internal_faces": changed,
        "affected_cells": len(dist),
        "before_min": min(vals), "before_max": max(vals),
        "after_min": min(new_vals), "after_max": max(new_vals),
        "incident_face_values_before": {str(i): vals[i] for i in EXPECTED_FACES},
        "incident_face_values_after": {str(i): new_vals[i] for i in EXPECTED_FACES},
    }

def patch_private_stage(fluid, gain, rings):
    path = fluid / "processor5/constant/motionReferenceDiffusivity"
    poly = fluid / "processor5/constant/polyMesh"
    if not path.is_file() or not poly.is_dir():
        die("FRESH_STAGE_FIELD_OR_MESH_MISSING")
    before_sha = sha(path)
    data, start, end, vals, new_vals, summary = plan_modifications(poly, path, gain, rings)
    patched = data[:start] + encode_field_payload(data, new_vals) + data[end:]
    tmp = path.with_name(path.name + ".repair96764.tmp")
    if tmp.exists():
        die("STALE_TEMP_FILE_REQUIRES_INVESTIGATION")
    with tmp.open("xb") as f:
        f.write(patched)
        f.flush()
        os.fsync(f.fileno())
    # Sanity validate the constructed field before replacing the private copy.
    _, _, _, vals2 = field_values(tmp)
    if len(vals2) != len(vals) or any(not math.isfinite(v) or v <= 0 for v in vals2):
        die("PRIVATE_FIELD_REWRITE_VALIDATION_FAILED")
    os.replace(tmp, path)
    summary.update({"original_sha256": before_sha, "modified_sha256": sha(path)})
    meta = fluid.parent / "LOCAL_ALE_REPAIR96764.json"
    dump(meta, summary)
    return summary

def preflight():
    p, a, src, fail, local = source_paths()
    checks = {}
    for path in (p, src, fail, a / "resume-cycles.py", a / "lib/libseagrass558RampDiffusivity.so"):
        checks[str(path)] = path.exists()
    if not all(checks.values()):
        die("PREFLIGHT_MISSING_REQUIRED_FILES " + json.dumps(checks))
    if sha(a / "lib/libseagrass558RampDiffusivity.so") != EXPECTED_LIB_SHA:
        die("PINNED_ALE_LIBRARY_CHANGED")
    for i in range(8):
        d = src / f"fluid/processor{i}/0.5635"
        for fname in ("U", "p", "phi", "pointDisplacement", "polyMesh/points"):
            if not (d / fname).is_file():
                die("INCOMPLETE_VERIFIED_SOURCE_RANK_" + str(i) + "_" + fname)
    for name in ("seagrass.rout", "kinematic_state.bin"):
        if not (src / "solid" / name).is_file():
            die("SOLID_BINARY_RESTART_MISSING " + name)
    # Read-only topology and field validation, no changes to original.
    summary = plan_modifications(
        src / "fluid/processor5/constant/polyMesh",
        src / "fluid/processor5/constant/motionReferenceDiffusivity",
        1.20, 8)[-1]
    report = {"status": "READONLY_PREFLIGHT_PASS",
              "source": str(src), "failure_evidence": str(fail),
              "known_last_verified_checkpoint": T0,
              "experimental_candidates": CANDIDATES,
              "source_unchanged": True, "local_face_plan": summary}
    print(json.dumps(report, indent=2, ensure_ascii=False), flush=True)
    return report

def import_driver(path):
    spec = importlib.util.spec_from_file_location("repair96764_existing_fsi_driver", path)
    if spec is None or spec.loader is None:
        die("EXISTING_DRIVER_IMPORT_FAILED")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for name in ("run_trial", "build_private_stage"):
        if not hasattr(mod, name):
            die("EXISTING_DRIVER_API_MISSING_" + name)
    return mod

def find_core(local):
    """Select the pinned core from the exact release, never recursive search."""
    path = local / "code-v4/segment.py"
    expected_blob = "15a219c75a7e417d707549c2a0e46bbebd761d19"
    if not path.is_file():
        die("PINNED_EXISTING_FSI_SEGMENT_CORE_NOT_FOUND " + str(path))
    data = path.read_bytes()
    actual_blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    if actual_blob != expected_blob:
        die("PINNED_FSI_SEGMENT_CORE_GIT_BLOB_MISMATCH " + str(path))
    return path

def snapshot_manifest(root):
    records = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            die("SYMLINK_FOUND_IN_SNAPSHOT_SOURCE " + str(path))
        if path.is_file():
            records.append([str(path.relative_to(root)), path.stat().st_size, sha(path)])
    return records

def backup_trial(name, root, local):
    dest = local / "backups" / name
    if dest.exists():
        manifest = local / "backups" / (name + ".manifest.json")
        if not manifest.is_file():
            die("EXISTING_BACKUP_UNVERIFIED_" + name)
        expected = json.loads(manifest.read_text())
        if snapshot_manifest(dest) != expected:
            die("EXISTING_BACKUP_HASH_MISMATCH_" + name)
        return
    tmp = local / "backups" / (name + ".INCOMPLETE")
    if tmp.exists():
        die("INCOMPLETE_BACKUP_REQUIRES_REVIEW_" + name)
    original = root / name
    if not original.is_dir():
        die("BACKUP_SOURCE_NOT_FOUND_" + name)
    before = snapshot_manifest(original)
    total = sum(x[1] for x in before)
    free = shutil.disk_usage(local).free
    if free < 2*total + 2_000_000_000:
        die("NOT_ENOUGH_BACKUP_FILESYSTEM_SPACE_" + name)
    shutil.copytree(original, tmp, symlinks=False)
    if before != snapshot_manifest(original) or before != snapshot_manifest(tmp):
        die("BACKUP_HASH_VERIFICATION_FAILED_" + name)
    tmp.rename(dest)
    dump(local/"backups"/(name+".manifest.json"), before)
    print("BACKUP_FULL_TRIAL_SHA256_PASS", name, len(before), total, flush=True)

def valid_stage(work, windows, t1):
    report = work / "DELTA_CONTINUATION_RESULT.json"
    native = work / "FSI_SEGMENT_RESULT.json"
    if not report.is_file() or not native.is_file():
        return False, "MISSING_NATIVE_FSI_RESULT"
    a = json.loads(report.read_text())
    b = json.loads(native.read_text())
    if "PASS" not in str(a.get("status")):
        return False, "CONTINUATION_NOT_PASS"
    if b.get("status") != "FSI_LONG_SEGMENT_PASS" or b.get("participant_exit_codes") != {"fluid": 0, "solid": 0}:
        return False, "NATIVE_OR_PARTICIPANT_NOT_PASS"
    if b.get("accepted_windows") != windows or abs(float(a.get("end_t", -1)) - t1) > 1e-8:
        return False, "WINDOWS_OR_FINAL_TIME_MISMATCH"
    if b.get("native_terminal_mesh",{}).get("status") != "PASS":
        return False, "TERMINAL_MESH_FAILED"
    fluid = work / "runs/hpcc-implicit-002/fluid"
    for i in range(8):
        d = fluid / f"processor{i}"
        if not any(x.is_dir() and re.fullmatch(r"\d+(?:\.\d+)?",x.name) and abs(float(x.name)-t1) < 1e-8 for x in d.iterdir()):
            return False, "CHECKPOINT_MISSING_RANK_"+str(i)
    solid = work / "runs/hpcc-implicit-002/solid"
    if not all((solid / x).is_file() for x in ("seagrass.rout","kinematic_state.bin")):
        return False, "STRUCTURAL_CHECKPOINT_MISSING"
    log = work / "fluid.log"
    if not log.is_file():
        return False, "MISSING_FLUID_GUARD_LOG"
    guards = re.findall(r"SEAGRASS_MESH_GUARD[^\n]*", log.read_text(errors="replace"))
    if len(guards) < windows:
        return False, "INCOMPLETE_MESH_GUARD_COVERAGE"
    for line in guards:
        for token in ("concave=1", "qualityFailed=1", "skewFailed=1",
                      "orthFailed=1", "tetFailed=1"):
            if token in line:
                return False, "MESH_GUARD_FAILURE_" + token
    return True, "VERIFIED_FSI_STAGE_PASS"

def run_job():
    job = os.environ.get("SLURM_JOB_ID","")
    if not re.fullmatch(r"\d+", job):
        die("SLURM_COMPUTE_ALLOCATION_REQUIRED")
    preflight()
    p, a, source, fault, local = source_paths()
    # The native resume-cycles driver accepts trial ROOT, not its
    # runs/hpcc-implicit-002 child. Stage2 already passes a trial root.
    source_trial = source.parent.parent
    if source_trial / "runs/hpcc-implicit-002" != source:
        die("SOURCE_WORK_ROOT_LAYOUT_INVALID")
    local.mkdir(exist_ok=True)
    (local/"backups").mkdir(exist_ok=True)
    # The original three-day 91543 source was separately backed up and
    # certified by its prior continuation; preserve it unchanged.
    for name in ("trial-96763", "trial-96764"):
        backup_trial(name, p, local)
    core = find_core(local)
    driver = import_driver(a/"resume-cycles.py")
    if hasattr(driver, "load_core"):
        try:
            loaded = driver.load_core(core)
            if not hasattr(loaded, "run"):
                die("INCOMPATIBLE_EXISTING_CORE_API")
        except Exception as exc:
            die("ORIGINAL_CORE_LOAD_FAILED "+str(exc))
    os.environ["FSI_DELTA_CORE_PATH"] = str(core)
    results = []
    best_time = T0
    for idx,(gain,rings) in enumerate(CANDIDATES,1):
        w1 = p / f"trial-{job}-repair96764-c{idx}-stage1"
        if w1.exists():
            die("TEST_OUTPUT_ALREADY_EXISTS " + str(w1))
        stage_summary = {}
        orig = driver.build_private_stage
        def patched_stage(*args,**kwargs):
            result = orig(*args,**kwargs)
            if not w1.joinpath("runs/hpcc-implicit-002/fluid").is_dir():
                die("PRIVATE_STAGE_DIR_NOT_CREATED")
            stage_summary.update(patch_private_stage(w1/"runs/hpcc-implicit-002/fluid",gain,rings))
            return result
        driver.build_private_stage = patched_stage
        try:
            driver.run_trial(Path.home()/"hpcc-fsi",source_trial,w1,FIRST_WINDOWS,core,96763,False)
            good1,why1 = valid_stage(w1,FIRST_WINDOWS,round(T0+FIRST_WINDOWS*DT,9))
        except BaseException as e:
            good1,why1 = False,"EXCEPTION_"+repr(e)
        finally:
            driver.build_private_stage = orig
        if good1:
            best_time=max(best_time,round(T0+FIRST_WINDOWS*DT,9))
        results.append({"variant":idx,"gain":gain,"rings":rings,
                        "stage":1,"work":str(w1),"pass":good1,
                        "reason":why1,"changed":stage_summary})
        print("CANDIDATE_96764_STAGE1",json.dumps(results[-1],ensure_ascii=False),flush=True)
        if not good1:
            continue
        # Stage 2 retains the modified reference field from stage 1;
        # do NOT apply the local multiplier a second time.
        w2 = p / f"trial-{job}-repair96764-c{idx}-stage2"
        if w2.exists():
            die("TEST_OUTPUT_ALREADY_EXISTS " + str(w2))
        try:
            driver.run_trial(Path.home()/"hpcc-fsi",w1,w2,SECOND_WINDOWS,core,int(job),False)
            good2,why2 = valid_stage(w2,SECOND_WINDOWS,
                round(T0+(FIRST_WINDOWS+SECOND_WINDOWS)*DT,9))
        except BaseException as e:
            good2,why2 = False,"EXCEPTION_"+repr(e)
        if good2:
            best_time = round(T0+(FIRST_WINDOWS+SECOND_WINDOWS)*DT,9)
        results.append({"variant":idx,"gain":gain,"rings":rings,
                        "stage":2,"work":str(w2),"pass":good2,"reason":why2})
        print("CANDIDATE_96764_STAGE2",json.dumps(results[-1],ensure_ascii=False),flush=True)
        if good2:
            break
    complete = bool(results and results[-1]["stage"] == 2 and results[-1]["pass"])
    result = {"job":int(job),"status":"REAL_FSI_REPLAY_TO_0P6035_PASS" if complete else
              "REPAIR_NOT_YET_VALIDATED", "best_verified_time_s":best_time,
              "source_physical_time_s":T0,"source_96763_untouched":True,
              "source_96764_untouched":True, "experiments":results,
              "next_production_submission_permitted":complete}
    dump(local/f"RESULT-{job}.json",result)
    print("FINAL_REPAIR96764_RESULT",json.dumps(result,ensure_ascii=False),flush=True)
    if not complete:
        raise SystemExit(3)
    queue_production(w2, job, best_time, local)


def queue_production(parent_work, parent_job, start_t, local):
    """Only after a real FSI repair replay passes: afterok-linked production."""
    p, a, src, fault, _ = source_paths()
    batch_dir = local / "batch"
    batch_dir.mkdir(exist_ok=True)
    record = {
        "type":"ALE96764_NATIVE_VERIFIED_PRODUCTION_CHAIN",
        "start_time_s":start_t, "all_afterok":True, "jobs":[]
    }
    previous_job = int(parent_job)
    previous_work = Path(parent_work)
    t = float(start_t)
    for k in range(1,6):
        windows = 640
        t1 = round(t + windows*DT, 9)
        config = local / f"production-{parent_job}-{k:02d}.json"
        if config.exists():
            die("PRODUCTION_CONFIG_ALREADY_EXISTS")
        cfg = {
            "source":str(previous_work), "source_job":previous_job,
            "start_t":t,"end_t":t1,"windows":windows,
            "source_hash_reference":EXPECTED_LIB_SHA
        }
        dump(config, cfg)
        batch = batch_dir / f"production-{parent_job}-{k:02d}.sbatch"
        if batch.exists():
            die("PRODUCTION_BATCH_ALREADY_EXISTS")
        script = Path(__file__).resolve(strict=True)
        img = Path.home()/"seagrass-fsi-ompi507-scotch-time.sif"
        body = f"""#!/bin/bash
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=12
#SBATCH --mem=24G
#SBATCH --time=3-00:00:00
#SBATCH --job-name=ale96764go
#SBATCH --output={local}/prod-%j.out
#SBATCH --error={local}/prod-%j.err
set -euo pipefail
module load gnu14/14.2.0 openmpi5/5.0.7
export SINGULARITYENV_SLURM_JOB_ID="$SLURM_JOB_ID"
export SINGULARITYENV_USER="$USER"
singularity exec --cleanenv -B /data/icto:/data/icto {shlex.quote(str(img))} \\
  /bin/bash --noprofile --norc -c '
set +eu
export WM_MPLIB=SYSTEMOPENMPI
source /usr/lib/openfoam/openfoam2512/etc/bashrc || exit 10
export PATH="/opt/precice-3.4.1-ompi5/bin:/opt/openmpi-5.0.7/bin:$PATH"
export LD_LIBRARY_PATH="/opt/scotch-compat/lib:/opt/precice-3.4.1-ompi5/lib:/opt/precice-3.4.1-ompi5/lib64:/opt/openmpi-5.0.7/lib:/opt/openmpi-5.0.7/lib64:$LD_LIBRARY_PATH"
export PKG_CONFIG_PATH="/opt/precice-3.4.1-ompi5/lib/pkgconfig:/opt/precice-3.4.1-ompi5/lib64/pkgconfig:$PKG_CONFIG_PATH"
export OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ROOT="$HOME/hpcc-fsi/seagrass-implicit-20261111"
export LD_LIBRARY_PATH="$ROOT/scripts/native/lib:$ROOT/fsi-explicit-test/mesh-guard/lib:$LD_LIBRARY_PATH"
set -eu
test "$WM_PROJECT_VERSION" = v2512
test "$(command -v mpirun)" = /opt/openmpi-5.0.7/bin/mpirun
exec python3 "$1" --run-one "$2"
' _ {shlex.quote(str(script))} {shlex.quote(str(config))}
"""
        batch.write_text(body)
        batch.chmod(0o500)
        proc = subprocess.run(["sbatch","--parsable",
            f"--dependency=afterok:{previous_job}",str(batch)],
            text=True,capture_output=True,check=True)
        jid = proc.stdout.strip().split(";")[0]
        if not re.fullmatch(r"\d+",jid):
            die("SLURM_BAD_PRODUCTION_JOB_ID "+proc.stdout)
        record["jobs"].append({
            "job":int(jid),"afterok":previous_job,
            "source":str(previous_work),"from_t":t,"to_t":t1,
            "windows":windows
        })
        previous_job=int(jid)
        previous_work=p/f"trial-{jid}-repair96764-prod"
        t=t1
        print("ALE96764_PRODUCTION_AFTEROK_QUEUED",jid,t1,flush=True)
    dump(local/f"CHAIN-{parent_job}.json",record)
    return record

def run_one(config_path):
    job = os.environ.get("SLURM_JOB_ID","")
    if not re.fullmatch(r"\d+",job):
        die("SLURM_JOB_ID_REQUIRED_FOR_PRODUCTION")
    preflight()
    p,a,orig,fault,local=source_paths()
    cfg=json.loads(Path(config_path).read_text())
    if cfg.get("source_hash_reference")!=EXPECTED_LIB_SHA:
        die("PINNED_PRODUCTION_LIBRARY_CONFIG_MISMATCH")
    source=Path(cfg["source"]).resolve(strict=True)
    if not source.is_relative_to(p):
        die("PRODUCTION_SOURCE_OUTSIDE_ISOLATED_DATA_ROOT")
    target=p/f"trial-{job}-repair96764-prod"
    if target.exists():
        die("PRODUCTION_DESTINATION_EXISTS")
    windows=int(cfg["windows"])
    if not 2 <= windows <= 1500:
        die("PRODUCTION_WINDOWS_OUTSIDE_VALIDATED_RANGE")
    driver=import_driver(a/"resume-cycles.py")
    core=find_core(local)
    os.environ["FSI_DELTA_CORE_PATH"]=str(core)
    try:
        driver.run_trial(Path.home()/"hpcc-fsi",source,target,windows,core,int(cfg["source_job"]),False)
        good,reason=valid_stage(target,windows,float(cfg["end_t"]))
    except BaseException as exc:
        good,reason=False,"EXCEPTION_"+repr(exc)
    result={"job":int(job),"source":str(source),"target":str(target),
            "start_t":cfg["start_t"],"end_t":cfg["end_t"],
            "pass":good,"reason":reason}
    dump(local/f"PRODUCTION-RESULT-{job}.json",result)
    print("ALE96764_PRODUCTION_SEGMENT",json.dumps(result,ensure_ascii=False),flush=True)
    if not good:
        raise SystemExit(3)

def submit():
    preflight()
    p, a, src, fault, local = source_paths()
    img = Path.home()/"seagrass-fsi-ompi507-scotch-time.sif"
    if not img.is_file():
        die("VERIFIED_CONTAINER_MISSING")
    core = find_core(local)
    # No running duplicate of this repair sequence.
    active = subprocess.run(["squeue","-h","-u",os.environ["USER"],"-n",
        "ale96764repair,ale96764go","-o","%i %T"],capture_output=True,text=True,check=True)
    if active.stdout.strip():
        die("ANOTHER_REPAIR_OR_PRODUCTION_JOB_ALREADY_ACTIVE "+active.stdout.strip())
    if any(local.glob("RESULT-*.json")) or any(local.glob("CHAIN-*.json")):
        die("EXISTING_REPAIR_RESULTS_OR_CHAIN_DO_NOT_DUPLICATE_SUBMISSION")
    local.mkdir(exist_ok=True)
    batch_dir = local / "batch"
    batch_dir.mkdir(exist_ok=True)
    (local / "backups").mkdir(exist_ok=True)
    script = Path(__file__).resolve(strict=True)
    batch = batch_dir / f"repair-{int(time.time())}.sbatch"
    # Use the original HPCC Open MPI 5.0.7, OpenFOAM v2512 and native library.
    body = f"""#!/bin/bash
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=12
#SBATCH --mem=24G
#SBATCH --time=3-00:00:00
#SBATCH --job-name=ale96764repair
#SBATCH --output={local}/logs-%j.out
#SBATCH --error={local}/logs-%j.err
set -euo pipefail
module load gnu14/14.2.0 openmpi5/5.0.7
export SINGULARITYENV_SLURM_JOB_ID="$SLURM_JOB_ID"
singularity exec --cleanenv -B /data/icto:/data/icto {shlex.quote(str(img))} \\
  /bin/bash --noprofile --norc -c '
set +eu
export WM_MPLIB=SYSTEMOPENMPI
source /usr/lib/openfoam/openfoam2512/etc/bashrc || exit 10
export PATH="/opt/precice-3.4.1-ompi5/bin:/opt/openmpi-5.0.7/bin:$PATH"
export LD_LIBRARY_PATH="/opt/scotch-compat/lib:/opt/precice-3.4.1-ompi5/lib:/opt/precice-3.4.1-ompi5/lib64:/opt/openmpi-5.0.7/lib:/opt/openmpi-5.0.7/lib64:$LD_LIBRARY_PATH"
export PKG_CONFIG_PATH="/opt/precice-3.4.1-ompi5/lib/pkgconfig:/opt/precice-3.4.1-ompi5/lib64/pkgconfig:$PKG_CONFIG_PATH"
export OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ROOT="$HOME/hpcc-fsi/seagrass-implicit-20261111"
export LD_LIBRARY_PATH="$ROOT/scripts/native/lib:$ROOT/fsi-explicit-test/mesh-guard/lib:$LD_LIBRARY_PATH"
set -eu
test "$WM_PROJECT_VERSION" = v2512
test "$(command -v mpirun)" = /opt/openmpi-5.0.7/bin/mpirun
exec python3 "$1" --run-job
' _ {shlex.quote(str(script))}
"""
    batch.write_text(body.replace('export SINGULARITYENV_SLURM_JOB_ID="$SLURM_JOB_ID"', 'export SINGULARITYENV_SLURM_JOB_ID="$SLURM_JOB_ID"\nexport SINGULARITYENV_USER="$USER"'))
    batch.chmod(0o500)
    result = subprocess.run(["sbatch","--parsable",str(batch)],
        text=True,capture_output=True,check=True)
    job=result.stdout.strip().split(";")[0]
    if not re.fullmatch(r"\d+",job):
        die("BAD_SLURM_JOB_ID "+result.stdout)
    print("ALE_96764_REPAIR_JOB_SUBMITTED",job,flush=True)
    print("LOG_DIR",local,flush=True)
    print("UNCHANGED_SOURCE",src,flush=True)

def status():
    _, _, _, _, local = source_paths()
    for p in sorted(local.glob("RESULT-*.json")):
        print(p, p.read_text()[:8000])
    q = subprocess.run(["squeue","-h","-u",os.environ["USER"],
       "-n","ale96764repair","-o","%i %T %R"],capture_output=True,text=True)
    print("SLURM_REPAIR_JOBS",q.stdout.strip() if q.returncode==0 else q.stderr)
    for p in sorted(local.glob("CHAIN-*.json")):
        print("QUEUED_CHAIN",p.read_text()[:12000])

def main():
    parser = argparse.ArgumentParser()
    actions=parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--preflight",action="store_true")
    actions.add_argument("--submit",action="store_true")
    actions.add_argument("--run-job",action="store_true",help=argparse.SUPPRESS)
    actions.add_argument("--status",action="store_true")
    actions.add_argument("--run-one",type=Path,help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.preflight: preflight()
    elif args.submit: submit()
    elif args.run_job: run_job()
    elif args.run_one is not None: run_one(args.run_one)
    else: status()

if __name__ == "__main__":
    main()
