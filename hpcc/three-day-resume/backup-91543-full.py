#!/usr/bin/env python3
"""Complete, manifest-verified copy of entire three-day job 91543.

Copy ALL source job files; verify SHA-256 before and after copy to detect
mutation; do not touch original; never claim backup on partial copy.
Output is a copy in a separate user-chosen backup root and a final manifest.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

ORIGINAL="three-day-proven/long-job-91543"
BACKUP_DIR="long-job-91543-FULL-BACKUP-20261119"

def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as fd:
        for block in iter(lambda:fd.read(16*1024*1024),b""):
            h.update(block)
    return h.hexdigest()

def scan(root):
    entries=[]
    for parent,dirs,files in os.walk(root,followlinks=False):
        dirs.sort();files.sort()
        for name in sorted(dirs+files):
            p=Path(parent)/name
            rel=p.relative_to(root).as_posix()
            if p.is_symlink():
                target=os.readlink(p)
                if not p.resolve().is_relative_to(root.resolve()):
                    raise RuntimeError(f"EXTERNAL_SYMLINK_REQUIRES_SEPARATE_BACKUP: {p} -> {target}")
                entries.append([rel,"symlink",target])
            elif p.is_dir():entries.append([rel,"directory"])
            elif p.is_file():entries.append([rel,"file",p.stat().st_size,sha(p)])
            else:raise RuntimeError(f"UNSUPPORTED_SOURCE_ITEM {p}")
    return entries

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--base",type=Path,default=Path.home()/"hpcc-fsi")
    p.add_argument("--backup-root",type=Path,default=Path.home()/"hpcc-fsi-backups")
    args=p.parse_args()
    base=args.base.expanduser().resolve(strict=True)
    backup_root=args.backup_root.expanduser().resolve()
    source=(base/ORIGINAL).resolve(strict=True)
    if backup_root.is_relative_to(base) or backup_root==source or backup_root.is_relative_to(source):
        raise RuntimeError("BACKUP_ROOT_MUST_NOT_BE_INSIDE_SOURCE_PROJECT")
    final=backup_root/BACKUP_DIR
    tmp=backup_root/(BACKUP_DIR+".INCOMPLETE")
    if final.exists() or tmp.exists():
        raise RuntimeError("EXISTING_FULL_BACKUP_OR_INCOMPLETE_REQUIRES_MANUAL_RECONCILIATION")
    print("FULL_BACKUP_91543_SOURCE",source,flush=True)
    print("FULL_BACKUP_91543_DESTINATION",final,flush=True)
    print("PRE_BACKUP_SOURCE_SHA256_MANIFEST_STARTED",flush=True)
    before=scan(source)
    total=sum(r[2] for r in before if r[1]=="file")
    backup_root.mkdir(parents=True,exist_ok=True)
    free=shutil.disk_usage(backup_root).free
    print("FULL_SOURCE_BYTES",total,"DESTINATION_FREE_BYTES",free,flush=True)
    if free<total+max(2_000_000_000,total//10):
        raise RuntimeError("BACKUP_STORAGE_INSUFFICIENT; choose a larger separate storage mount")
    tmp.mkdir()
    try:
        print("BACKUP_COPY_ALL_FILES_START",flush=True)
        shutil.copytree(source,tmp/"long-job-91543",symlinks=True,copy_function=shutil.copy2)
        print("BACKUP_SHA256_VERIFY_BOTH_SOURCE_AND_COPY_START",flush=True)
        after_source=scan(source)
        after_copy=scan(tmp/"long-job-91543")
        if before!=after_source:
            raise RuntimeError("SOURCE_CHANGED_DURING_BACKUP; cannot certify")
        if before!=after_copy:
            raise RuntimeError("BACKUP_BYTE_FOR_BYTE_SHA256_MISMATCH")
        evidence={
          "status":"FULL_THREE_DAY_91543_BACKUP_SHA256_VERIFIED",
          "original_job":91543,"source":str(source),"backup":str(final),
          "file_and_directory_entries":len(before),"source_file_bytes":total,
          "manifest_SHA256":hashlib.sha256(json.dumps(before).encode()).hexdigest(),
          "completed_unix":time.time(),"original_modified":False
        }
        (tmp/"full-source-sha256-manifest.json").write_text(json.dumps(before,ensure_ascii=False)+"\n")
        (tmp/"BACKUP_COMPLETE.json").write_text(json.dumps(evidence,indent=2,ensure_ascii=False)+"\n")
        tmp.rename(final)
        print("FULL_THREE_DAY_91543_BACKUP_SHA256_VERIFIED",final,flush=True)
    except BaseException:
        print("FULL_BACKUP_FAILED_INCOMPLETE_PRESERVED_DO_NOT_LAUNCH_FSI",tmp,flush=True)
        raise

if __name__=="__main__":
    main()
