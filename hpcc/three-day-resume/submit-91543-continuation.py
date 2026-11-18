#!/usr/bin/env python3
"""Queue FULL SHA-256 backup of original uninterrupted 91543, then continue it.

No fixed invented endpoint: inspect the actual 91543's eight-rank checkpoint.
Slurm afterok links backup -> physical continuation jobs. Any failed segment
blocks successors. The original 3-day source remains untouched. Default
extension 0.1 s of *physical time*, never replace the original.
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
import subprocess

DT=.000125
CASE="three-day-proven/long-job-91543"
ROOT_NAME="three-day-resume-20261119"
BACKUP_NAME="long-job-91543-FULL-BACKUP-20261119"

def fail(reason):raise RuntimeError(reason)

def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(4*1024*1024),b""):
            h.update(chunk)
    return h.hexdigest()

def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    if not spec or not spec.loader:fail(f"INVALID_PINNED_PYTHON_FILE {path}")
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def call(cmd):
    p=subprocess.run(cmd,capture_output=True,text=True)
    if p.returncode:
        fail(f"COMMAND_FAILED {cmd[0]} exit={p.returncode} stderr={p.stderr[-2000:]}")
    return p.stdout.strip()

def source_inactive():
    # sacct may be down; list ACTIVE jobs by user rather than querying a
    # completed job ID (which can yield "Invalid job id specified").
    user=os.environ.get("USER")
    if not user:fail("USER_ENV_MISSING")
    result=call(["squeue","-h","-u",user,"-o","%i|%T|%N"])
    for item in result.splitlines():
        if item.split("|",1)[0].strip()=="91543":
            fail("ORIGINAL_91543_STILL_ACTIVE_DO_NOT_BACKUP_MOVING_SOURCE: "+item)

def plan(start,accepted_count,extension):
    if not 0<extension<=.5:
        fail("EXTENSION_S_MUST_BE_POSITIVE_AND_AT_MOST_0P5_PER_BATCH")
    total=round(extension/DT)
    if abs(total*DT-extension)>1e-8:fail("EXTENSION_NOT_MULTIPLE_OF_DT")
    if total<2:fail("EXTENSION_TOO_SHORT")
    # Use full 72h as conservative estimated denominator; it may overestimate
    # seconds/window and thus choose shorter, safer production jobs.
    s_per=max(90.,72*3600/max(accepted_count-1,1))
    windows=max(16,min(1500,int(42*3600/s_per)))
    windows=max(16,windows//8*8)
    count=min(total,windows*12) # max 12 prequeued production jobs
    chunks=[]
    remaining=count
    while remaining>0:
        take=min(windows,remaining)
        if remaining-take==1:take-=1
        if take<2:fail("LAST_SINGLE_WINDOW_NOT_SCHEDULABLE")
        chunks.append(take);remaining-=take
    return chunks,round(start+sum(chunks)*DT,9),s_per

def batch(path,body):
    if path.exists():fail(f"REFUSING_TO_OVERWRITE_SLURM_BATCH {path}")
    path.write_text(body)
    path.chmod(0o500)

def schedule(path,name,stdout,stderr,cores,mem,dependency=None):
    cmd=["sbatch","--parsable","--partition=cpu","--nodes=1","--ntasks=1",
         f"--cpus-per-task={cores}",f"--mem={mem}","--time=3-00:00:00",
         f"--job-name={name}",f"--output={stdout}",f"--error={stderr}"]
    if dependency:cmd.append(f"--dependency=afterok:{dependency}")
    cmd.append(str(path))
    out=call(cmd)
    job=out.split(";",1)[0]
    if not re.fullmatch(r"[0-9]+",job):fail(f"INVALID_SLURM_JOB_ID {out}")
    return job

def verified_backup(p):
    if not p.is_file():fail("REQUIRED_FULL_91543_BACKUP_MARKER_MISSING")
    obj=json.loads(p.read_text())
    if obj.get("status")!="FULL_THREE_DAY_91543_BACKUP_SHA256_VERIFIED" or obj.get("original_job")!=91543:
        fail("FULL_91543_BACKUP_NOT_VERIFIED")
    if not (p.parent/"long-job-91543").is_dir():
        fail("BACKUP_COPY_DIRECTORY_MISSING")
    return obj

def compute_one(config):
    c=json.loads(config.read_text())
    if c.get("type")!="THREE_DAY_91543_DELTA_CONTINUATION":fail("BAD_PRODUCTION_CONFIG")
    verified_backup(Path(c["backup_marker"]))
    for item in ("driver","core","runner","inspector","patcher"):
        if sha(Path(c[item]))!=c[item+"_sha256"]:
            fail(f"PINNED_SOURCE_HASH_CHANGED_{item}")
    container=Path.home()/"seagrass-fsi-ompi507-scotch-time.sif"
    if not container.is_file():fail("VALIDATED_OMPI507_CONTAINER_MISSING")
    job=os.environ.get("SLURM_JOB_ID","")
    if not re.fullmatch(r"[0-9]+",job):fail("SLURM_JOB_ID_MISSING")
    base=Path.home()/"hpcc-fsi"
    dest=base/ROOT_NAME/"jobs"/f"trial-{job}"
    if dest.exists():fail("REFUSE_TO_OVERWRITE_EXISTING_FSI_RUN")
    env=os.environ.copy()
    env["FSI_91543_INSPECTOR"]=c["inspector"]
    env["FSI_ORIGINAL_DELTA_PATCH"]=c["patcher"]
    env.pop("BASH_ENV",None);env.pop("ENV",None)
    cmd=[
      "singularity","exec","--cleanenv",str(container),
      "/usr/bin/env","-u","BASH_ENV","-u","ENV",
      "/bin/bash","--noprofile","--norc",c["runner"],
      c["driver"],c["core"],c["parent"],job,str(dest),
      str(c["windows"]),str(c["parent_job"]),
      str(Path(c["backup_marker"]).parent),c["inspector"],c["patcher"]
    ]
    print("91543_CONTINUATION_NATIVE_START",json.dumps({
      "job":job,"previous_job":c["parent_job"],"source":c["parent"],
      "physical_time_start_s":c["start_s"],"physical_time_end_s":c["end_s"],
      "delta_protocol":"DisplacementDelta","original_91543_untouched":True,
      "backup_91543_SHA256_verified":True
    },ensure_ascii=False),flush=True)
    p=subprocess.run(cmd,env=env)
    if p.returncode:fail(f"NATIVE_OR_ACCEPTED_GUARD_FAILED_EXIT_{p.returncode}")
    report=json.loads((dest/"DELTA_CONTINUATION_RESULT.json").read_text())
    native=json.loads((dest/"FSI_SEGMENT_RESULT.json").read_text())
    if (report.get("status")!="91543_CONTINUATION_NATIVE_GUARDS_PASS" or
        native.get("status")!="FSI_LONG_SEGMENT_PASS" or
        native.get("participant_exit_codes")!={"fluid":0,"solid":0} or
        native.get("native_terminal_mesh",{}).get("status")!="PASS" or
        abs(float(report["end_t"])-float(c["end_s"]))>1e-9):
        fail("CONTINUATION_REPORT_OR_CHECKPOINT_FAILED")
    print("91543_CONTINUATION_STAGE_NATIVE_PASS",job,report["end_t"],flush=True)

def command(args):
    base=args.base.expanduser().resolve(strict=True)
    source_inactive()
    original=(base/CASE).resolve(strict=True)
    controller=Path(__file__).resolve()
    if controller.is_relative_to(base/ROOT_NAME):
        pass # frozen copies may live under $HOME/hpcc-fsi
    inspector=load(args.inspector,"fsi_long_job_inspector")
    d=inspector.inspect(base)
    actual=d["last_complete_MPI_fluid_time_s"]
    print("91543_ACTUAL_SAVED_FLUID_PHYSICAL_TIME_S",actual,flush=True)
    print("91543_LAST_SOLID_ACCEPTED_PHYSICAL_TIME_S",d["last_accepted_physical_time_s_from_origin_0p0025"],flush=True)
    if (not d["checkpoint_time_matches_latest_accepted_watch"]
       or not d["complete_fluid_MPI_time_aligned"]
       or actual is None):
        fail("91543_CHECKPOINT_NOT_ALIGNED_CANNOT_SAFELY_RESTART")
    driver=load(args.driver,"fsi_resume_91543_driver")
    core=driver.load_core(args.core)
    source,stamp,struct_step,_=driver.verified_source(original,core,base)
    if abs(stamp-actual)>1e-9:fail("DRIVER_AND_INSPECTOR_TIME_MISMATCH")
    chunks,end,estimate=plan(actual,d["accepted_watch_rows"],args.extend)
    print("THREE_DAY_91543_CONTINUATION_PLAN",json.dumps({
      "source_job":91543,"physical_checkpoint_s":stamp,
      "next_structural_restart_step":struct_step,
      "extension_requested_s":args.extend,
      "windows_planned":sum(chunks),"segments_planned":len(chunks),
      "next_endpoint_s":end,
      "estimate_seconds_per_window_conservative":estimate,
      "full_source_sha256_backup_required_first":True,
      "no_91543_future_scientific_reference_claim":True,
      "original_untouched":True,
      "afterok_only_start_if_previous_exits_zero":True
    },ensure_ascii=False),flush=True)
    if not args.submit:
        print("READONLY_INSPECT_NO_BACKUP_OR_PRODUCTION_JOB_SUBMITTED")
        return
    out=base/ROOT_NAME
    backup_root=args.backup_root.expanduser().resolve()
    final_backup=backup_root/BACKUP_NAME
    if out.exists() or final_backup.exists() or Path(str(final_backup)+".INCOMPLETE").exists():
        fail("EXISTING_PRODUCTION_OR_BACKUP_PATH_NO_DUPLICATE_SUBMISSION")
    running=call(["squeue","-h","-u",os.environ["USER"],"-n",
                  "fsi91543bak,fsi91543go","-o","%j|%T"])
    if running:fail("ANOTHER_91543_RESUME_OR_BACKUP_ACTIVE: "+running)
    out.mkdir()
    for folder in ("jobs","logs","batch","config"):(out/folder).mkdir()
    code={
        "driver":args.driver.resolve(strict=True),
        "core":args.core.resolve(strict=True),
        "runner":args.runner.resolve(strict=True),
        "inspector":args.inspector.resolve(strict=True),
        "patcher":args.patcher.resolve(strict=True)
    }
    backup_b=out/"batch/backup-91543.sh"
    backup_cmd=(
      "#!/usr/bin/env bash\nset -euo pipefail\n"
      f"python3 {shlex.quote(str(args.backup_script.resolve(strict=True)))}"
      f" --base {shlex.quote(str(base))}"
      f" --backup-root {shlex.quote(str(backup_root))}\n")
    batch(backup_b,backup_cmd)
    backup_id=schedule(backup_b,"fsi91543bak",out/"logs/backup-%j.out",
                       out/"logs/backup-%j.err",2,"16G")
    print("ORIGINAL_91543_FULL_SHA256_BACKUP_JOB_SUBMITTED",backup_id,flush=True)
    last=backup_id;parent=str(original);parent_job=91543;start=stamp
    record={"backup_job":int(backup_id),"backup_dir":str(final_backup),
            "source_job":91543,"source_physical_time_s":stamp,
            "status":"AFTEROK_CHAIN_QUEUED_BACKUP_FIRST",
            "jobs":[],"next_endpoint_s":end}
    for i,n in enumerate(chunks,1):
        stop=round(start+n*DT,9)
        cfg={"type":"THREE_DAY_91543_DELTA_CONTINUATION",
             "backup_marker":str(final_backup/"BACKUP_COMPLETE.json"),
             "parent":parent,"parent_job":int(parent_job),
             "start_s":start,"end_s":stop,"windows":n}
        for key,p in code.items():
            cfg[key]=str(p);cfg[key+"_sha256"]=sha(p)
        config=out/f"config/segment-{i:02d}.json"
        config.write_text(json.dumps(cfg,indent=2,ensure_ascii=False)+"\n")
        job_b=out/f"batch/segment-{i:02d}.sh"
        batch(job_b,("#!/usr/bin/env bash\nset -euo pipefail\n"
               f"python3 {shlex.quote(str(controller))} --run-one {shlex.quote(str(config))}\n"))
        jid=schedule(job_b,"fsi91543go",out/"logs/resume-%j.out",
                     out/"logs/resume-%j.err",12,"24G",last)
        print("91543_DELTA_CONTINUATION_AFTEROK_SUBMITTED",jid,
              "after",last,"from_s",start,"to_s",stop,"windows",n,flush=True)
        record["jobs"].append({"job":int(jid),"afterok":int(last),
            "parent_job":int(parent_job),"start_s":start,"end_s":stop,"windows":n})
        (out/"CHAIN_RECORD.json").write_text(json.dumps(record,indent=2,ensure_ascii=False)+"\n")
        parent=str(out/f"jobs/trial-{jid}");parent_job=int(jid)
        start=stop;last=jid
    print("91543_RESUME_QUEUED_BACKUP_FIRST_AND_DEPENDENT_FSI",flush=True)
    print("BACKUP_PARENT_JOB",backup_id,flush=True)
    print("LAST_QUEUED_FSI_JOB",last,"PLANNED_PHYSICAL_END",end,flush=True)
    print("DO_NOT_ASSUME_COMPLETE_UNTIL_BACKUP_AND_NATIVE_RESULTS_APPEAR",flush=True)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--base",type=Path,default=Path.home()/"hpcc-fsi")
    p.add_argument("--backup-root",type=Path,default=Path.home()/"hpcc-fsi-backups")
    p.add_argument("--driver",type=Path)
    p.add_argument("--core",type=Path)
    p.add_argument("--runner",type=Path)
    p.add_argument("--inspector",type=Path)
    p.add_argument("--patcher",type=Path)
    p.add_argument("--backup-script",type=Path)
    p.add_argument("--extend",type=float,default=.1)
    p.add_argument("--submit",action="store_true")
    p.add_argument("--run-one",type=Path)
    args=p.parse_args()
    if args.run_one is not None:
        compute_one(args.run_one)
        return
    if not all((args.driver,args.core,args.runner,args.inspector,args.patcher,args.backup_script)):
        p.error("Required: --driver --core --runner --inspector --patcher --backup-script")
    command(args)

if __name__=="__main__":
    main()
