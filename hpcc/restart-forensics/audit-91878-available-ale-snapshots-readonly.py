#!/usr/bin/env python3
"""Inspect ONLY genuinely saved OpenFOAM ALE fields; no imagined per-step files.

Purpose: diagnose stage1 91878 after 0.0325s restart while preserving 91006,
91878 and running 91543. Read-only, no solver, no sbatch, no case writes.
Uses checked-in native OpenFOAM 64-bit binary vector reader.
"""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import tempfile

SOURCE="fsi-long-stage0-job91006/runs/hpcc-implicit-002/fluid"
TRIAL="crossjob-fix-20261116/force-ab-tests/trial-91878/runs/hpcc-implicit-002/fluid"
KEYS=("polyMesh/points","pointDisplacement","cellDisplacement","U","p","phi","meshPhi","V0")
REFERENCE_CANDIDATES=(
  ("saved_time_points0","{time}/polyMesh/points0"),
  ("constant_points0","constant/polyMesh/points0"),
  ("zero_points0","0/polyMesh/points0"),
  ("constant_points","constant/polyMesh/points"),
)
TARGET_TIMES=(.032375,.0325,.032625,.03275)

def reader():
    a=Path(__file__).resolve().with_name("audit-binary-ale-coordinates.py")
    if not a.is_file():a=Path(__file__).resolve().parent.parent/"clean-production/audit-binary-ale-coordinates.py"
    if not a.is_file():raise RuntimeError("Missing approved binary OpenFOAM reader: "+str(a))
    spec=importlib.util.spec_from_file_location("openfoam_native_binary_reader",a)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def available_times(processor):
    if not processor.is_dir():raise FileNotFoundError(processor)
    out=[]
    for p in processor.iterdir():
        if not p.is_dir():continue
        try:x=float(p.name)
        except ValueError:continue
        if math.isfinite(x):out.append((x,p))
    out.sort(key=lambda pair:pair[0])
    return out

def time_dir(processor,t):
    matches=[p for x,p in available_times(processor) if abs(x-t)<=1e-11]
    if len(matches)>1:raise RuntimeError(f"Ambiguous time folder for t={t}, rank={processor}")
    return matches[0] if matches else None

def manifest(processor):
    entries=[]
    for x,p in available_times(processor):
        flags={key:(p/key).is_file() for key in KEYS}
        entries.append({
           "time_s":x,"directory":p.name,
           "present":{k:True for k,v in flags.items() if v},
           "missing":{k:True for k,v in flags.items() if not v}
        })
    return entries

def sha(p):
    if not p.is_file():return None
    h=hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda:f.read(1<<20),b""):h.update(chunk)
    return h.hexdigest()

def read_or_error(r,p):
    if not p.is_file():return None,f"MISSING_FILE {p}"
    try:return r(p),None
    except Exception as e:return None,f"READ_ERROR {p}: {type(e).__name__} {str(e)[:220]}"

def diff_stats(reader_fn,old,new):
    a,ea=read_or_error(reader_fn,old)
    b,eb=read_or_error(reader_fn,new)
    if ea or eb:return {"status":"UNAVAILABLE","reason":[e for e in (ea,eb) if e]}
    if len(a)!=len(b) or len(a)%3:return {
      "status":"INCOMPARABLE_POINT_COUNT","a_scalars":len(a),"b_scalars":len(b)}
    values=[math.hypot(b[i]-a[i],b[i+1]-a[i+1],b[i+2]-a[i+2])
            for i in range(0,len(a),3)]
    values.sort()
    n=len(values)
    return {"status":"AVAILABLE","points":n,"max_motion_m":values[-1],
            "mean_motion_m":sum(values)/n,"p99_motion_m":values[min(n-1,int(.99*n))],
            "moved_over_1um":sum(v>1e-6 for v in values)}

def reference_candidates(reader_fn,rank,where,stamp):
    point_path=stamp/"polyMesh/points"
    dis_path=stamp/"pointDisplacement"
    x,ex=read_or_error(reader_fn,point_path)
    d,ed=read_or_error(reader_fn,dis_path)
    if ex or ed:return {"status":"UNAVAILABLE_CURRENT_POINT_OR_DISP",
                        "reason":[s for s in (ex,ed) if s]}
    if len(x)!=len(d):
        return {"status":"INCOMPATIBLE_CURRENT_POINT_AND_DISP_LENGTH",
                "x":len(x),"disp":len(d)}
    results=[]
    for name,spec in REFERENCE_CANDIDATES:
        p=(rank/spec.replace("{time}",where))
        r,er=read_or_error(reader_fn,p)
        if er:
            results.append({"candidate":name,"status":"UNAVAILABLE","reason":er})
            continue
        if len(r)!=len(x):
            results.append({"candidate":name,"status":"SIZE_MISMATCH",
                            "reference_scalars":len(r),"current_scalars":len(x)})
            continue
        maxres=0.0
        sumn=0.0
        for i in range(0,len(x),3):
            v=math.sqrt(sum((x[i+j]-r[i+j]-d[i+j])**2 for j in range(3)))
            maxres=max(maxres,v);sumn+=v
        results.append({"candidate":name,"status":"AVAILABLE",
                        "max_abs_X_minus_Xref_minus_D_m":maxres,
                        "mean_abs_residual_m":sumn/(len(x)/3)})
    return {"status":"REFERENCE_OPTIONS_ONLY_NOT_NATIVE_POINTS0_PROOF",
            "options":results,
            "max_saved_displacement_m":max(
                math.hypot(d[i],d[i+1],d[i+2]) for i in range(0,len(d),3))}

