#!/usr/bin/env python3
"""One sign-directed native coupled ALE-FSI continuation: C2 plus -2% at bed cell2758.

This is ONE EXPERIMENTAL, unvalidated improvement. Based on independent
native mesh diagnostics: C2 passes first step but develops cell2758 concavity
at t=0.580750; C2 plus +100% bed diffusivity fails immediately at 0.563625.
Test a small -2% bed-local change to the C2 reference coefficient, preserving
C2's successful +Y zone and both bed wall vertices. Nonlinear response is
not proven from this directional hypothesis. Never changes any original run,
bed vertices, checkpoint points, mesh topology, guard or physical solver.
Only after native coupled FSI validates BOTH 0.5815 and 0.6035, queue
five pre-existing strict-validated, afterok-dependent 640-window production
segments to 1.0035 seconds. Never launch them if the pilot fails.
"""
from __future__ import annotations
import argparse
from collections import deque
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

NAME="ale-c2-minus2percent-20261122-v1"
T0=0.5635
DT=0.000125
WINDOWS1=144
WINDOWS2=176
POS_CENTER=3535
POS_GAIN=0.85
POS_RINGS=8
NEG_CENTER=2758
NEG_GAIN=0.98
NEG_RINGS=6
EXPECTED_NEG_FACES={9317,9318,9306,9309,9313,9315}
EXPECTED_NEG_NEIGHBORS={2754,2755,2756,2757,2799,20428}
OLD_BLOB="bc8c4decb24cf3b94a017f7149a2080bf7570929"

def stop(reason):
    raise RuntimeError(reason)

def roots():
    user=os.environ.get("USER")
    if not user:stop("USER_NOT_SET")
    p=Path("/data/icto")/user/"seagrass-fsi558-runs.sNIpi9"
    old=p/"repair-96764-github-20261122-v3"
    source=p/"trial-96763/runs/hpcc-implicit-002"
    this=p/NAME
    return p,old,source,this

def load_core(old):
    path=old/"code-v5/repair96764.py"
    if not path.is_file():stop("PINNED_ORIGINAL_CONTROLLER_NOT_FOUND "+str(path))
    raw=path.read_bytes()
    blob=hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()
    if blob!=OLD_BLOB:stop("PINNED_ORIGINAL_CONTROLLER_HASH_CHANGED "+blob)
    spec=importlib.util.spec_from_file_location("frozen_real_fsi",path)
    module=importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module

def smooth(d,r):
    if d>=r:return 0.
    x=1.-d/r
    return x*x*(3.-2.*x)

def distances(graph,seed,r):
    seen={seed:0}
    q=deque([seed])
    while q:
        a=q.popleft()
        if seen[a]>=r:continue
        for b in graph.get(a,()):
            if b not in seen:
                seen[b]=seen[a]+1
                q.append(b)
    return seen

def boundary_intersection(poly,owner,distance,r):
    """Refuse to change only half of a processor-to-processor interface."""
    boundary=(poly/"boundary")
    txt=boundary.read_text(errors="strict")
    txt=re.sub(r"/\*.*?\*/","",txt,flags=re.S)
    txt=re.sub(r"//[^\n]*","",txt)
    overlaps=[]
    matches=0
    for m in re.finditer(r"(?ms)^\s*([\w.-]+)\s*\{([^{}]*)\}",txt):
        body=m.group(2)
        kind=re.search(r"\btype\s+([\w]+)\s*;",body)
        start=re.search(r"\bstartFace\s+(\d+)\s*;",body)
        count=re.search(r"\bnFaces\s+(\d+)\s*;",body)
        if not (kind and start and count):continue
        matches+=1
        if kind.group(1)!="processor":continue
        for fid in range(int(start.group(1)),int(start.group(1))+int(count.group(1))):
            if fid>=len(owner):stop("PROCESSOR_PATCH_FACE_OUT_OF_BOUNDS")
            if distance.get(int(owner[fid]),r+1)<r:
                overlaps.append((m.group(1),fid,int(owner[fid])))
                if len(overlaps)>10:break
    if not matches:stop("BOUNDARY_DICTIONARY_NOT_PARSED")
    if overlaps:
        stop("NEGATIVE_BED_REPAIR_TOUCHES_PROCESSOR_PATCH: REQUIRES_MATCHED_CROSS_RANK_FIELD "+
             repr(overlaps))
    return matches

