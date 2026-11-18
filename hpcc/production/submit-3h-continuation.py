#!/usr/bin/env python3
"""Schedule full backup FIRST and uninterrupted Slurm afterok FSI continuation.

Login-node controller: no physics running on login node. Each source for next
job is the preceding accepted checkpoint. Failed backups/science/native jobs
never release their dependent successors. No writes to historical sources.
Default target is the LAST requested time supported by continuous 91543
science reference, capped at 0.1625 s. Never fabricate reference beyond it.
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time

DT=0.000125
ORIGIN=0.0025
START=0.038
SEED_JOB=93691
WATCH="precice-Solid-watchintegral-Interface-Integral.log"
SOURCE_REL="crossjob-fix-20261116/delta-continuation/trial-93691"
ROOT_REL="production-resume-20261119"
BACKUP_NAME="fsi-three-hour-and-restart-lineage-20261119"

def failure(msg):
    raise RuntimeError(msg)

def read(path):
    return json.loads(path.read_text())

def digest(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def run(cmd,stdout=None):
    p=subprocess.run(cmd,capture_output=True,text=True,check=False)
    if p.returncode:
        failure(f"COMMAND_FAILED {cmd[0]} code={p.returncode} stderr={p.stderr[-1500:]}")
    return p.stdout.strip()

def load_driver(path):
    spec=importlib.util.spec_from_file_location("fsi_real_production_driver",path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def reference_plan(base,source_end,target,per_window):
    ref=base/"three-day-proven/long-job-91543/runs/hpcc-implicit-002/solid"/WATCH
    if not ref.is_file():failure("CONTINUOUS_91543_REFERENCE_MISSING")
    rows=set()
    for line in ref.read_text(errors="replace").splitlines():
        parts=line.split()
        if len(parts)<7:continue
        try:values=[float(q) for q in parts[:7]]
        except ValueError:continue
        if all(math.isfinite(v) for v in values):
            rows.add(round(values[0],9))
    start_index=round(source_end/DT)
    target_index=round(target/DT)
    if not math.isclose(start_index*DT,source_end,abs_tol=1e-9):
        failure("SOURCE_NOT_EXACT_TIME_STEP")
    if not math.isclose(target_index*DT,target,abs_tol=1e-9):
        failure("TARGET_NOT_EXACT_TIME_STEP")
    base_reference_time=round(source_end-ORIGIN,9)
    if base_reference_time not in rows:failure("REFERENCE_SOURCE_TIME_MISSING")
    count=0
    for index in range(start_index+1,target_index+1):
        rel=round(index*DT-ORIGIN,9)
        if rel not in rows:break
        count+=1
    if count<2:failure("REFERENCE_MISSING_AT_LEAST_TWO_FUTURE_WINDOWS")
    # Adapt MAXIMUM chunk length to the measured 20-window HPC rate.
    # 3h Slurm request and 2h50 native timeout; target <= 2h30 solver.
    max_chunk=next((n for n in (80,64,48,40,32,24,16,8,4,2)
                    if n*per_window<=9000),None)
    if max_chunk is None:
        failure("REFERENCE_JOB_MEASURED_TOO_SLOW_FOR_SAFE_3H_SEGMENT")
    chunks=[]
    remain=count
    while remain:
        n=min(remain,max_chunk)
        if remain-n==1:n-=1
        if n<2:failure("UNSCHEDULABLE_FINAL_SINGLE_WINDOW")
        chunks.append(n)
        remain-=n
    if len(chunks)>40:failure("TOO_MANY_AUTO_QUEUED_JOBS")
    return chunks,source_end+count*DT,per_window,max_chunk

def checked_source(base,driver,core):
    source=(base/SOURCE_REL).resolve(strict=True)
    native=read(source/"FSI_SEGMENT_RESULT.json")
    marker=read(source/"DELTA_CONTINUATION_RESULT.json")
    if native.get("status")!="FSI_LONG_SEGMENT_PASS" or marker.get("status")!="G3_PILOT_20_WINDOW_PASS_NOT_PRODUCTION":
        failure("SOURCE_93691_HAS_NO_COMPLETE_NATIVE_AND_G3_REPORT")
    if marker.get("original_strict_1pct_science_pass") is not True:
        failure("SOURCE_93691_SCIENTIFIC_GATE_NOT_PASSED")
    _,when,step,_=driver.verified_source(source,core,base)
    if not math.isclose(when,START,abs_tol=1e-9) or step!=7:
        failure("SOURCE_93691_WRONG_TIME_OR_SOLID_RESTART_STEP")
    return source,native

def write_executable(path,body):
    if path.exists():failure(f"REFUSING_TO_OVERWRITE_EXISTING_JOB_SCRIPT {path}")
    path.write_text(body)
    path.chmod(0o500)

def sbatch(batch,jobname,time_limit,cpus,mem,output,error,dep=None):
    cmd=["sbatch","--parsable","--partition=cpu","--nodes=1","--ntasks=1",
         f"--cpus-per-task={cpus}",f"--mem={mem}",f"--time={time_limit}",
         f"--job-name={jobname}",f"--output={output}",f"--error={error}"]
    if dep:cmd.append(f"--dependency=afterok:{dep}")
    cmd.append(str(batch))
    out=run(cmd)
    job=out.split(";",1)[0].strip()
    if not re.fullmatch(r"[0-9]+",job):
        failure(f"INVALID_SBATCH_JOB_ID {out}")
    return job

def verified_backup(marker):
    if not marker.is_file():failure("BACKUP_COMPLETE_MARKER_MISSING")
    obj=read(marker)
    if obj.get("status")!="BACKUP_COMPLETE_SHA256_VERIFIED":
        failure("BACKUP_MARKER_NOT_COMPLETE")
    if len(obj.get("sources",{}))!=5:
        failure("BACKUP_MARKER_FIVE_FULL_SOURCE_DIRECTORIES_REQUIRED")
    return obj

def execute_one(config):
    cfg=read(config)
    if cfg.get("protocol")!="FULL_BACKUP_THEN_STRICT_DELTA_PRODUCTION":
        failure("PRODUCTION_JOB_CONFIG_INVALID")
    backup=Path(cfg["backup_marker"])
    verified_backup(backup)
    for key in ("driver","core","runner"):
        name=Path(cfg[key]).resolve(strict=True)
        if digest(name)!=cfg[key+"_sha256"]:
            failure(f"PINNED_PRODUCTION_CODE_SHA256_CHANGED_{key}")
    container=Path.home()/"seagrass-fsi-ompi507-scotch-time.sif"
    if not container.is_file():failure("VALIDATED_OMPI507_CONTAINER_MISSING")
    parent=Path(cfg["parent"])
    if not parent.is_dir():failure("SCHEDULED_PARENT_CHECKPOINT_MISSING")
    job=os.environ.get("SLURM_JOB_ID","")
    if not re.fullmatch(r"[0-9]+",job):failure("COMPUTE_NODE_SLURM_ID_REQUIRED")
    base=Path.home()/"hpcc-fsi"
    work=base/ROOT_REL/"jobs"/f"trial-{job}"
    if work.exists():failure("PRODUCTION_WORK_FOLDER_ALREADY_EXISTS")
    command=[
      "singularity","exec","--cleanenv",str(container),
      "/usr/bin/env","-u","BASH_ENV","-u","ENV",
      "/bin/bash","--noprofile","--norc",
      cfg["runner"],cfg["driver"],cfg["core"],str(parent),
      job,str(work),str(cfg["windows"]),str(cfg["parent_job"]),
      str(backup.parent)]
    print("THREE_HOUR_CONTINUATION_START",json.dumps({
      "job":job,"parent_job":cfg["parent_job"],"windows":cfg["windows"],
      "parent":str(parent),"target_time_s":cfg["end_s"],
      "backup":str(backup.parent),"physics":"unchanged DisplacementDelta"
    }),flush=True)
    env=os.environ.copy()
    env.pop("BASH_ENV",None);env.pop("ENV",None)
    p=subprocess.run(command,env=env,check=False)
    if p.returncode:failure(f"PRODUCTION_NATIVE_OR_1PCT_SCIENCE_FAIL code={p.returncode}")
    final=read(work/"DELTA_CONTINUATION_RESULT.json")
    if final.get("status")!="LONG_CHAIN_SEGMENT_PASS" or final.get("production_approved") is not True:
        failure("PRODUCTION_FAILED_TO_GENERATE_STRICT_ACCEPTED_REPORT")
    if abs(float(final["end_t"])-float(cfg["end_s"]))>1e-9:
        failure("PRODUCTION_ACCEPTED_TIME_WRONG")
    print("THREE_HOUR_SEGMENT_NATIVE_AND_SCIENCE_PASS",job,final["end_t"],flush=True)

def plan_or_submit(args):
    base=args.base.expanduser().resolve(strict=True)
    output=base/ROOT_REL
    backup_root=args.backup_root.expanduser().resolve()
    backup_dest=backup_root/BACKUP_NAME
    backup_marker=backup_dest/"BACKUP_COMPLETE.json"
    driver_path=args.driver.expanduser().resolve(strict=True)
    core_path=args.core.expanduser().resolve(strict=True)
    runner_path=args.runner.expanduser().resolve(strict=True)
    backup_script=args.backup_script.expanduser().resolve(strict=True)
    driver=load_driver(driver_path)
    core=driver.load_core(core_path)
    seed,native=checked_source(base,driver,core)
    per=float(native.get("s_per_window",0))
    if not 1<=per<=1000:failure("G3_MEASURED_WALL_SECONDS_PER_WINDOW_ABSENT")
    requested=float(args.target)
    if requested<=START or requested>.1625:
        failure("TARGET_MUST_BE_AFTER_0P038_AND_NOT_BEYOND_91543_REFERENCE_0P1625")
    chunks,end,per,max_chunk=reference_plan(base,START,requested,per)
    print("3H_PRODUCTION_PREFLIGHT_PASS",json.dumps({
        "seed_job":SEED_JOB,"seed_time_s":START,"original_3h_job":91006,
        "native_G3_s_per_window":per,"max_chunk":max_chunk,
        "planned_segments":len(chunks),"planned_windows":sum(chunks),
        "planned_end_s":end,"requires_verified_full_backup":True,
        "production_physics":"DisplacementDelta unchanged",
        "no_reference_extrapolation":True,
        "children_start_only_after_previous_SUCCESS":True
    },ensure_ascii=False),flush=True)
    if not args.submit:
        print("READONLY_PREFLIGHT_NO_BACKUP_OR_COMPUTE_SUBMITTED")
        return
    if output.exists():
        failure(f"PRODUCTION_OUTPUT_ALREADY_EXISTS_NO_DUPLICATE_SUBMISSION {output}")
    if backup_dest.exists() or Path(str(backup_dest)+".INCOMPLETE").exists():
        failure("PREVIOUS_BACKUP_ALREADY_PRESENT_DO_NOT_RERUN_BLINDLY")
    # Do not schedule two simultaneous continuation chains.
    active=run(["squeue","-h","-u",os.environ["USER"],
                "-n","fsi-prod3h,fsi-backup3h","-o","%j:%T"])
    if active:failure("EXISTING_FSI_PRODUCTION_OR_BACKUP_JOB_ACTIVE "+active)
    output.mkdir(parents=True)
    batch_dir=output/"batch"
    cfg_dir=output/"config"
    log_dir=output/"logs"
    jobs_dir=output/"jobs"
    for d in (batch_dir,cfg_dir,log_dir,jobs_dir):d.mkdir()
    backup_batch=batch_dir/"backup-full-3h.sh"
    body=("#!/usr/bin/env bash\nset -euo pipefail\n"
          f"python3 {shlex.quote(str(backup_script))} --base {shlex.quote(str(base))}"
          f" --backup-root {shlex.quote(str(backup_root))}\n")
    write_executable(backup_batch,body.replace("\\\n","\n"))
    backup_id=sbatch(backup_batch,"fsi-backup3h","03:00:00",2,"8G",
                     log_dir/"backup-%j.out",log_dir/"backup-%j.err")
    print("FULL_BACKUP_JOB_SUBMITTED",backup_id,flush=True)
    parent=seed
    parent_job=str(SEED_JOB)
    last_id=backup_id
    start=START
    log={"status":"CHAIN_SUBMITTED_DEPENDENT_AFTEROK","backup_job":backup_id,
         "backup_root":str(backup_dest),"source_three_hour_original_job":91006,
         "seed_job":SEED_JOB,"seed_time":START,"science_reference_91543":True,
         "jobs":[],"planned_end_s":end,"target_s":requested,
         "full_original_91006_and_G0_to_G3_backup_required":True}
    # Every later job is queued with *both* strict sequential predecessor
    # and exact source trial-N, not a guessed future checkpoint.
    for index,window_count in enumerate(chunks,1):
        ending=start+window_count*DT
        config={
          "protocol":"FULL_BACKUP_THEN_STRICT_DELTA_PRODUCTION",
          "parent":str(parent),"parent_job":int(parent_job),
          "windows":window_count,"start_s":start,"end_s":ending,
          "backup_marker":str(backup_marker)}
        for key,path in (("driver",driver_path),("core",core_path),
                         ("runner",runner_path)):
            config[key]=str(path)
            config[key+"_sha256"]=digest(path)
        cfg=cfg_dir/f"segment-{index:02d}.json"
        cfg.write_text(json.dumps(config,indent=2,ensure_ascii=False)+"\n")
        batch=batch_dir/f"segment-{index:02d}.sh"
        command=(f"#!/usr/bin/env bash\nset -euo pipefail\n"
           f"python3 {shlex.quote(str(Path(__file__).resolve()))}"
           f" --run-one {shlex.quote(str(cfg))}\n")
        write_executable(batch,command.replace("\\\n","\n"))
        job=sbatch(batch,"fsi-prod3h","03:00:00",12,"24G",
                   log_dir/"production-%j.out",log_dir/"production-%j.err",
                   dep=last_id)
        print("THREE_HOUR_CONTINUATION_DEPENDENT_SUBMITTED",
              job,"afterok",last_id,"source",parent_job,
              "windows",window_count,"from",round(start,9),"to",round(ending,9),flush=True)
        log["jobs"].append({"id":int(job),"afterok":int(last_id),
            "parent_job":int(parent_job),"start_s":start,"end_s":ending,
            "windows":window_count,"config":str(cfg)})
        parent=jobs_dir/f"trial-{job}"
        parent_job=job
        last_id=job
        start=ending
        (output/"CHAIN_SUBMISSION_RECORD.json").write_text(
            json.dumps(log,indent=2,ensure_ascii=False)+"\n")
    print("ALL_3H_SEGMENTS_SCHEDULED_AFTER_FULL_BACKUP",
          "backup_job",backup_id,"final_job",last_id,"end_s",end,flush=True)
    print("BACKUP_MUST_COMPLETE_SHA256_BEFORE_FIRST_COMPUTE",str(backup_dest),flush=True)
    print("ON_ANY_SEGMENT_FAILURE_ALL_LATER_AFTEROK_SEGMENTS_ARE_BLOCKED",flush=True)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--base",type=Path,default=Path.home()/"hpcc-fsi")
    p.add_argument("--driver",type=Path)
    p.add_argument("--core",type=Path)
    p.add_argument("--runner",type=Path)
    p.add_argument("--backup-script",type=Path)
    p.add_argument("--backup-root",type=Path,default=Path.home()/"hpcc-fsi-backups")
    p.add_argument("--target",type=float,default=.1625)
    p.add_argument("--submit",action="store_true")
    p.add_argument("--run-one",type=Path)
    args=p.parse_args()
    if args.run_one is not None:
        execute_one(args.run_one)
        return
    if not all((args.driver,args.core,args.runner,args.backup_script)):
        p.error("--driver --core --runner --backup-script required")
    plan_or_submit(args)

if __name__=="__main__":
    main()