def inspect_rank(base,n,readvec):
    source=base/SOURCE/f"processor{n}"
    trial=base/TRIAL/f"processor{n}"
    data={"rank":n}
    src0=time_dir(source,.0325)
    tr0=time_dir(trial,.0325)
    if not src0 or not tr0:
        raise RuntimeError(f"Missing mandatory 0.0325 restart time folder rank={n}")
    data["source_time_directories"]=len(available_times(source))
    data["trial_time_directories"]=len(available_times(trial))
    data["time_flags"]={}
    for label,root in (("source",source),("trial",trial)):
        flags={}
        for t in TARGET_TIMES:
            d=time_dir(root,t)
            flags[f"{t:g}"]={"directory_present":bool(d),
                "fields_present":{key:(d/key).is_file() if d else False
                                  for key in ("polyMesh/points","pointDisplacement")}}
        data["time_flags"][label]=flags
    data["initial_checkpoint_hash_equal"]={key:
        (sha(src0/key)==sha(tr0/key) if sha(src0/key) and sha(tr0/key) else None)
        for key in ("polyMesh/points","pointDisplacement","U","p","phi","meshPhi","V0")}
    data["source_restart_reference"]=reference_candidates(readvec,source,src0.name,src0)
    data["trial_restart_reference"]=reference_candidates(readvec,trial,tr0.name,tr0)
    tr_end=time_dir(trial,.03275)
    if tr_end:
        data["trial_final_time_field_flags"]={k:(tr_end/k).is_file() for k in KEYS}
        data["trial_0.0325_to_0.03275_point_motion"]=diff_stats(
            readvec,tr0/"polyMesh/points",tr_end/"polyMesh/points")
        data["trial_0.0325_to_0.03275_displacement_change"]=diff_stats(
            readvec,tr0/"pointDisplacement",tr_end/"pointDisplacement")
        data["trial_final_reference"]=reference_candidates(readvec,trial,tr_end.name,tr_end)
    else:
        data["trial_final_time_field_flags"]=None
        data["trial_0.0325_to_0.03275_point_motion"]={"status":"FINAL_TIME_DIRECTORY_MISSING"}
    return data

def summarize(packet):
    lines=["READ_ONLY_91878_AVAILABLE_ALE_SNAPSHOTS"]
    for r in packet["ranks"]:
        lines.append(f"RANK={r['rank']} source_times={r['source_time_directories']} "
                     f"trial_times={r['trial_time_directories']}")
        lines.append("  SAVED_TIME_FIELDS="+str(r["time_flags"]))
        lines.append("  RESTART_T0_HASH_EQUAL="+str(r["initial_checkpoint_hash_equal"]))
        for label in ("source_restart_reference","trial_restart_reference","trial_final_reference"):
            if label not in r:continue
            val=r[label]
            opts=val.get("options",[])
            lines.append("  "+label+"="+str({
                "status":val["status"],
                "candidates":[{k:v for k,v in option.items()
                               if k in ("candidate","status","max_abs_X_minus_Xref_minus_D_m",
                                        "reason","reference_scalars","current_scalars")}
                              for option in opts]}))
        lines.append("  trial_t0_to_t2_points="+str(r["trial_0.0325_to_0.03275_point_motion"]))
        lines.append("  trial_t0_to_t2_displacement="+str(
            r.get("trial_0.0325_to_0.03275_displacement_change")))
    lines.extend([
      "CAUTION: This compares a TWO-window restart delta only where both files really exist.",
      "CAUTION: Directory existence does not mean every field is saved; OpenFOAM mesh files may be inherited.",
      "CAUTION: Fallback constant/polyMesh/points is a candidate, not proof of native points0 selection.",
      "NO_SBATCH_NO_SOLVER_NO_SOURCE_OR_LIVE_JOB_WRITES"])
    return "\n".join(lines)

def selftest():
    with tempfile.TemporaryDirectory() as d:
        proc=Path(d)/"processor0"
        (proc/"0.0325").mkdir(parents=True)
        (proc/"0.032625").mkdir()
        (proc/"0.03275").mkdir()
        (proc/"0.0325/pointDisplacement").write_text("sample")
        assert time_dir(proc,.0325).name=="0.0325"
        assert not (time_dir(proc,.032625)/"pointDisplacement").is_file()
        assert len(available_times(proc))==3
        assert len(manifest(proc))==3
        out=diff_stats(lambda p:[0,0,0],proc/"0.032625/pointDisplacement",
                       proc/"0.0325/pointDisplacement")
        assert out["status"]=="UNAVAILABLE"
        (proc/".0325").mkdir()
        try:time_dir(proc,.0325)
        except RuntimeError:pass
        else:raise AssertionError("Identical numeric time aliases must raise")
    print("ALE_AVAILABLE_SNAPSHOT_AUDIT_SELFTEST_PASS")

def main():
    a=argparse.ArgumentParser()
    a.add_argument("--base",type=Path,default=Path.home()/"hpcc-fsi")
    a.add_argument("--self-test",action="store_true")
    a.add_argument("--summary",action="store_true")
    opts=a.parse_args()
    if opts.self_test:return selftest()
    base=opts.base.expanduser().resolve(strict=True)
    if not (base/SOURCE).is_dir() or not (base/TRIAL).is_dir():
        raise RuntimeError("Source 91006 or isolated trial 91878 not found")
    vec=reader().numeric_binary_vectors
    packet={"report":"READ_ONLY_91878_ACTUAL_AVAILABLE_SAVED_ALE_FIELDS",
            "ranks":[inspect_rank(base,i,vec) for i in range(8)]}
    print(summarize(packet) if opts.summary else json.dumps(packet,indent=2,ensure_ascii=False))
    print("NO_MODIFICATION_NO_SOLVER_NO_SCHEDULER")

if __name__=="__main__": main()