def plan(poly,field,mod):
    owner=mod.read_labels(poly/"owner")
    neigh=mod.read_labels(poly/"neighbour")
    if len(owner)<=len(neigh):stop("TOPOLOGY_OWNER_NEIGHBOUR_COUNTS_INVALID")
    if not 9318<len(neigh):stop("EXPECTED_CRITICAL_FACE_NOT_INTERNAL")
    incident={i for i,o in enumerate(owner) if o==NEG_CENTER}
    incident.update(i for i,n in enumerate(neigh) if n==NEG_CENTER)
    if incident!=EXPECTED_NEG_FACES:
        stop("CELL2758_TOPOLOGY_MISMATCH "+repr(sorted(incident)))
    nbrs=set()
    graph={}
    for a,b in zip(owner,neigh):
        a=int(a);b=int(b)
        graph.setdefault(a,set()).add(b)
        graph.setdefault(b,set()).add(a)
    if graph.get(NEG_CENTER)!=EXPECTED_NEG_NEIGHBORS:
        stop("CELL2758_NEIGHBOUR_MISMATCH")
    source,newstart,newend,values=mod.field_values(field)
    if len(values)!=len(neigh):stop("REFERENCE_FACE_FIELD_LENGTH_MISMATCH")
    pos=distances(graph,POS_CENTER,POS_RINGS)
    neg=distances(graph,NEG_CENTER,NEG_RINGS)
    if neg.get(POS_CENTER) is not None:
        stop("NEGATIVE_BED_REGION_OVERLAPS_POSITIVE_CENTRE")
    boundary_count=boundary_intersection(poly,owner,neg,NEG_RINGS)
    new=[]
    c2only=[]
    changed=0
    changedneg=0
    touched_pos_center=set()
    for fid,(a,b) in enumerate(zip(owner,neigh)):
        a=int(a);b=int(b)
        dp=min(pos.get(a,99),pos.get(b,99))
        dn=min(neg.get(a,99),neg.get(b,99))
        posfactor=1.+(POS_GAIN-1.)*smooth(dp,POS_RINGS)
        negfactor=1.+(NEG_GAIN-1.)*smooth(dn,NEG_RINGS)
        factor=posfactor*negfactor
        # Analytic combined lower bound is 0.85 * 0.98 = 0.833 when
        # the two smooth C2/bed regions overlap. The old 0.84 bound
        # inherited from the +2x trial incorrectly rejects such overlap.
        if not .832<=factor<=1.000000001:stop("COEFFICIENT_MULTIPLIER_OUTSIDE_BOUNDS "+str(factor))
        new.append(values[fid]*factor)
        c2only.append(values[fid]*posfactor)
        if abs(factor-1.)>1e-13: changed+=1
        if abs(negfactor-1.)>1e-13: changedneg+=1
        if a==POS_CENTER or b==POS_CENTER:
            touched_pos_center.add(fid)
            if negfactor!=1.:
                stop("NEGATIVE_PATCH_WOULD_CHANGE_POSITIVE_CENTRE")
    if len(touched_pos_center)!=6:stop("POSITIVE_OLD_CELL_MISSING_EXPECTED_INTERNAL_FACES")
    if changedneg<6 or changedneg>20000:stop("NEGATIVE_PATCH_AFFECTED_FACE_COUNT_OUTSIDE_BOUNDS "+str(changedneg))
    if not all(v>0 for v in new):stop("NON_POSITIVE_REFERENCE_DIFFUSIVITY")
    local=[
        {"face":i,"c2_multiplier":c2only[i]/values[i],
         "combined_multiplier":new[i]/values[i],
         "relative_to_C2":new[i]/c2only[i]}
        for i in sorted(EXPECTED_NEG_FACES)
    ]
    if any(abs(item["relative_to_C2"]-NEG_GAIN)>1e-12 for item in local):
        stop("CRITICAL_FACE_NOT_AT_NEGATIVE_PATCH_CORE")
    info={"type":"C2_MINUS2P_SIGN_DIRECTED_BED_COEFFICIENT_NOT_YET_VALIDATED",
          "source_cell_pos":POS_CENTER,"actual_concave_cell":NEG_CENTER,
          "positive_y": {"gain":POS_GAIN,"rings":POS_RINGS},
          "negative_y_bed":{"gain":NEG_GAIN,"rings":NEG_RINGS},
          "physics_hypothesis":"At 98512 +100 percent bed field, cell2758 face-plane overshot by ~997um on first step. A small opposite -2 percent adjustment may move 0.58075 C2 projection (-2.065um -> +0.204um) away from crossing, but this is NOT guaranteed in nonlinear FSI.",
          "valid_source_topology":True,
          "processor_patch_overlap":False,"boundary_patch_count":boundary_count,
          "changed_internal_faces_total":changed,
          "changed_internal_faces_negative_region":changedneg,
          "cell2758_incident_face_factors":local,
          "minimum_field_before":min(values),"maximum_field_before":max(values),
          "minimum_field_after":min(new),"maximum_field_after":max(new),
          "bed_wall_vertices_3922_3923_never_modified":True,
          "source_checkpoint_t_s":T0,
          "only_c2_plus_one_candidate":True,
          "single_candidate_no_scan":True}
    return source,newstart,newend,values,new,info

