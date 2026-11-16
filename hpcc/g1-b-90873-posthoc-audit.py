#!/usr/bin/env python3
"""Read-only post-hoc recovery of G1-B job 90873 after verifier column-index bug.

Does not start solvers, modify STATE.json, retroactively mark original job PASS,
or pretend the missing terminal native checkMesh was performed. Reuses the
updated live verifier for strict 10-window accounting and tip/load trajectories.
A PASS of this audit means the existing evidence supports a restarted trajectory
comparison; full native mesh and strict production restart remain unqualified.
"""
import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys


def load_module(path):
    spec=importlib.util.spec_from_file_location("g1b_updated_verifier",path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()


def tail(path):
    if not path.is_file():return []
    with path.open("rb") as f:
        f.seek(0,2)
        n=f.tell()
        f.seek(max(0,n-4*1024*1024))
        text=f.read().decode("utf-8","replace")
    return text.splitlines()


def read_json(path):
    return json.loads(path.read_text())


def audit(base,verifier,job_id):
    work=base/f"g1-b10-job-{job_id}"
    run=work/"runs/hpcc-implicit-002"
    solid=run/"solid"
    fluid=run/"fluid"
    baseline=base/verifier.EXPECTED_BASELINE
    state=read_json(work/"STATE.json")
    manifest=read_json(work/"G1_B_STAGE_EVIDENCE.json")
    failures=[]
    def require(check,label):
        if not check:failures.append(label)
    require(state.get("participant_exit_codes")=={"fluid":0,"solid":0},
            "fluid and solid must both exit 0")
    require(state.get("status")=="G1_B_FAILED","expected original job's verifier-failure state")
    require(state.get("failure")=="preCICE coupling iterations outside 1..50",
            "original failure not recognized as known iteration column bug")
    require(manifest.get("status")=="G1_B_ISOLATED_STAGED_NOT_RUN",
            "isolated stage provenance missing")
    require(manifest.get("original_90739_untouched") is True,
            "frozen-source isolation evidence missing")
    for name in ("seagrass.rin","seagrass.rout",
                 "kinematic_state.input.bin","kinematic_state.bin"):
        p=solid/name
        require(p.is_file() and p.stat().st_size>1024,
                f"missing or empty solid checkpoint: {name}")
    if (solid/"seagrass.rin").is_file():
        require(digest(solid/"seagrass.rin")==manifest.get("solid_restart_input_sha256"),
                "restart input checksum mismatch")
    if (solid/"kinematic_state.input.bin").is_file():
        require(digest(solid/"kinematic_state.input.bin")==manifest.get("solid_state_input_sha256"),
                "kinematic state input checksum mismatch")
    try:
        rows=verifier.check_iterations(solid/"precice-Solid-iterations.log")
        counts=[row[2] for row in rows]
    except Exception as ex:
        failures.append(f"real per-window iteration validation: {ex}")
        rows=[]
        counts=[]
    try:
        trajectory=verifier.compare_trajectory(run,baseline)
    except Exception as ex:
        failures.append(f"tip and force full 10-window trajectory: {ex}")
        trajectory=None
    combined_log="\n".join(tail(work/"fluid.log"))
    solid_log="\n".join(tail(work/"solid.log"))
    guard_matches=re.findall(
        r"SEAGRASS_MESH_GUARD\s+time=([0-9.eE+-]+)\s+minVolume=([0-9.eE+-]+)"
        r"\s+concave=(\d+)\s+qualityFailed=(\d+)\s+skewFailed=(\d+)"
        r"\s+orthFailed=(\d+)\s+tetFailed=(\d+)",combined_log)
    terminal=None
    for record in reversed(guard_matches):
        vals=[float(record[0]),float(record[1])]+[int(x) for x in record[2:]]
        if math.isclose(vals[0],verifier.FINAL,abs_tol=1e-9):
            terminal={
                "physical_time_s":vals[0],
                "min_volume_m3":vals[1],
                "concave":vals[2],
                "quality_failed":vals[3],
                "skew_failed":vals[4],
                "orth_failed":vals[5],
                "tet_failed":vals[6],
            }
            break
    require(terminal is not None,"missing terminal original in-situ SEAGRASS_MESH_GUARD")
    if terminal:
        require(terminal["min_volume_m3"]>0,"nonpositive cell volume at final guard")
        require(not any(terminal[k] for k in (
            "concave","quality_failed","skew_failed","orth_failed","tet_failed")),
            "in-situ terminal ALE guard detected a failed mesh")
    require("restart file seagrass.rin" in solid_log
            and "has been opened for reading" in solid_log,
            "CalculiX .rin actually opened")
    if re.search(r"FOAM FATAL|\bSegmentation fault\b",combined_log):
        failures.append("Fluid solver fatal marker")
    if re.search(r"\bSegmentation fault\b|\*ERROR",solid_log):
        failures.append("Solid solver fatal marker")
    require(baseline.is_dir(),"87186 reference missing")
    info={
        "schema":"g1b-posthoc-audit-v1",
        "created_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
        "job":job_id,
        "original_state_unchanged":state.get("status"),
        "original_failure":state.get("failure"),
        "stage_integrity":manifest.get("status"),
        "participant_exit_codes":state.get("participant_exit_codes"),
        "resumed_windows_verified":len(rows),
        "resumed_iteration_counts":counts,
        "solid_restarted_file_opened":("restart file seagrass.rin" in solid_log),
        "in_situ_terminal_ale_guard":terminal,
        "interface_trajectory_comparison":trajectory,
        "native_terminal_parallel_checkMesh":"NOT_RUN_POSTHOC",
        "strict_g1b_restart_qualification":"NOT_YET_CONFIRMED",
        "errors":failures,
        "status":"G1_B_90873_POSTHOC_EVIDENCE_PASS_NATIVE_MESH_UNVERIFIED"
            if not failures else "G1_B_90873_POSTHOC_EVIDENCE_FAIL",
    }
    return info


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base",type=Path,default=Path.home()/"hpcc-fsi")
    p.add_argument("--verifier",type=Path)
    p.add_argument("--job",type=int,default=90873)
    p.add_argument("--out",type=Path)
    args=p.parse_args()
    base=args.base.expanduser().resolve(strict=True)
    verifier=load_module((args.verifier or base/"g1-b-real-restart.py").expanduser().resolve(strict=True))
    result=audit(base,verifier,args.job)
    print("POSTHOC_STATUS",result["status"])
    print("ORIGINAL_STATE_UNCHANGED",result["original_state_unchanged"])
    print("PARTICIPANT_EXITS",result["participant_exit_codes"])
    print("VALIDATED_RESUME_WINDOWS",result["resumed_windows_verified"])
    print("WINDOW_ITERATIONS",result["resumed_iteration_counts"])
    print("TERMINAL_IN_SITU_ALE_GUARD",json.dumps(result["in_situ_terminal_ale_guard"]))
    for name,vals in (result["interface_trajectory_comparison"] or {}).items():
        print("TRAJECTORY",name,"MODE",vals["time_mode"],
              "MAX_ERROR",max(v["difference_norm"] for v in vals["windows"]))
    for error in result["errors"]:print("FAILED_EVIDENCE",error)
    print("NATIVE_TERMINAL_CHECKMESH=NOT_RUN")
    if args.out:
        out=args.out.expanduser().resolve()
        if out.suffix!=".json" or not out.is_relative_to(base):
            raise SystemExit("Output must be a JSON under hpcc-fsi")
        for protected in ("g1-b10-job-90873",
                          "g1-rout10-job-90739",
                          "performance-full160-job-89038",
                          "implicit-pilot-002-8mpi-timefix-87186"):
            if out.is_relative_to(base/protected):
                raise SystemExit("Refusing to alter source or run folders")
        with out.open("x") as f:
            json.dump(result,f,indent=2,ensure_ascii=False)
            f.write("\n")
        print("AUDIT_REPORT",out)
    if result["errors"]:
        raise SystemExit(2)


if __name__=="__main__":
    main()
