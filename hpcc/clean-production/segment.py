#!/usr/bin/env python3
"""Clean production 3D FSI segment; prior completion under a separate project root.

Stage 0: continue validated 90873 at t=0.0025 s.
Later stages: consume ONLY successful previous stage with intact checkpoints.
Starts Fluid and Solid simultaneously in a fresh preCICE session and checks
coupling convergence, native mesh, Courant and checkpoint advancement. Each
stage ends normally to write CalculiX .rout; Slurm dependency stops on failure.
No staged data or physics inputs are modified in place.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import traceback

DT=0.000125
MAX_ITER=50
MAX_CO=.5
MAX_NONORTH=65
END_G1=.0025
EXPECTED_RANKS=8

def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1<<20),b""):h.update(b)
    return h.hexdigest()

def jread(path):
    return json.loads(path.read_text())

def jwrite(path,obj):
    tmp=path.with_suffix(path.suffix+".tmp")
    tmp.write_text(json.dumps(obj,indent=2,ensure_ascii=False)+"\n")
    tmp.replace(path)

def exact(pattern,repl,source,description):
    result,n=re.subn(pattern,repl,source,flags=re.M)
    if n!=1:raise RuntimeError(f"{description}: expected one replacement, got {n}")
    return result

def latest_time(fluid):
    timestamps=[]
    for rank in range(EXPECTED_RANKS):
        p=fluid/f"processor{rank}"
        if not p.is_dir():raise RuntimeError(f"Missing processor{rank}")
        numeric=[]
        for child in p.iterdir():
            if child.is_dir():
                try:
                    n=float(child.name)
                    if math.isfinite(n):numeric.append((n,child))
                except ValueError:pass
        if not numeric:raise RuntimeError(f"No saved times rank {rank}")
        t,folder=max(numeric,key=lambda item:item[0])
        for field in ("U","p","phi","pointDisplacement","polyMesh/points","uniform/time"):
            if not (folder/field).is_file():
                raise RuntimeError(f"Rank {rank} lacks checkpoint {field}")
        timestamps.append((t,folder))
    if max(t for t,_ in timestamps)-min(t for t,_ in timestamps)>1e-9:
        raise RuntimeError("Fluid MPI checkpoints do not share one time")
    return timestamps[0][0],timestamps

def numeric_time_names(processor):
    """Sorted time directories; excludes non-time names, no state changes."""
    if not processor.is_dir():
        raise RuntimeError(f"Missing fluid processor directory: {processor}")
    pairs=[]
    for item in processor.iterdir():
        if not item.is_dir():continue
        try:
            time_value=float(item.name)
        except ValueError:
            continue
        if not math.isfinite(time_value):
            raise RuntimeError(f"Nonfinite time directory: {item}")
        pairs.append((time_value,item.name))
    return [name for _,name in sorted(pairs)]

def verify_staged_fluid_history(source,staged,stage):
    """Enforce source -> private-copy time-history preservation before solver."""
    result={}
    for rank in range(EXPECTED_RANKS):
        rank_name=f"processor{rank}"
        a=numeric_time_names(source/"fluid"/rank_name)
        b=numeric_time_names(staged/"fluid"/rank_name)
        if not a or a!=b:
            raise RuntimeError(
                f"OUR_RESTART_HISTORY_COPY_FAILED {rank_name} "
                f"source={a} staged={b}")
        if stage>=1 and len(a)<2:
            raise RuntimeError(
                f"OUR_RESTART_HISTORY_INSUFFICIENT {rank_name}: only {a}")
        result[rank_name]={"source_time_folders":len(a),
                           "staged_time_folders":len(b),
                           "latest_time":a[-1]}
    return result

def segment_folder(stage):
    if not 1<=stage<=12:
        raise RuntimeError("Only segments A-L supported")
    return f"segment-{chr(ord('A')+stage-1)}"

def source_for(base,stage,previous_job,chain_root=None):
    if stage==0:
        previous=base/"g1-b10-job-90873"
        reports=sorted(base.glob("g1-b-90873-posthoc-*.json"))
        if not reports:raise RuntimeError("Missing 90873 passed posthoc evidence")
        accepted=any(jread(p).get("status")==
            "G1_B_90873_POSTHOC_EVIDENCE_PASS_NATIVE_MESH_UNVERIFIED"
            for p in reports)
        if not accepted:raise RuntimeError("No verified 90873 10+10 posthoc report")
        expected_t=END_G1
        previous_wall_per_window=1690.2690456761047/10
        next_step=2
    elif stage==1 and previous_job==91006:
        # Recovery of the COMPLETE but post-hoc-rejected 91006 solver run.
        # Gate with a separately issued native checkMesh certificate and a
        # recorded first-window Mesh Courant exception. Never change 91006.
        certificate=jread(base/"FSI_91006_RESUME_CERT.json")
        if certificate.get("status")!="FSI_91006_CONDITIONAL_RESTART_ELIGIBLE":
            raise RuntimeError("91006 recovery does not have valid independent certification")
        if certificate.get("source_job")!=91006 or certificate.get("next_step")!=3:
            raise RuntimeError("91006 certificate identity/restart step mismatch")
        if certificate.get("native_terminal_checkMesh",{}).get("status")!="PASS":
            raise RuntimeError("91006 native terminal mesh not independently validated")
        prior=certificate.get("evidence",{})
        if prior.get("accepted_windows")!=240 or prior.get("original_guard_failures")!=0:
            raise RuntimeError("91006 attempted 240-window completion was not proven")
        if not prior.get("startup_exception"):
            raise RuntimeError("91006 initial Mesh Courant waiver was not explicitly documented")
        if prior.get("first_window_meshCo_last_record",99)>.5 or prior.get("remaining_239_windows_meshCo_max",99)>.5:
            raise RuntimeError("91006 did not meet conditional startup exception criteria")
        previous=base/"fsi-long-stage0-job91006"
        run=previous/"runs/hpcc-implicit-002"
        hashes=prior.get("checkpoint_hashes",{})
        for label,filepath in (
          ("solid_rout_sha256",run/"solid/seagrass.rout"),
          ("solid_kinematic_sha256",run/"solid/kinematic_state.bin"),
          ("fluid_proc0_terminal_points_sha256",
           run/"fluid/processor0/0.0325/polyMesh/points")):
            if not filepath.is_file() or sha(filepath)!=hashes.get(label):
                raise RuntimeError("91006 checkpoint changed since independent certification: "+label)
        expected_t=.0325
        previous_wall_per_window=32483.809472374618/240
        next_step=3
    else:
        if not previous_job:raise RuntimeError("Missing previous Slurm job")
        previous=(chain_root/segment_folder(stage-1) if chain_root is not None
                  else base/f"fsi-long-stage{stage-1}-job{previous_job}")
        evidence=jread(previous/"FSI_SEGMENT_RESULT.json")
        if evidence.get("status") not in (
                "FSI_LONG_SEGMENT_PASS",
                "FSI_LONG_SEGMENT_PASS_WITH_RESTART_TRANSIENT"):
            raise RuntimeError("Previous chained job was not accepted")
        if evidence.get("status")=="FSI_LONG_SEGMENT_PASS_WITH_RESTART_TRANSIENT":
            q=evidence.get("quality",{})
            if not (q.get("first_window_restart_transient_exception") is True
                    and q.get("first_window_meshCo_last_record",99)<=.5
                    and q.get("later_window_meshCo_max",99)<=.5):
                raise RuntimeError("Previous conditional segment lacks narrow documented meshCo evidence")
        if evidence.get("stage")!=stage-1:
            raise RuntimeError("Previous stage index mismatch")
        if evidence.get("participant_exit_codes")!={"fluid":0,"solid":0}:
            raise RuntimeError("Previous participant exit status mismatch")
        expected_t=float(evidence["final_time_s"])
        previous_wall_per_window=float(evidence["wall_s"])/int(evidence["accepted_windows"])
        next_step=int(evidence["read_restart_step"])+1
    run=previous/"runs/hpcc-implicit-002"
    if not run.is_dir():
        raise RuntimeError(f"Missing validated source run: {run}")
    t,saved=latest_time(run/"fluid")
    if abs(t-expected_t)>1e-9:
        raise RuntimeError(f"Checkpoint mismatch expected {expected_t} found {t}")
    if stage==0:
        # 90873 post-hoc proves FSI trajectory agreement, but the original
        # verifier stopped before checking checkpoint advancement. Verify
        # BOTH outputs are actually different from their 0.00125s inputs.
        pairs=(("seagrass.rin","seagrass.rout"),
               ("kinematic_state.input.bin","kinematic_state.bin"))
        for before,after in pairs:
            inp=run/"solid"/before
            out=run/"solid"/after
            if not inp.is_file() or not out.is_file() or sha(inp)==sha(out):
                raise RuntimeError("90873 structural state not advanced: "+
                                   before+" -> "+after)
    deck=(run/"solid/seagrass.inp").read_text()
    match=re.search(r"(?mi)^\s*\*RESTART\s*,\s*READ\s*,\s*STEP=(\d+)",deck)
    if not match or int(match.group(1))!=next_step-1:
        raise RuntimeError("CalculiX prior restart step chain not as expected")
    for f in ("solid/seagrass.rout","solid/kinematic_state.bin",
              "restart_reference/Solid-Mesh.coords"):
        if not (run/f).is_file() or (run/f).stat().st_size<1000:
            raise RuntimeError(f"Missing source structural state {f}")
    return previous,run,t,saved,next_step,previous_wall_per_window

def choose_windows(stage,max_windows,seconds_per_window):
    if stage==0:
        if max_windows!=240:raise RuntimeError("First segment must be 240 windows to align end output on 80-step interval")
        return 240
    if not math.isfinite(seconds_per_window) or seconds_per_window<=0:
        raise RuntimeError("Missing prior measured wall clock throughput")
    # 60h of estimated wall with 35% slowdown reserve and <=66h hard watchdog.
    budget=int((60*3600)/(seconds_per_window*1.35))
    planned=min(max_windows, (budget//80)*80)
    if planned<80:
        raise RuntimeError("Performance too slow even for an 80-window safe segment")
    return planned

def stage_inputs(base,stage,previous_job,work,max_windows,chain_root=None):
    previous,source,start,saved,step,per_win=source_for(base,stage,previous_job,chain_root)
    n=choose_windows(stage,max_windows,per_win)
    end=start+n*DT
    if work.exists():raise RuntimeError(f"Refusing to reuse work path {work}")
    for f in (previous,source,base/"seagrass-implicit-20261111",
              base/"performance-full160-job-89038"):
        if work==f or f in work.parents or work in f.parents:
            raise RuntimeError("Work path overlaps a frozen original")
    work.mkdir(parents=True)
    dst=work/"runs/hpcc-implicit-002"
    dst.parent.mkdir()
    # Keep only the latest distributed checkpoint, with original case static
    # fields; do not accumulate older history across multi-day stages.
    # IMPORTANT: retain source time history rather than dropping all but
    # the most recent MPI time directory. Although historic time folders
    # alone do not prove restoration of mesh oldPoints / moving fluxes,
    # deleting them was an avoidable loss of restart evidence.
    # All copied files remain private to the isolated new work folder.
    def ignore(parent,names):
        p=Path(parent)
        return [x for x in names if x=="precice-profiling"] if p.name in ("fluid","solid") else []
    shutil.copytree(source,dst,ignore=ignore,symlinks=False)
    history=verify_staged_fluid_history(source,dst,stage)
    for child in dst.rglob("precice-*"):
        if child.is_file() and child.suffix in (".log",".json",".csv"):
            child.unlink()
    for name in ("seagrass.dat","seagrass.cvg","seagrass.frd","seagrass.sta","spooles.out"):
        (dst/"solid"/name).unlink(missing_ok=True)
    for log in dst.glob("*.log"):log.unlink()
    solid=dst/"solid"
    original_rout=sha(solid/"seagrass.rout")
    original_kin=sha(solid/"kinematic_state.bin")
    shutil.copy2(solid/"seagrass.rout",solid/"seagrass.rin")
    shutil.copy2(solid/"kinematic_state.bin",solid/"kinematic_state.input.bin")
    (solid/"seagrass.rout").unlink()
    (solid/"kinematic_state.bin").unlink()
    # Set next explicit CalculiX restart step and duration. No new material
    # or mesh definitions, no changes to physical structure parameters.
    deck=solid/"seagrass.inp"
    txt=deck.read_text()
    txt=exact(r"(?im)^(\s*\*RESTART\s*,\s*READ\s*,\s*STEP=)\d+",
              lambda m:m.group(1)+str(step),txt,"CalculiX restart step")
    def dynamic(match):
        parts=match.group(2).split(",")
        if not math.isclose(float(parts[0]),DT,abs_tol=1e-12):
            raise RuntimeError("Structure dt changed")
        parts[1]=f" {n*DT:.12g}"
        return match.group(1)+",".join(parts)
    txt=exact(r"(?im)^(\s*\*DYNAMIC\s*,\s*DIRECT[^\n]*\n)([^\n]+)",
              dynamic,txt,"structural step duration")
    if not re.search(r"(?im)^\s*\*RESTART\s*,\s*WRITE\s*,\s*FREQUENCY=1\s*,\s*OVERLAY",txt):
        raise RuntimeError("Solid stage lacks end-step output .rout")
    deck.write_text(txt)
    control=dst/"fluid/system/controlDict"
    conf=control.read_text()
    if not re.search(r"\bstartFrom\s+latestTime\s*;",conf):
        raise RuntimeError("Fluid did not use latestTime restart")
    conf=exact(r"(?m)(?<![A-Za-z0-9_])(endTime\s+)([-+.\deE]+)(\s*;)",
               lambda m:m.group(1)+f"{end:.12g}"+m.group(3),
               conf,"fluid absolute endTime")
    # A restarted timeStep counter may continue its absolute timeIndex:
    # at 0.0025 s start index is 20; 240 new steps end at index 260.
    # 80 does NOT divide 260. Use a divisor of the absolute END index
    # to guarantee a written final checkpoint without relying on
    # undocumented endTime forced writes.
    end_step=round(end/DT)
    if abs(end/DT-end_step)>1e-7:
        raise RuntimeError("End time not on exact dt index")
    write_every=math.gcd(end_step,80)
    if write_every<1:
        raise RuntimeError("Failed to select safe write interval")
    conf,changes=re.subn(r"(writeControl\s+timeStep\s*;\s*writeInterval\s+)\d+(\s*;)",
                         lambda m:m.group(1)+str(write_every)+m.group(2),conf)
    if changes!=4:raise RuntimeError(f"Expected 4 writeIntervals; got {changes}")
    conf=exact(r"(purgeWrite\s+)\d+(\s*;)",r"\g<1>2\2",conf,"fluid purgeWrite")
    control.write_text(conf)
    xml=dst/"precice-config.xml"
    doc=xml.read_text()
    doc=exact(r'(<max-time value=")[\d.eE+-]+(")',
              lambda m:m.group(1)+f"{n*DT:.12g}"+m.group(2),
              doc,"new session duration")
    doc=exact(r'(<time-windows-reused value=")(?:5|15)(")',
              r"\g<1>15\2",doc,"IQN15")
    if doc.count('limit="1e-05"')!=2 or "coupling-scheme:parallel-implicit" not in doc:
        raise RuntimeError("Convergence or implicit coupling altered")
    xml.write_text(doc)
    if "restartFromDeformed true;" not in (dst/"fluid/system/preciceDict").read_text():
        raise RuntimeError("Missing restored fluid FSI reference policy")
    meta={
        "status":"STAGED_NOT_RUN",
        "stage":stage,"parent_job":90873 if stage==0 else int(previous_job),
        "parent_run":str(source),"parent_time_s":start,
        "read_restart_step":step,"accepted_windows":n,
        "estimated_previous_wall_s_per_window":per_win,
        "final_time_s":end,
        "solid_input_rin_sha256":original_rout,
        "solid_input_kinematic_sha256":original_kin,
        "no_physical_parameters_modified":True,
        "mpi_fluid":8,"omp_solid":4,"iqn_reuse":15,
        "dt_s":DT,"dual_convergence_tol":1e-5,
        "fluid_write_interval_steps":write_every,
        "origin_90873_untouched":True,
        "source_checkpoint":"0.0325s certified if stage1, otherwise previous accepted clean segment",
        "fluid_history_preserved_before_solver":True,
        "fluid_history_per_rank":history
    }
    jwrite(work/"FSI_SEGMENT_STAGE.json",meta)
    return dst,meta

def accepted_iterations(path,n):
    if not path.is_file():raise RuntimeError("Missing preCICE Solid iterations")
    lines=[line.split() for line in path.read_text(errors="replace").splitlines() if line.strip()]
    hdr=["TimeWindow","TotalIterations","Iterations","Convergence",
         "QNColumns","DeletedQNColumns","DroppedQNColumns"]
    if not lines or lines[0]!=hdr or len(lines)!=n+1:
        raise RuntimeError(f"preCICE iterations count or header error: {len(lines)-1} / {n}")
    allrows=[]
    total=0
    for index,values in enumerate(lines[1:],1):
        try:row=list(map(int,values))
        except ValueError:raise RuntimeError(f"Noninteger window row {index}")
        if len(row)!=7:raise RuntimeError("Incorrect preCICE columns")
        total+=row[2]
        if row[0]!=index or not 1<=row[2]<=MAX_ITER or row[1]!=total or row[3]!=1:
            raise RuntimeError(f"Window {index} did not pass convergence: {row}")
        allrows.append(row)
    return allrows

def quality_from_log(log,end,first_attempt_time,allow_transient=False):
    """Keep frozen fluid Co and mesh quality gates. Explicitly report the
    first-window meshCo restart transient instead of silently discarding it.

    An exception is eligible ONLY if every meshCo>0.5 has the very first
    absolute physical window label, that window's final logged value is <=0.5,
    and all subsequent windows are <=0.5. Preserve the excursion in JSON.
    """
    txt=log.read_text(errors="replace")
    matches=re.findall(
       r"SEAGRASS_MESH_GUARD\s+time=([\d.eE+-]+)\s+minVolume=([\d.eE+-]+)"
       r"\s+concave=(\d+)\s+qualityFailed=(\d+)\s+skewFailed=(\d+)"
       r"\s+orthFailed=(\d+)\s+tetFailed=(\d+)",txt)
    if not matches:raise RuntimeError("No in-situ original ALE guard evidence")
    recs=[]
    for data in matches:
        recs.append([float(data[0]),float(data[1])]+[int(x) for x in data[2:]])
    if any(r[1]<=0 or any(r[2:]) for r in recs):
        raise RuntimeError("ALE mesh guard failed during real FSI segment")
    if not any(abs(r[0]-end)<1e-9 for r in recs):
        raise RuntimeError("ALE mesh guard missing final physical time")

    co=[float(x) for x in re.findall(
       r"(?<!Mesh )Courant Number mean:\s*[\d.eE+-]+\s+max:\s*([\d.eE+-]+)",txt)]
    if not co or max(co)>.5:
        raise RuntimeError("Missing fluid Courant diagnostics or fluid Co>0.5")

    mesh_events=[]
    tm=None
    for line in txt.splitlines():
        found=re.match(r"^\s*Time\s*=\s*([+-]?[\d.eE+-]+)\s*$",line)
        if found:tm=float(found.group(1))
        match=re.search(
            r"Mesh Courant Number mean:\s*[\d.eE+-]+\s+max:\s*([\d.eE+-]+)",line)
        if match:
            value=float(match.group(1))
            if not math.isfinite(value):
                raise RuntimeError("Nonfinite mesh Courant number")
            mesh_events.append((tm,value))
    if not mesh_events:raise RuntimeError("No mesh Courant histories")
    high=[(time,value) for time,value in mesh_events if value>.5]
    # A restarted coupled session must not silently pass a large transient.
    # Historic continuous stage-0 evidence may explicitly opt in, but a
    # NEW cross-Slurm job is strict unless independent numerical validation
    # proves any relaxation safe.
    if high and not allow_transient:
        raise RuntimeError(f"UNQUALIFIED_CROSS_JOB_MESH_COURANT_SPIKE peak={max(v for _,v in high)}")
    first=[v for time,v in mesh_events
           if time is not None and abs(time-first_attempt_time)<1e-9]
    following=[v for time,v in mesh_events
               if time is not None and time>first_attempt_time+1e-9]
    if not first or not following:
        raise RuntimeError("Missing first-window or later-window mesh Courant evidence")
    if any(time is None or abs(time-first_attempt_time)>1e-9
           for time,value in high):
        raise RuntimeError("Mesh Courant >0.5 outside the first restart window")
    if first[-1]>.5:
        raise RuntimeError("First restart window's LAST mesh Courant remains >0.5")
    if max(following)>.5:
        raise RuntimeError("Later time window mesh Courant >0.5")
    quality={
        "max_fluid_Co":max(co),
        "max_mesh_Co":max(v for _,v in mesh_events),
        "min_ale_volume_m3":min(r[1] for r in recs),
        "native_guard_checks":len(recs),
        "first_window_meshCo_last_record":first[-1],
        "first_window_meshCo_max":max(first),
        "initial_restart_window_high_events":len(high),
        "later_window_meshCo_max":max(following),
        "first_window_restart_transient_exception":bool(high),
        "numeric_accuracy_verified_for_startup_excursion":False,
    }
    return quality

def first_computed_fluid_force(log):
    """Read first physical force sample, not the preCICE initialized exchange."""
    text=log.read_text(errors="replace")
    m=re.search(
        r"forces bladeForces write:.*?\bTotal\s*:\s*"
        r"\(([-+\d.eE]+)\s+([-+\d.eE]+)\s+([-+\d.eE]+)\)",
        text,re.S)
    if not m:raise RuntimeError("Cross-job force gate: no bladeForces first computed sample")
    force=tuple(float(v) for v in m.groups())
    if not all(math.isfinite(v) for v in force):
        raise RuntimeError("Cross-job force gate: nonfinite computed force")
    return force

def previous_last_accepted_force(source):
    path=source/"solid/precice-Solid-watchintegral-Interface-Integral.log"
    if not path.is_file():
        raise RuntimeError("Cross-job force gate: missing prior accepted force watch")
    result=None
    for line in path.read_text(errors="replace").splitlines():
        cols=line.split()
        if len(cols)<2:continue
        try:
            time=float(cols[0]);fx=float(cols[1])
        except ValueError:continue
        if math.isfinite(time) and math.isfinite(fx):
            result=(time,fx)
    if result is None:
        raise RuntimeError("Cross-job force gate: no prior accepted watch force")
    return result

def validate_cross_job_force(source,log,max_relative_error=.20):
    """Diagnostic only: the first PIMPLE force is an UNACCEPTED iteration.

    Do not compare it with the previous *accepted* preCICE watch integral
    as an acceptance gate. 91006 and continuous 91543 also have first
    provisional forces near 11 N while their accepted forces are ~0.018 N.
    Our earlier 650x failure criterion mixed different coupling stages.
    Actual continuity is checked using accepted force windows separately.
    """
    prior_time,accepted=previous_last_accepted_force(source)
    provisional=first_computed_fluid_force(log)
    ratio=(abs(provisional[0]-accepted)/abs(accepted)
           if abs(accepted)>1e-12 else None)
    return {
        "status":"PROVISIONAL_NOT_COMPARABLE_TO_ACCEPTED",
        "prior_accepted_relative_time_s":prior_time,
        "prior_accepted_Fx_N":accepted,
        "first_provisional_Fx_N":provisional[0],
        "first_provisional_Fy_N":provisional[1],
        "first_provisional_Fz_N":provisional[2],
        "provisional_to_accepted_relative_difference_DIAGNOSTIC_ONLY":ratio,
        "used_as_pass_fail_gate":False,
        "pass_fail_from":"validate_accepted_force_continuity"
    }

def validate_accepted_force_continuity(source,solid_log,dt,
                                        max_relative_error=.20,
                                        continuous_reference_log=None,
                                        absolute_restart_time_s=None,
                                        reference_origin_time_s=.0025):
    """Validate two accepted *implicit* windows, not just provisional force.

    The previously validated source watch integral supplies the t=restart
    baseline. This is a deliberately strict startup gate for a new Slurm
    coupled session, not a general bound for long unsteady vegetation loads.
    """
    prior_time,baseline=previous_last_accepted_force(source)
    if abs(baseline)<1e-12:
        raise RuntimeError("CROSS_JOB_ACCEPTED_FORCE_BASELINE_ZERO: requires case-specific absolute tolerance")
    if not solid_log.is_file():
        raise RuntimeError("CROSS_JOB_ACCEPTED_FORCE_WATCH_MISSING")
    records={}
    for line in solid_log.read_text(errors="replace").splitlines():
        tokens=line.split()
        if len(tokens)<2:continue
        try:
            t,fx=float(tokens[0]),float(tokens[1])
        except ValueError:continue
        if math.isfinite(t) and math.isfinite(fx):
            records[round(t,9)]=fx
    # A restarted and continuous case can have different relative clocks.
    # Never compare different physical instants or assume the previous Fx
    # stays constant as a scientific reference for the next two windows.
    continuous_records={}
    if continuous_reference_log is not None:
        if absolute_restart_time_s is None:
            raise RuntimeError("CONTINUOUS_REFERENCE_NEEDS_ABSOLUTE_RESTART_TIME")
        if not continuous_reference_log.is_file():
            raise RuntimeError("CONTINUOUS_REFERENCE_WATCH_MISSING")
        for line in continuous_reference_log.read_text(errors="replace").splitlines():
            cols=line.split()
            if len(cols)<2:continue
            try:time_ref,fx_ref=float(cols[0]),float(cols[1])
            except ValueError:continue
            if math.isfinite(time_ref) and math.isfinite(fx_ref):
                continuous_records[round(time_ref,9)]=fx_ref
    first=[]
    for index in (1,2):
        t=round(index*dt,9)
        if t not in records:
            raise RuntimeError(f"CROSS_JOB_ACCEPTED_FORCE_MISSING window={index} rel_time={t}")
        fx=records[t]
        err=abs(fx-baseline)/abs(baseline)
        if not math.isfinite(err) or err>max_relative_error:
            raise RuntimeError(
                f"UNPHYSICAL_CROSS_JOB_ACCEPTED_FORCE window={index} "
                f"source_Fx={baseline:.12g} accepted_Fx={fx:.12g} "
                f"relative_error={err:.9g} threshold={max_relative_error}")
        comparison={"window":index,"relative_time_s":t,
                    "accepted_Fx_N":fx,"relative_error_to_prior":err}
        if continuous_reference_log is not None:
            phys=absolute_restart_time_s+t
            reference_t=round(phys-reference_origin_time_s,9)
            if reference_t not in continuous_records:
                raise RuntimeError(
                    f"CONTINUOUS_REFERENCE_MISSING physical_time={phys:.9g} "
                    f"reference_relative_time={reference_t:.9g}")
            expected=continuous_records[reference_t]
            if abs(expected)<1e-12:
                raise RuntimeError("CONTINUOUS_REFERENCE_FORCE_ZERO_REQUIRES_ABSOLUTE_TOL")
            delta=abs(fx-expected)/abs(expected)
            comparison.update(physical_time_s=phys,continuous_reference_Fx_N=expected,
                              relative_error_to_continuous=delta)
            if delta>max_relative_error:
                raise RuntimeError(
                    f"UNPHYSICAL_CROSS_JOB_VS_CONTINUOUS window={index} "
                    f"physical_time={phys:.9g} reference_Fx={expected:.12g} "
                    f"accepted_Fx={fx:.12g} relative_error={delta:.9g} "
                    f"threshold={max_relative_error}")
        first.append(comparison)
    return {"source_relative_time_s":prior_time,"source_Fx_N":baseline,
            "continuous_reference_checked":continuous_reference_log is not None,
            "first_two_windows":first,"threshold":max_relative_error}

def check_mesh(fluid,work):
    command=["mpirun","--oversubscribe","-np","8","--bind-to","none",
             "checkMesh","-case",str(fluid),"-parallel",
             "-fileHandler","uncollated","-latestTime",
             "-allGeometry","-allTopology","-meshQuality"]
    result=subprocess.run(command,cwd=work,capture_output=True,text=True,timeout=1800)
    txt=result.stdout+"\n"+result.stderr
    (work/"native-final-checkMesh.log").write_text(txt)
    if result.returncode!=0 or not re.search(r"(?m)^\s*Mesh OK\.\s*$",txt):
        raise RuntimeError("Native terminal checkMesh failed (see retained log)")
    if re.search(r"FOAM FATAL|Failed\s+[1-9]\d*\s+mesh checks?",txt,re.I):
        raise RuntimeError("Native terminal mesh failed checks")
    orth=[float(x) for x in re.findall(r"Max non-orthogonality\s*=\s*([\d.]+)",txt)]
    if orth and max(orth)>65:raise RuntimeError("Mesh nonorthogonality exceeds 65")
    return {"status":"PASS","max_nonorthogonality_deg":max(orth) if orth else None}

def run(base,stage,previous_job,work,max_windows,timeout,chain_root=None):
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("Real job requires a Slurm allocation")
    if os.environ.get("WM_PROJECT_VERSION")!="v2512":
        raise RuntimeError("OpenFOAM v2512 environment not loaded")
    if not shutil.which("mpirun") or not shutil.which("precice-config-validate"):
        raise RuntimeError("Required OpenMPI/preCICE tools missing")
    start_wall=time.monotonic()
    runfolder,meta=stage_inputs(base,stage,previous_job,work,max_windows,chain_root)
    state={"status":"STARTING","stage":stage,"restart_from_time_s":meta["parent_time_s"],
           "final_time_s":meta["final_time_s"]}
    jwrite(work/"STATE.json",state)
    fluid=runfolder/"fluid"
    solid=runfolder/"solid"
    ccx=base/"seagrass-implicit-20261111/scripts/native/bin/ccx_preCICE_persistent_v2"
    refso=base/"seagrass-implicit-20261111/scripts/native/lib/libseagrassReferenceRestart.so"
    for binary in (ccx,refso):
        if not binary.is_file():raise RuntimeError(f"Missing native component {binary}")
    for participant in ("Fluid","Solid"):
        p=subprocess.run(["precice-config-validate",
              str(runfolder/"precice-config.xml"),participant],
              cwd=runfolder,capture_output=True,text=True,timeout=120)
        (work/f"precice-{participant}-validation.log").write_text(p.stdout+p.stderr)
        if p.returncode:raise RuntimeError(f"Invalid preCICE {participant} configuration")
    commands={
       "fluid":["/usr/bin/time","-v","mpirun","--oversubscribe","-np","8",
                "--bind-to","none","pimpleFoam","-fileHandler","uncollated","-parallel"],
       "solid":["/usr/bin/time","-v",str(ccx),"-i","seagrass",
                "-precice-participant","Solid"]}
    jwrite(work/"COMMANDS.json",commands)
    procs={}
    handles={}
    try:
        for name,directory in (("fluid",fluid),("solid",solid)):
            env=os.environ.copy()
            env["OMP_NUM_THREADS"]="4" if name=="solid" else "1"
            env["PYTHONDONTWRITEBYTECODE"]="1"
            if name=="solid":
                env.update({
                  "LD_PRELOAD":str(refso),
                  "SG_REFERENCE_MODE":"restore",
                  "SG_REFERENCE_DIR":str(runfolder/"restart_reference"),
                  "SG_PERSISTENT_STATE_IN":str(solid/"kinematic_state.input.bin"),
                  "SG_PERSISTENT_STATE_OUT":str(solid/"kinematic_state.bin"),
                })
            f=(work/f"{name}.log").open("x")
            handles[name]=f
            procs[name]=subprocess.Popen(commands[name],cwd=directory,env=env,
                 stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT,
                 start_new_session=True)
        state["status"]="RUNNING"
        jwrite(work/"STATE.json",state)
        while any(p.poll() is None for p in procs.values()):
            if time.monotonic()-start_wall>=timeout:
                raise RuntimeError("SEGMENT_TIMEOUT_BEFORE_CHECKPOINT")
            failures=[(name,p.returncode) for name,p in procs.items()
                      if p.poll() is not None and p.returncode!=0]
            if failures:raise RuntimeError(f"FSI participant error: {failures}")
            time.sleep(15)
        exits={name:p.returncode for name,p in procs.items()}
        if exits!={"fluid":0,"solid":0}:raise RuntimeError(f"FSI exits invalid: {exits}")
        iters=accepted_iterations(solid/"precice-Solid-iterations.log",meta["accepted_windows"])
        t,saved=latest_time(fluid)
        if abs(t-meta["final_time_s"])>1e-9:
            raise RuntimeError("Fluid latest time not equal accepted preCICE time")
        quality=quality_from_log(work/"fluid.log",t,meta["parent_time_s"]+DT,
                                 allow_transient=(stage==0))
        force_continuity=(validate_cross_job_force(Path(meta["parent_run"]),
                           work/"fluid.log") if stage>=1 else None)
        accepted_force_continuity=(validate_accepted_force_continuity(
            Path(meta["parent_run"]),
            solid/"precice-Solid-watchintegral-Interface-Integral.log",DT,
            continuous_reference_log=(
                base/"three-day-proven/long-job-91543/runs/hpcc-implicit-002/"
                     "solid/precice-Solid-watchintegral-Interface-Integral.log"
                if stage==1 else None),
            absolute_restart_time_s=meta["parent_time_s"])
            if stage>=1 else None)
        if not (solid/"seagrass.rout").is_file() or not (solid/"kinematic_state.bin").is_file():
            raise RuntimeError("New structural continuation checkpoints missing")
        if (sha(solid/"seagrass.rout")==meta["solid_input_rin_sha256"] or
            sha(solid/"kinematic_state.bin")==meta["solid_input_kinematic_sha256"]):
            raise RuntimeError("Structural restart/kinematic state did not advance")
        check=check_mesh(fluid,work)
        wall=time.monotonic()-start_wall
        verdict=("FSI_LONG_SEGMENT_PASS_WITH_RESTART_TRANSIENT"
                 if quality["first_window_restart_transient_exception"]
                 else "FSI_LONG_SEGMENT_PASS")
        result={
           "status":verdict,"stage":stage,
           "parent_job":meta["parent_job"],
           "parent_time_s":meta["parent_time_s"],
           "read_restart_step":meta["read_restart_step"],
           "final_time_s":t,"accepted_windows":meta["accepted_windows"],
           "coupling_iterations":sum(r[2] for r in iters),
           "max_coupling_iterations_per_window":max(r[2] for r in iters),
           "participant_exit_codes":exits,
           "quality":quality,"native_terminal_mesh":check,
           "cross_job_initial_force_continuity":force_continuity,
           "cross_job_accepted_force_continuity":accepted_force_continuity,
           "wall_s":wall,"s_per_window":wall/meta["accepted_windows"],
           "solid_rout_sha256":sha(solid/"seagrass.rout"),
           "solid_kinematic_sha256":sha(solid/"kinematic_state.bin"),
           "scientific_two_periods_verified":False,
           "startup_meshCo_exception_recorded":quality["first_window_restart_transient_exception"],
           "full_meshCo_threshold_met":not quality["first_window_restart_transient_exception"],
           "note":"Approved computation only through stated physical time; two wet oscillations are not inferred."
        }
        jwrite(work/"FSI_SEGMENT_RESULT.json",result)
        state.update(status=verdict,accepted_time_s=t)
        jwrite(work/"STATE.json",state)
        print(verdict,json.dumps({k:result[k] for k in
            ("stage","final_time_s","accepted_windows","wall_s","s_per_window")}),flush=True)
    except BaseException as exc:
        state.update(status="FSI_LONG_SEGMENT_FAILED",failure=str(exc),
                     elapsed_s=time.monotonic()-start_wall)
        jwrite(work/"STATE.json",state)
        print("FSI_LONG_SEGMENT_FAILED",str(exc),flush=True)
        traceback.print_exc()
        raise
    finally:
        for p in procs.values():
            if p.poll() is None:
                try:os.killpg(p.pid,signal.SIGTERM)
                except ProcessLookupError:pass
        for p in procs.values():
            try:p.wait(timeout=20)
            except subprocess.TimeoutExpired:
                try:os.killpg(p.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                p.wait()
        for f in handles.values():f.close()

def self_test():
    assert segment_folder(1)=="segment-A"
    assert segment_folder(2)=="segment-B"
    assert segment_folder(12)=="segment-L"
    try:segment_folder(13)
    except RuntimeError:pass
    else:raise AssertionError("Invalid segment allowed")
    assert choose_windows(0,240,180)==240
    assert choose_windows(1,960,150)==960
    assert choose_windows(1,960,300)==(int((60*3600)/(300*1.35))//80)*80
    assert round((.0025+240*DT)/DT)==260
    assert math.gcd(260,80)==20
    source="*RESTART,READ,STEP=1\n*STEP\n*DYNAMIC,DIRECT\n0.000125, 0.00125\n*RESTART,WRITE,FREQUENCY=1,OVERLAY\n*END STEP\n"
    changed=exact(r"(?im)^(\s*\*RESTART\s*,\s*READ\s*,\s*STEP=)\d+",
                  lambda m:m.group(1)+"2",source,"restart self-test")
    assert changed.startswith("*RESTART,READ,STEP=2")
    # No blanket Courant relaxation: all >.5 excursions must be in first
    # restart window, whose final logged value must be <=.5.
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        log=Path(d)/"fluid.log"
        start_t=.0325+.000125
        end_t=start_t+.000125
        def guard(t):
            return (f"SEAGRASS_MESH_GUARD time={t:.9f} minVolume=2.5e-11 "
                    "concave=0 qualityFailed=0 skewFailed=0 orthFailed=0 tetFailed=0\n")
        # Real test log with 2 windows, including an early rejected step.
        log.write_text(
          f"Time = {start_t:.9f}\n"
          "Courant Number mean: 0.01 max: 0.42\n"
          "Mesh Courant Number mean: 0.001 max: 4.18\n"
          "Mesh Courant Number mean: 0.001 max: 0.25\n"
          +guard(start_t)+
          f"Time = {end_t:.9f}\n"
          "Courant Number mean: 0.01 max: 0.42\n"
          "Mesh Courant Number mean: 0.001 max: 0.24\n"
          +guard(end_t))
        try:
            quality_from_log(log,end_t,start_t)
        except RuntimeError as e:
            assert "UNQUALIFIED_CROSS_JOB_MESH_COURANT_SPIKE" in str(e)
        else:
            raise AssertionError("Cross-job mesh Co excursion incorrectly approved")
        good=quality_from_log(log,end_t,start_t,allow_transient=True)
        assert good["first_window_restart_transient_exception"]
        assert good["later_window_meshCo_max"]==.24
        log.write_text(log.read_text()+f"Time = {end_t:.9f}\n"
                       "Mesh Courant Number mean: 0.001 max: 2.0\n")
        try:quality_from_log(log,end_t,start_t)
        except RuntimeError:pass
        else:raise AssertionError("Later Courant excursion was accepted")
    with tempfile.TemporaryDirectory() as d:
        root=Path(d)
        (root/"solid").mkdir()
        (root/"solid/precice-Solid-watchintegral-Interface-Integral.log").write_text(
            "Time Fx Fy Fz\n0.030 0.0176638208 0 0\n")
        force_log=root/"fluid.log"
        force_log.write_text(
            "Time = 0.032625\nforces bladeForces write:\n"
            "Total : (11.515278323918 0 0)\n")
        diagnostic=validate_cross_job_force(root,force_log)
        assert diagnostic["status"]=="PROVISIONAL_NOT_COMPARABLE_TO_ACCEPTED"
        assert diagnostic["used_as_pass_fail_gate"] is False
        assert diagnostic["first_provisional_Fx_N"]>11
        # First provisional force is not the criterion; only accepted data
        # can approve a cross-job continuation.
        force_log.write_text(
            "Time = 0.032625\nforces bladeForces write:\n"
            "Total : (0.018 0 0)\n")
        diagnostic=validate_cross_job_force(root,force_log)
        assert diagnostic["first_provisional_Fx_N"]==.018
        assert diagnostic["used_as_pass_fail_gate"] is False
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)
        source=root/"source";staged=root/"staged"
        for rank in range(EXPECTED_RANKS):
            for label,which in (("source",source),("staged",staged)):
                for stamp in ("0.03","0.0325"):
                    (which/f"fluid/processor{rank}"/stamp).mkdir(parents=True)
        counts=verify_staged_fluid_history(source,staged,1)
        assert all(item["source_time_folders"]==2 for item in counts.values())
        (staged/"fluid/processor0/0.03").rmdir()
        try:verify_staged_fluid_history(source,staged,1)
        except RuntimeError as e:
            assert "OUR_RESTART_HISTORY_COPY_FAILED" in str(e)
        else:raise AssertionError("Discarded prior time directory not detected")
        old=source/"solid"
        old.mkdir()
        (old/"precice-Solid-watchintegral-Interface-Integral.log").write_text(
            "Time Fx Fy Fz\n0.030 0.0176638208 0 0\n")
        watch=root/"accepted-watch.log"
        watch.write_text(
            "Time Fx Fy Fz\n0 0.0176638208 0 0\n"
            "0.000125 0.0721967891 0 0\n"
            "0.00025 -0.120743427 0 0\n")
        try:validate_accepted_force_continuity(source,watch,DT)
        except RuntimeError as e:
            assert "UNPHYSICAL_CROSS_JOB_ACCEPTED_FORCE" in str(e)
        else:raise AssertionError("91767 accepted forces incorrectly approved")
        watch.write_text(
            "Time Fx Fy Fz\n0 0.0176638208 0 0\n"
            "0.000125 0.0178807774 0 0\n"
            "0.00025 0.0181010198 0 0\n")
        audit=validate_accepted_force_continuity(source,watch,DT)
        assert len(audit["first_two_windows"])==2
        reference=root/"continuous-91543-watch.log"
        reference.write_text(
            "Time Fx Fy Fz\n"
            "0.030125 0.0178807774 0 0\n"
            "0.030250 0.0181010198 0 0\n")
        confirmed=validate_accepted_force_continuity(
            source,watch,DT,continuous_reference_log=reference,
            absolute_restart_time_s=.0325)
        assert confirmed["continuous_reference_checked"]
        assert all(x["relative_error_to_continuous"]<.01
                   for x in confirmed["first_two_windows"])
        # A plausible source-vs-next force can still disagree badly with
        # uninterrupted same-time reference. Old code falsely passed this.
        reference.write_text(
            "Time Fx Fy Fz\n"
            "0.030125 0.0300000 0 0\n"
            "0.030250 0.0300000 0 0\n")
        try:validate_accepted_force_continuity(
            source,watch,DT,continuous_reference_log=reference,
            absolute_restart_time_s=.0325)
        except RuntimeError as e:
            assert "UNPHYSICAL_CROSS_JOB_VS_CONTINUOUS" in str(e)
        else:raise AssertionError("Accepted scientific mismatch vs 91543")
        reference.write_text("Time Fx\n0.030125 0.018\n")
        try:validate_accepted_force_continuity(
            source,watch,DT,continuous_reference_log=reference,
            absolute_restart_time_s=.0325)
        except RuntimeError as e:
            assert "CONTINUOUS_REFERENCE_MISSING" in str(e)
        else:raise AssertionError("Accepted missing continuous second window")
    print("FSI_CLEAN_PRODUCTION_SELF_TEST_PASS")

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base",type=Path,default=Path.home()/"hpcc-fsi")
    p.add_argument("--stage",type=int,required=False,default=0)
    p.add_argument("--previous-job",type=int)
    p.add_argument("--chain-root",type=Path,help="Private named production chain root")
    p.add_argument("--max-windows",type=int,default=960)
    p.add_argument("--work",type=Path)
    p.add_argument("--preflight-only",action="store_true")
    p.add_argument("--run",action="store_true")
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--timeout-seconds",type=int,default=66*3600)
    a=p.parse_args()
    if a.self_test:self_test();return
    if not 1<=a.stage<=12 and not a.self_test:
        raise RuntimeError("Clean production supports only stages 1..12")
    if a.chain_root is None:
        raise RuntimeError("--chain-root required in clean production")
    chain_root=a.chain_root.expanduser().resolve()
    if not chain_root.is_relative_to(Path.home()/"hpcc-fsi"):
        raise RuntimeError("Chain root must be within hpcc-fsi")
    if a.stage==1 and a.previous_job!=91006:
        raise RuntimeError("Clean source must be previously certified 91006")

    if a.run==a.preflight_only:
        p.error("choose exactly one --run or --preflight-only")

    base=a.base.expanduser().resolve(strict=True)
    if a.preflight_only:
        prev,src,t,saved,step,perwin=source_for(base,a.stage,a.previous_job,chain_root)
        n=choose_windows(a.stage,a.max_windows,perwin)
        print("FSI_LONG_CHAIN_PREFLIGHT_PASS",f"stage={a.stage}",f"from={t}",
              f"to={t+n*DT}",f"windows={n}",f"step={step}")
        print("NO_SLURM_NO_SOLVER_NO_MUTATION")
        return
    if a.work is None:p.error("--run needs --work")
    target=chain_root/segment_folder(a.stage)
    if a.work.expanduser().resolve()!=target:
        raise RuntimeError(f"Clean production work must be exactly {target}")
    if not chain_root.is_dir():
        raise RuntimeError("Chain root missing, must be created by submit script")
    run(base,a.stage,a.previous_job,target,
        a.max_windows,a.timeout_seconds,chain_root)

if __name__=="__main__":
    sys.exit(main())