def apply_private_field(fluid,mod):
    poly=fluid/"processor5/constant/polyMesh"
    field=fluid/"processor5/constant/motionReferenceDiffusivity"
    if not poly.is_dir() or not field.is_file():stop("PRIVATE_FIELD_TO_PATCH_MISSING")
    raw,a,b,before,after,info=plan(poly,field,mod)
    outfile=field.with_name(field.name+".bed2758.tmp")
    if outfile.exists():stop("PRIVATE_TEMP_FILE_ALREADY_EXISTS")
    write=raw[:a]+mod.encode_field_payload(raw,after)+raw[b:]
    with outfile.open("xb") as f:
        f.write(write);f.flush();os.fsync(f.fileno())
    try:
        _,_,_,verify=mod.field_values(outfile)
        if len(verify)!=len(after) or any(abs(x-y)>max(1e-10,1e-12*abs(y)) for x,y in zip(after,verify)):
            stop("PRIVATE_ALE_FIELD_ROUNDTRIP_MISMATCH")
        os.replace(outfile,field)
    finally:
        if outfile.exists():outfile.unlink()
    info["modified_field_sha256"]=mod.sha(field)
    info["original_field_sha256"]=hashlib.sha256(raw).hexdigest()
    mod.dump(fluid.parent/"BED2758_TARGETED_FIELD.json",info)
    print("BED2758_PRIVATE_ALE_FIELD_PATCH",json.dumps(info,ensure_ascii=False),flush=True)
    return info

def source_preflight():
    p,old,source,this=roots()
    mod=load_core(old)
    mod.preflight()
    if not source.is_dir():stop("VERIFIED_SOURCE_MISSING")
    # Checks both fluid geometry and field from untouched validated checkpoint.
    info=plan(source/"fluid/processor5/constant/polyMesh",
              source/"fluid/processor5/constant/motionReferenceDiffusivity",mod)[-1]
    for candidate in (p/"trial-97576-repair96764-c2-stage1",
                      p/"trial-97854-repair96764-c2-stage1"):
        log=candidate/"fluid.log"
        if not log.is_file() or "concave=1" not in log.read_text(errors="replace"):
            stop("NATIVE_C2_FAILURE_NOT_PRESENT "+str(log))
    return mod,info

