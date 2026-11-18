#!/usr/bin/env python3
"""Full-byte protected copy of original three-hour job 91006 and restart lineage.

Run inside a backup-only Slurm allocation. Copies entire source directories
(including histories), creates per-file SHA-256+symlink manifests, verifies
copies, then writes a single atomic acceptance marker used by the compute job.
NO modification of source. NO sbatch, NO FSI solving.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

CASE_ITEMS={
    "three-hour-original-91006":"fsi-long-stage0-job91006",
    "restart-G0-92264":"crossjob-fix-20261116/delta-2window/trial-92264",
    "restart-G1-92479":"crossjob-fix-20261116/delta-continuation/trial-92479",
    "restart-G2-93674":"crossjob-fix-20261116/delta-continuation/trial-93674",
    "latest-restart-G3-93691":"crossjob-fix-20261116/delta-continuation/trial-93691",
}
REFERENCE_LOG="three-day-proven/long-job-91543/runs/hpcc-implicit-002/solid/precice-Solid-watchintegral-Interface-Integral.log"

def manifest(root):
    records=[]
    for d,dirs,files in os.walk(root,followlinks=False):
        dirs.sort();files.sort()
        for name in dirs+files:
            p=Path(d)/name
            rel=p.relative_to(root).as_posix()
            if p.is_symlink():
                records.append((rel,"link",os.readlink(p)))
            elif p.is_file():
                h=hashlib.sha256()
                with p.open("rb") as inp:
                    for chunk in iter(lambda: inp.read(8*1024*1024),b""):
                        h.update(chunk)
                records.append((rel,"file",str(p.stat().st_size),h.hexdigest()))
            elif p.is_dir():
                records.append((rel,"dir"))
            else:
                raise RuntimeError(f"Unexpected special file: {p}")
    return records

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--base",type=Path,required=True)
    p.add_argument("--backup-root",type=Path,required=True)
    args=p.parse_args()
    base=args.base.expanduser().resolve(strict=True)
    backup_root=args.backup_root.expanduser().resolve()
    destination=backup_root/"fsi-three-hour-and-restart-lineage-20261119"
    staging=backup_root/"fsi-three-hour-and-restart-lineage-20261119.INCOMPLETE"
    for place in (destination,staging):
        if place.exists():raise RuntimeError(f"BACKUP_DESTINATION_ALREADY_EXISTS: {place}")
    if backup_root==base or backup_root.is_relative_to(base):
        raise RuntimeError("BACKUP_MUST_BE_OUTSIDE_HPCC_FSI_SOURCE_TREE")
    sources={}
    for label,rel in CASE_ITEMS.items():
        src=base/rel
        if not src.is_dir():raise RuntimeError(f"MISSING_ORIGINAL_SOURCE_{label}: {src}")
        sources[label]=src
    ref=base/REFERENCE_LOG
    if not ref.is_file():raise RuntimeError("MISSING_CONTINUOUS_REFERENCE_LOG")
    if not (sources["latest-restart-G3-93691"]/"DELTA_CONTINUATION_RESULT.json").is_file():
        raise RuntimeError("G3_ACCEPTED_RESULT_MISSING")
    report=json.loads((sources["latest-restart-G3-93691"]/"DELTA_CONTINUATION_RESULT.json").read_text())
    if report.get("status")!="G3_PILOT_20_WINDOW_PASS_NOT_PRODUCTION" or report.get("original_strict_1pct_science_pass") is not True:
        raise RuntimeError("G3_NATIVE_AND_STRICT_SCIENCE_SOURCE_NOT_PROVEN")
    backup_root.mkdir(parents=True,exist_ok=True)
    total=sum(sum(x.stat().st_size for x in src.rglob("*") if x.is_file() and not x.is_symlink())
              for src in sources.values())+ref.stat().st_size
    free=shutil.disk_usage(backup_root).free
    print("BACKUP_TOTAL_INPUT_BYTES",total,flush=True)
    print("BACKUP_FILESYSTEM_FREE_BYTES",free,flush=True)
    if free < int(total*1.15)+2_000_000_000:
        raise RuntimeError("BACKUP_INSUFFICIENT_FREE_SPACE: need 115 percent of source plus 2 GB")
    staging.mkdir()
    info={"status":"INCOMPLETE","sources":{},"copy_started_unix":time.time(),
          "backup_root":str(destination),"input_bytes":total}
    for label,src in sources.items():
        target=staging/label
        print("BACKUP_COPY_START",label,str(src),flush=True)
        shutil.copytree(src,target,symlinks=True,copy_function=shutil.copy2)
        original=manifest(src)
        copied=manifest(target)
        if original!=copied:
            raise RuntimeError(f"BACKUP_MANIFEST_MISMATCH_{label}")
        (staging/f"{label}.sha256-manifest.json").write_text(json.dumps(original,ensure_ascii=False)+"\n")
        info["sources"][label]={"original":str(src),"entries":len(original),
                                "full_sha256_manifest":f"{label}.sha256-manifest.json"}
        print("BACKUP_ALL_BYTES_SHA256_VERIFIED",label,"entries",len(original),flush=True)
    ref_target=staging/"continuous-91543-watchintegral.log"
    shutil.copy2(ref,ref_target)
    # The continuous reference job may still append to its live log; only
    # verify the copy as a self-contained snapshot; do not mutate that source.
    h=hashlib.sha256(ref_target.read_bytes()).hexdigest()
    info["reference_log_snapshot_sha256"]=h
    info["completed_unix"]=time.time()
    info["status"]="BACKUP_COMPLETE_SHA256_VERIFIED"
    (staging/"BACKUP_COMPLETE.json").write_text(json.dumps(info,indent=2,ensure_ascii=False)+"\n")
    staging.rename(destination)
    print("BACKUP_COMPLETE_SHA256_VERIFIED",str(destination),flush=True)

if __name__=="__main__":
    main()