def run():
    job=os.environ.get("SLURM_JOB_ID","")
    if not re.fullmatch(r"\d+",job):stop("SLURM_JOB_ID_REQUIRED")
    mod,info=source_preflight()
    p,old,source,this=roots()
    if not this.is_dir():stop("EXPERIMENT_ROOT_MISSING")
    for name in ("trial-96763","trial-96764"):
        # Re-verify existing full checksum backups. NEVER duplicate them.
        mod.backup_trial(name,p,old)
    core=mod.find_core(old)
    driver=mod.import_driver(Path.home()/"hpcc-fsi/three-day-resume-20261119/.mesh-repair558-data.29CSy1/resume-cycles.py")
    os.environ["FSI_DELTA_CORE_PATH"]=str(core)
    src_trial=source.parent.parent
    if src_trial/"runs/hpcc-implicit-002"!=source:stop("SOURCE_TRIAL_LAYOUT_INVALID")
    s1=p/f"trial-{job}-bed2758-s1"
    if s1.exists():stop("STAGE1_DESTINATION_ALREADY_EXISTS")
    orig=driver.build_private_stage
    called=[False]
    def staged(*args,**kwargs):
        result=orig(*args,**kwargs)
        if called[0]:stop("PRIVATE_STAGE_HOOK_CALLED_MULTIPLE_TIMES")
        called[0]=True
        apply_private_field(s1/"runs/hpcc-implicit-002/fluid",mod)
        return result
    driver.build_private_stage=staged
    print("C2_MINUS2P_NATIVE_FSI_STAGE1_START",T0,"target",.5815,flush=True)
    try:
        driver.run_trial(Path.home()/"hpcc-fsi",src_trial,s1,WINDOWS1,core,96763,False)
        ok,why=mod.valid_stage(s1,WINDOWS1,.5815)
    except BaseException as exc:
        ok,why=False,"EXCEPTION_"+repr(exc)
    finally:
        driver.build_private_stage=orig
    steps=[{"stage":1,"work":str(s1),"pass":ok,"reason":why,
            "physical_time_if_accepted":.5815 if ok else T0}]
    print("C2_MINUS2P_NATIVE_FSI_STAGE1_RESULT",json.dumps(steps[-1],ensure_ascii=False),flush=True)
    if ok:
        s2=p/f"trial-{job}-bed2758-s2"
        if s2.exists():stop("STAGE2_DESTINATION_ALREADY_EXISTS")
        print("C2_MINUS2P_NATIVE_FSI_STAGE2_START",.5815,"target",.6035,flush=True)
        try:
            driver.run_trial(Path.home()/"hpcc-fsi",s1,s2,WINDOWS2,core,int(job),False)
            ok2,why2=mod.valid_stage(s2,WINDOWS2,.6035)
        except BaseException as exc:
            ok2,why2=False,"EXCEPTION_"+repr(exc)
        steps.append({"stage":2,"work":str(s2),"pass":ok2,"reason":why2,
                      "physical_time_if_accepted":.6035 if ok2 else .5815})
        print("C2_MINUS2P_NATIVE_FSI_STAGE2_RESULT",json.dumps(steps[-1],ensure_ascii=False),flush=True)
    completed=bool(steps[-1]["stage"]==2 and steps[-1]["pass"])
    summary={"status":"C2_MINUS2P_NATIVE_FSI_PASS_TO_0P6035" if completed else
             "C2_MINUS2P_REPAIR_NOT_VALIDATED",
             "job":int(job),"trial_count":1,
             "verified_time_s":.6035 if completed else .5815 if steps[0]["pass"] else T0,
             "stage_results":steps,"new_ALE_field_private":True,
             "original_96763_unchanged":True,
             "original_96764_unchanged":True,
             "automatic_production_queued":False,
             "production_after_review_and_explicit_validated_gate_only":True}
    mod.dump(this/f"RESULT-{job}.json",summary)
    print("C2_MINUS2P_FINAL_REPAIR_RESULT",json.dumps(summary,ensure_ascii=False),flush=True)
    if not completed:
        print("C2_MINUS2P_FAILED_NATIVE_GATES_NO_LONG_FSI_JOB_QUEUED",flush=True)
        raise SystemExit(3)
    print("C2_MINUS2P_VERIFIED_FSI_RESTART_0P6035",flush=True)
    # After the actual 320 accepted windows and solid checkpoints, re-use
    # the frozen, previously audited afterok production chain. Every segment
    # has a strict native mesh/participant/checkpoint acceptance gate.
    if any(old.glob("CHAIN-*.json")):
        stop("EXISTING_PRODUCTION_CHAIN_REQUIRES_MANUAL_RECONCILIATION")
    print("C2_MINUS2P_START_QUEUE_ONLY_AFTER_VERIFIED_0P6035",flush=True)
    chain=mod.queue_production(s2,int(job),.6035,old)
    print("C2_MINUS2P_AFTEROK_PRODUCTION_JOBS",json.dumps(chain,ensure_ascii=False),flush=True)


def submit():
    mod,info=source_preflight()
    p,old,source,this=roots()
    if this.exists():stop("EXPERIMENT_ROOT_ALREADY_EXISTS_NO_OVERWRITE "+str(this))
    q=subprocess.run(["squeue","-h","-u",os.environ["USER"],
                      "-o","%i|%j|%T"],capture_output=True,text=True,check=True)
    active=[line for line in q.stdout.splitlines()
            if re.search(r"(?:fsi|ale|seagrass|precice|calculix|ccx)",line,re.I)]
    if active:stop("EXISTING_FSI_ALE_JOB_ALREADY_ACTIVE "+repr(active[:20]))
    if not (old/"backups/trial-96763.manifest.json").is_file() or not (
            old/"backups/trial-96764.manifest.json").is_file():
        stop("VERIFIED_BACKUP_MANIFESTS_NOT_PRESENT")
    # Fail closed if a previous production chain exists. No new FSI pilots
    # in parallel with an already queued verified production continuation.
    if any(old.glob("CHAIN-*.json")):
        stop("OLD_REPAIR_PRODUCTION_CHAIN_EXISTS_NO_DUPLICATES")
    # Verify all external dependencies BEFORE creating the case root.
    mod.native_wrapper(old)
    img=Path.home()/"seagrass-fsi-ompi507-scotch-time.sif"
    if not img.is_file():stop("NATIVE_CONTAINER_MISSING")
    this.mkdir()
    # Immutable job script must live on shared /data/icto, not login-node /tmp.
    origin=Path(__file__).resolve()
    if not origin.is_file():stop("SCRIPT_FILE_MISSING")
    src_script=this/"continue-c2-minus2percent-native-fsi.py"
    shutil.copy2(origin,src_script)
    if hashlib.sha256(origin.read_bytes()).digest()!=hashlib.sha256(src_script.read_bytes()).digest():
        stop("PINNED_JOB_SCRIPT_PRIVATE_COPY_MISMATCH")
    src_script.chmod(0o444)
    safe_data=info.copy()
    safe_data["actual_FSI_run_passed"]=False
    mod.dump(this/"PRE_SUBMISSION_PLAN.json",safe_data)
    bash=this/"c2-minus2p.sbatch"
    wrapper=mod.native_wrapper(old)
    img=Path.home()/"seagrass-fsi-ompi507-scotch-time.sif"
    if not img.is_file():stop("NATIVE_CONTAINER_MISSING")
    body=f"""#!/bin/bash
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=12
#SBATCH --mem=24G
#SBATCH --time=3-00:00:00
#SBATCH --job-name=alec2m2fsi
#SBATCH --output={this}/slurm-%j.out
#SBATCH --error={this}/slurm-%j.err
set -euo pipefail
module load gnu14/14.2.0 openmpi5/5.0.7
export SINGULARITYENV_SLURM_JOB_ID="$SLURM_JOB_ID"
export SINGULARITYENV_USER="$USER"
singularity exec --cleanenv -B /data/icto:/data/icto "{img}" /bin/bash "{wrapper}" "{src_script}" --run-job
"""
    bash.write_text(body)
    check=subprocess.run(["bash","-n",str(bash)],capture_output=True,text=True)
    if check.returncode:stop("SLURM_SCRIPT_SYNTAX_FAILED "+check.stderr)
    batch=subprocess.run(["sbatch","--parsable",str(bash)],capture_output=True,text=True,check=True)
    jid=batch.stdout.strip().split(";")[0]
    if not re.fullmatch(r"\d+",jid):stop("SLURM_BAD_JOB_ID "+batch.stdout)
    (this/"job-id.txt").write_text(jid+"\n")
    print("C2_MINUS2P_NATIVE_FSI_SUBMITTED",jid,flush=True)
    print("SLURM_LOG",this/f"slurm-{jid}.out",flush=True)
    print("SINGLE_CANDIDATE_BOUNDARY_PRESERVING_NOT_YET_VALIDATED",flush=True)

def main():
    a=argparse.ArgumentParser(description=__doc__)
    g=a.add_mutually_exclusive_group(required=True)
    g.add_argument("--preflight",action="store_true")
    g.add_argument("--submit",action="store_true")
    g.add_argument("--run-job",action="store_true")
    args=a.parse_args()
    if args.preflight:
        _,plan_info=source_preflight()
        print("C2_MINUS2P_SAFETY_PLAN",json.dumps(plan_info,ensure_ascii=False),flush=True)
        print("PREFLIGHT_PASS_NO_FSI_SUBMITTED")
    elif args.submit:submit()
    else:run()

if __name__=="__main__":
    main()
