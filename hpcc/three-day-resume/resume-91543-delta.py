#!/usr/bin/env python3
"""Continue UNINTERRUPTED THREE-DAY FSI job 91543 using validated Delta adapter.

Original case is absolute Displacement; patch reference frame and
DisplacementDelta only in a fresh private cloned run (same exact transform
used for successfully validated G0). Never overwrite original or full backup.
Beyond 91543's endpoint there is NO uninterrupted same-time reference:
only native mesh, convergence, checkpoint, accepted force continuity and
finite Delta guards are scientifically assertable, NOT 1% reference accuracy.
Each segment uses original unchanged physics and native OpenFOAM/CCX runner.
"""
import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import traceback

DT=.000125
ORIGIN=.0025
CHECKPOINT_SOURCE_JOB=92264
WATCH="precice-Solid-watchintegral-Interface-Integral.log"


def load_core(path):
    spec=importlib.util.spec_from_file_location("fsi_delta_continuation_core",path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Missing isolated continuation core")
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_json(path):
    if not path.is_file():
        raise RuntimeError(f"MISSING_REQUIRED_RESULT {path}")
    return json.loads(path.read_text())


def load_inspector():
    path=Path(os.environ.get("FSI_91543_INSPECTOR",
        str(Path(__file__).resolve().with_name("inspect-91543.py"))))
    sp=importlib.util.spec_from_file_location("fsi_91543_inspector",path)
    if sp is None or sp.loader is None:raise RuntimeError("91543_INSPECTOR_MISSING")
    m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
    return m

def load_original_delta_patcher():
    path=Path(os.environ.get("FSI_ORIGINAL_DELTA_PATCH",
        str(Path(__file__).resolve().with_name("try-incremental-displacement-restart.py"))))
    sp=importlib.util.spec_from_file_location("fsi_validated_original_delta_patch",path)
    if sp is None or sp.loader is None:raise RuntimeError("VALIDATED_DELTA_PATCH_MISSING")
    m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
    return m

def verified_source(source_work,core,base,diagnostic_g2=False):
    if diagnostic_g2:raise RuntimeError("G2_DIAGNOSTIC_MODE_FORBIDDEN")
    source_work=source_work.resolve(strict=True)
    original=(base/"three-day-proven/long-job-91543").resolve()
    descendants=(base/"three-day-resume-20261119/jobs").resolve()
    original_seed=source_work==original
    if not original_seed and source_work.parent!=descendants:
        raise RuntimeError("RESUME_PARENT_MUST_BE_ORIGINAL_91543_OR_ACCEPTED_CHILD")
    source=source_work/"runs/hpcc-implicit-002"
    if not source.is_dir():raise RuntimeError("RESTART_SOURCE_MISSING")
    physical,times=core.latest_time(source/"fluid")
    if original_seed:
        evidence=load_inspector().inspect(base)
        if not evidence["complete_fluid_MPI_time_aligned"]:
            raise RuntimeError("91543_MPI_CHECKPOINTS_NOT_ALIGNED")
        if not evidence["checkpoint_time_matches_latest_accepted_watch"]:
            raise RuntimeError("91543_FLUID_AND_ACCEPTED_SOLID_TIMES_NOT_ALIGNED")
        req=evidence["original_structural_restart_state"]
        if not all(req[k] for k in ("rout_exists",
                "persistent_kinematic_state_exists",
                "original_reference_coords_exists")):
            raise RuntimeError("91543_SOLID_STATE_INCOMPLETE")
        proto=evidence["original_protocol"]
        if not all(proto[k] for k in ("fluid_absolute_Displacement",
                 "fluid_restartFromDeformed_true",
                 "solid_absolute_Displacement",
                 "xml_absolute_Displacement",
                 "xml_implicit_coupling")):
            raise RuntimeError("91543_ORIGINAL_ABSOLUTE_PROTOCOL_UNEXPECTED")
        current=int(req["restart_step_read_in_original_inp"])
        # Native PASS is strongest; a synchronized intermediate checkpoint
        # can also be eligible after explicit full backup, but not guaranteed
        # scientifically identical. Runtime strict ALE/accepted-state guards
        # can reject a bad resumed first coupling window.
        parent={"status":"ORIGINAL_91543_VERIFIED_SYNCHRONIZED_SAVED_CHECKPOINT",
                "final_time_s":physical,"accepted_windows":evidence["accepted_watch_rows"]}
    else:
        marker=read_json(source_work/"DELTA_CONTINUATION_RESULT.json")
        native=read_json(source_work/"FSI_SEGMENT_RESULT.json")
        if marker.get("status")!="91543_CONTINUATION_NATIVE_GUARDS_PASS":
            raise RuntimeError("PREVIOUS_CONTINUATION_NOT_ACCEPTED")
        if native.get("status")!="FSI_LONG_SEGMENT_PASS" or native.get("participant_exit_codes")!={"fluid":0,"solid":0}:
            raise RuntimeError("PREVIOUS_NATIVE_FSI_NOT_PASS")
        if native.get("native_terminal_mesh",{}).get("status")!="PASS":
            raise RuntimeError("PREVIOUS_TERMINAL_MESH_NOT_PASS")
        if abs(float(native["final_time_s"])-physical)>1e-9:
            raise RuntimeError("PREVIOUS_FLUID_CHECKPOINT_TIME_MISMATCH")
        if not marker.get("native_mechanical_pass") or marker.get("exception") is not None:
            raise RuntimeError("PREVIOUS_NATIVE_GUARDS_MISSING")
        if not (source/"restart_reference/Solid-Mesh.coords").is_file():
            raise RuntimeError("PREVIOUS_ORIGINAL_SOLID_COORDS_MISSING")
        foam=(source/"fluid/system/preciceDict").read_text()
        xml=(source/"precice-config.xml").read_text()
        yaml=(source/"solid/config.yml").read_text()
        if not ("restartFromDeformed false;" in foam and
                "readData (DisplacementDelta);" in foam and
                'name="DisplacementDelta"' in xml and
                "DisplacementDelta" in yaml):
            raise RuntimeError("PREVIOUS_DELTA_PROTOCOL_MISMATCH")
        deck=(source/"solid/seagrass.inp").read_text()
        mat=re.search(r"(?im)^\s*\*RESTART\s*,\s*READ\s*,\s*STEP=(\d+)",deck)
        if mat is None:raise RuntimeError("PREVIOUS_SOLID_STEP_MISSING")
        current=int(mat.group(1))
        parent=native
    for name in ("seagrass.rout","kinematic_state.bin"):
        if not (source/"solid"/name).is_file():
            raise RuntimeError("STRUCTURAL_BINARY_RESTART_MISSING_"+name)
    if not (source/"restart_reference/Solid-Mesh.coords").is_file():
        raise RuntimeError("ORIGINAL_SOLID_REFERENCE_COORDS_MISSING")
    for i in range(8):
        p=source/f"fluid/processor{i}"
        if len(core.numeric_time_names(p))<2:
            raise RuntimeError(f"MISSING_SECOND_TIME_DIR_RANK_{i}")
    return source,physical,current+1,parent

def build_private_stage(core,base,source_work,destination,windows,source_job,diagnostic_g2=False):
    source,t0,step,parent=verified_source(source_work,core,base,diagnostic_g2)
    if diagnostic_g2 or not 2<=windows<=1500:
        raise RuntimeError("CONTINUATION_WINDOWS_OUTSIDE_2_TO_1500")
    t1=t0+windows*DT
    destination=destination.resolve()
    base=base.resolve()
    if not destination.is_relative_to(base) or destination.exists():
        raise RuntimeError("Destination must be a fresh isolated path under hpcc-fsi")
    for original in (source,source_work,
                     base/"seagrass-implicit-20261111",
                     base/"three-day-proven/long-job-91543",
                     base/"fsi-long-stage0-job91006"):
        if destination==original or destination in original.parents or original in destination.parents:
            raise RuntimeError("Output overlaps immutable original or source")
    destination.mkdir(parents=True)
    dst=destination/"runs/hpcc-implicit-002"
    dst.parent.mkdir()
    # Copy only last THREE time directories from each ORIGINAL rank; the
    # 3-day source itself was fully SHA-256 backed up, never pruned.
    selected={}
    for rank in range(8):
        p=source/f"fluid/processor{rank}"
        names=core.numeric_time_names(p)
        if len(names)<2:raise RuntimeError("SOURCE_CHECKPOINT_HISTORY_INSUFFICIENT")
        selected[f"processor{rank}"]=set(names[-3:])
    def ignore(parent,names):
        p=Path(parent)
        if p.name in selected and p.parent.name=="fluid":
            return [n for n in names if n not in selected[p.name]
                    and n in set(core.numeric_time_names(p))]
        if p.name in ("fluid","solid"):
            return [n for n in names if n=="precice-profiling"]
        return []
    shutil.copytree(source,dst,ignore=ignore,symlinks=False)
    for rank in range(8):
        core.latest_time(dst/"fluid") # verify actual MPI terminal once copied
        break
    for p in dst.rglob("precice-*"):
        if p.is_file() and p.suffix in (".log",".json",".csv"):
            p.unlink()
    for name in ("seagrass.dat","seagrass.cvg","seagrass.frd",
                 "seagrass.sta","spooles.out"):
        (dst/"solid"/name).unlink(missing_ok=True)
    for p in dst.glob("*.log"):
        p.unlink()
    solid=dst/"solid"
    rout_sha=core.sha(solid/"seagrass.rout")
    kin_sha=core.sha(solid/"kinematic_state.bin")
    shutil.copy2(solid/"seagrass.rout",solid/"seagrass.rin")
    shutil.copy2(solid/"kinematic_state.bin",solid/"kinematic_state.input.bin")
    (solid/"seagrass.rout").unlink()
    (solid/"kinematic_state.bin").unlink()
    deck=solid/"seagrass.inp"
    txt=deck.read_text()
    txt=core.exact(r"(?im)^(\s*\*RESTART\s*,\s*READ\s*,\s*STEP=)\d+",
                   lambda m:m.group(1)+str(step),txt,"CalculiX structural step")
    def dynamic(m):
        parts=m.group(2).split(",")
        if not math.isclose(float(parts[0]),DT,abs_tol=1e-12):
            raise RuntimeError("Incompatible structural deltaT")
        parts[1]=f" {windows*DT:.12g}"
        return m.group(1)+",".join(parts)
    txt=core.exact(r"(?im)^(\s*\*DYNAMIC\s*,\s*DIRECT[^\n]*\n)([^\n]+)",
                   dynamic,txt,"CalculiX stage duration")
    if not re.search(r"(?im)^\s*\*RESTART\s*,\s*WRITE\s*,\s*FREQUENCY=1\s*,\s*OVERLAY",txt):
        raise RuntimeError("No new CalculiX .rout requested")
    deck.write_text(txt)
    control=dst/"fluid/system/controlDict"
    conf=control.read_text()
    if not re.search(r"\bstartFrom\s+latestTime\s*;",conf):
        raise RuntimeError("Fluid must restart from latestTime")
    conf=core.exact(r"(?m)(?<![A-Za-z0-9_])(endTime\s+)([-+.\deE]+)(\s*;)",
                    lambda m:m.group(1)+f"{t1:.12g}"+m.group(3),
                    conf,"Fluid target physical time")
    end_index=round(t1/DT)
    if abs(t1/DT-end_index)>1e-7:
        raise RuntimeError("Fluid terminal time is not integer deltaT")
    write_every=math.gcd(end_index,80)
    conf,count=re.subn(r"(writeControl\s+timeStep\s*;\s*writeInterval\s+)\d+(\s*;)",
                       lambda m:m.group(1)+str(write_every)+m.group(2),conf)
    if count!=4:
        raise RuntimeError(f"Expected four fluid output intervals; found {count}")
    conf=core.exact(r"(purgeWrite\s+)\d+(\s*;)",r"\g<1>4\2",
                    conf,"Keep four latest MPI restart checkpoints")
    control.write_text(conf)
    # The uninterrupted 91543 case uses ABSOLUTE Displacement. Apply the
    # exact 92264-verified frame+Delta transform in this PRIVATE COPY only.
    original_seed=source_work.resolve()==(base/"three-day-proven/long-job-91543").resolve()
    xml=dst/"precice-config.xml"
    if original_seed:
        patch=load_original_delta_patcher()
        foam_path=dst/"fluid/system/preciceDict"
        solid_yaml=dst/"solid/config.yml"
        foam_path.write_text(patch.patch_foam(foam_path.read_text()))
        xml.write_text(patch.patch_xml(xml.read_text()))
        solid_yaml.write_text(patch.patch_solid_yaml(solid_yaml.read_text()))
    doc=xml.read_text()
    doc=core.exact(r'(<max-time value=")[\d.eE+-]+(")',
                   lambda m:m.group(1)+f"{windows*DT:.12g}"+m.group(2),
                   doc,"New preCICE session duration")
    xml.write_text(doc)
    metadata={
        "status":"STAGED_LONG_CHAIN_PRODUCTION",
        "stage":1,  # legacy core's numerical quality stage path
        "parent_job":int(source_job),
        "parent_run":str(source),
        "parent_time_s":t0,
        "read_restart_step":step,
        "accepted_windows":windows,
        "final_time_s":t1,
        "solid_input_rin_sha256":rout_sha,
        "solid_input_kinematic_sha256":kin_sha,
        "no_physical_parameters_modified":True,
        "mpi_fluid":8,"omp_solid":4,"iqn_reuse":15,
        "dt_s":DT,"dual_convergence_tol":1e-5,
        "fluid_write_interval_steps":write_every,
        "delta_protocol_inherited_not_repatched":True,
        "initial_force_only":True,"mesh_registration_original_reference":True,
        "parent_stage_status":parent["status"],
        "PARENT_IS_ORIGINAL_91543":original_seed,
        "SOURCE_ORIGINAL_FULL_BACKUP_REQUIRED":True,
        "NO_FUTURE_UNINTERRUPTED_REFERENCE":True,
        "PRODUCTION_APPROVED":False,
        "DO_NOT_AUTO_CHAIN":True
    }
    core.jwrite(destination/"FSI_SEGMENT_STAGE.json",metadata)
    return dst,metadata


def watch(path):
    rows={}
    if not path.is_file():
        raise RuntimeError(f"Missing watch integral {path}")
    for line in path.read_text(errors="replace").splitlines():
        p=line.split()
        if len(p)<7:continue
        try:vals=[float(x) for x in p[:7]]
        except ValueError:continue
        if all(math.isfinite(x) for x in vals):
            rows[round(vals[0],9)]=vals[1:]
    return rows


def scientific_gate(base,source_work,work,start,windows):
    """Native/accepted continuity checks, NOT same-time reference accuracy."""
    previous=watch(source_work/"runs/hpcc-implicit-002/solid"/WATCH)
    rows=watch(work/"runs/hpcc-implicit-002/solid"/WATCH)
    source_last=previous[max(previous)]
    init=rows.get(0.)
    if init is None or abs(init[0]-source_last[0])>max(1e-9,abs(source_last[0])*1e-7):
        raise RuntimeError("INITIAL_ACCEPTED_FORCE_NOT_RESTORED")
    if any(abs(v)>1e-11 for v in init[3:]):
        raise RuntimeError("INITIAL_DISPLACEMENT_DELTA_NOT_ZERO")
    data=[]
    max_force_step_change=0.
    prevFx=init[0]
    for n in range(1,windows+1):
        rel=round(n*DT,9)
        val=rows.get(rel)
        if val is None or len(val)!=6 or not all(math.isfinite(x) for x in val):
            raise RuntimeError(f"ACCEPTED_FINITE_FORCE_AND_DELTA_MISSING_WINDOW_{n}")
        # Gross-jump guard only; no claim of physical reference fidelity.
        jump=abs(val[0]-prevFx)/max(abs(prevFx),0.001)
        if jump>0.2:
            raise RuntimeError(f"ABRUPT_ACCEPTED_FX_JUMP_WINDOW_{n}_{jump}")
        max_force_step_change=max(max_force_step_change,jump)
        if any(abs(v)>1000 for v in val):
            raise RuntimeError(f"ACCEPTED_FORCE_OR_INTEGRAL_OUT_OF_FINITE_RANGE_{n}")
        data.append({"n":n,"physical_t":start+rel,"Fx":val[0],
                     "Delta0":val[3],"Delta2":val[5],
                     "Fx_jump_ratio_to_previous":jump})
        prevFx=val[0]
    return {
        "status":"PASS_NATIVE_CONTINUITY_NO_FUTURE_REFERENCE",
        "not_a_same_time_1pct_science_comparison":True,
        "accepted":data,
        "max_Fx_step_jump_ratio":max_force_step_change,
        "source_initial_force_N":source_last[0],
        "first_new_force_N":init[0],
        "initial_delta_zero":True,
    }

def first_native_meshco(path, t):
    """First native MeshCo in the target physical step, not settled value."""
    if not path.is_file():
        return None
    active=False
    with path.open(errors="replace") as stream:
        for line in stream:
            m=re.match(r"^\s*Time\s*=\s*([0-9.eE+-]+)\s*$",line)
            if m:
                when=float(m.group(1))
                if active or when>t+1e-8:
                    return None
                active=abs(when-t)<5e-10
            elif active and "Mesh Courant Number mean:" in line:
                m=re.search(r"\bmax:\s*([0-9.eE+-]+)",line)
                if m:
                    value=float(m.group(1))
                    return value if math.isfinite(value) and value>=0 else None
    return None


def meshco_reference_gate(base,work,start):
    value=first_native_meshco(work/"fluid.log",start+DT)
    return {
       "physical_time_s":start+DT,
       "candidate_first_meshco":value,
       "same_time_reference_unavailable_after_91543":True,
       "first_native_meshco_pass":value is not None and 0<=value<=.5
    }

def run_trial(base,source_work,work,windows,core_path,source_job,diagnostic_g2=False):
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("Compute node Slurm allocation required")
    core=load_core(core_path)
    # Fail-closed source before any files created.
    source,start,step,parent=verified_source(source_work,core,base,diagnostic_g2)
    if diagnostic_g2 or not 2<=windows<=1500:
        raise RuntimeError("LONG_PRODUCTION_WINDOW_COUNT_INVALID")
    if source_work.resolve()==(base/"three-day-proven/long-job-91543").resolve() and source_job!=91543:
        raise RuntimeError("FIRST_CONTINUATION_SOURCE_MUST_BE_91543")
    if work.exists():
        raise RuntimeError("Work already exists")
    def staged(_base,_stage,_job,_dest,_n,_chain_root=None):
        return build_private_stage(core,base,source_work,work,windows,source_job,diagnostic_g2)
    original=core.stage_inputs
    original_accepted=core.validate_accepted_force_continuity
    def no_future_reference(source,solid_log,dt,**kwargs):
        kwargs["continuous_reference_log"]=None
        kwargs["absolute_restart_time_s"]=None
        return original_accepted(source,solid_log,dt,**kwargs)
    core.stage_inputs=staged
    core.validate_accepted_force_continuity=no_future_reference
    error=None
    try:
        core.run(base,1,int(source_job),work,windows,230400,base/"seagrass-fsi-mainline")
    except BaseException as e:
        error=repr(e)
        traceback.print_exc()
    finally:
        core.stage_inputs=original
        core.validate_accepted_force_continuity=original_accepted
    status_path=work/"FSI_SEGMENT_RESULT.json"
    native=read_json(status_path) if status_path.is_file() else None
    first_meshco=meshco_reference_gate(base,work,start)
    validation=None
    try:
        validation=scientific_gate(base,source_work,work,start,windows)
    except Exception as e:
        if error is None:error=repr(e)
    native_ok=bool(
        error is None and native is not None and validation is not None
        and native.get("status")=="FSI_LONG_SEGMENT_PASS"
        and native.get("accepted_windows")==windows
        and native.get("participant_exit_codes")=={"fluid":0,"solid":0}
        and native.get("native_terminal_mesh",{}).get("status")=="PASS"
        and first_meshco["first_native_meshco_pass"]
    )
    # Scientific reference 91543 ENDS at source; never fabricate future Fx.
    ok=bool(native_ok and validation.get("status")==
            "PASS_NATIVE_CONTINUITY_NO_FUTURE_REFERENCE")
    verdict="91543_CONTINUATION_NATIVE_GUARDS_PASS" if ok else "91543_CONTINUATION_FAIL"
    report={
        "status":verdict,
        "parent_source":str(source_work),
        "start_t":start,"end_t":start+windows*DT,
        "windows":windows,"next_structural_step":step,
        "native_result":native,"accepted_continuity_guards":validation,
        "first_native_meshco_no_external_reference":first_meshco,
        "exception":error,
        "native_mechanical_pass":native_ok,
        "same_time_external_scientific_reference_available":False,
        "native_and_accepted_consistency_only":True,
        "production_approved":False,
        "NEVER_AUTO_QUEUE_NEXT_STAGE":True,
    }
    if work.is_dir():
        (work/"DELTA_CONTINUATION_RESULT.json").write_text(
            json.dumps(report,indent=2,ensure_ascii=False)+"\n")
    print(report["status"],"window_count",windows,
          "native_continuity",validation.get("status") if validation else None,
          "exception",error,flush=True)
    if not ok:
        raise SystemExit(3)


def self_test():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        root=Path(d)
        source=root/"parent/runs/hpcc-implicit-002/solid"
        new=root/"new/runs/hpcc-implicit-002/solid"
        source.mkdir(parents=True);new.mkdir(parents=True)
        (source/WATCH).write_text("Time Force0 Force1 Force2 Displacement0 Displacement1 Displacement2\n"
                 "0.2 0.02 0 0 40 0 0\n")
        (new/WATCH).write_text("Time Force0 Force1 Force2 DisplacementDelta0 DisplacementDelta1 DisplacementDelta2\n"
                 "0 0.02 0 0 0 0 0\n"
                 "0.000125 0.021 0 0 0.1 0 -0.001\n"
                 "0.00025 0.022 0 0 0.099 0 -0.001\n")
        q=scientific_gate(root,root/"parent",root/"new",.2025,2)
        assert q["status"]=="PASS_NATIVE_CONTINUITY_NO_FUTURE_REFERENCE"
        assert q["max_Fx_step_jump_ratio"]<.2
    print("91543_REAL_LONG_CONTINUATION_NATIVE_GUARDS_OFFLINE_PASS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--base",type=Path,default=Path.home()/"hpcc-fsi")
    p.add_argument("--core",type=Path)
    p.add_argument("--source-work",type=Path)
    p.add_argument("--source-job",type=int)
    p.add_argument("--work",type=Path)
    p.add_argument("--windows",type=int,default=480)
    p.add_argument("--preflight",action="store_true")
    p.add_argument("--run",action="store_true")
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--diagnostic-g2",action="store_true",help=argparse.SUPPRESS)
    args=p.parse_args()
    if args.self_test:
        return self_test()
    if args.source_work is None or args.core is None or args.source_job is None:
        p.error("Supply --source-work, --source-job and --core")
    base=args.base.expanduser().resolve(strict=True)
    core_path=args.core.expanduser().resolve(strict=True)
    os.environ["FSI_DELTA_CORE_PATH"]=str(core_path)
    core=load_core(core_path)
    source_work=args.source_work.expanduser().resolve(strict=True)
    if args.diagnostic_g2 or not 2<=args.windows<=1500:
        p.error("2..1500 windows; native/accepted guards, no imaginary future reference")
    source,start,step,outcome=verified_source(source_work,core,base,args.diagnostic_g2)
    if args.preflight:
        print("DELTA_CONTINUATION_PREFLIGHT_PASS",
              "source",source_work,"from",start,
              "to",start+args.windows*DT,
              "structural_restart_step",step,
              "windows",args.windows,
              "no_same_time_reference_after_source",True,
              "NO_SBATCH_NO_SOURCE_WRITES")
        return
    if not args.run or args.work is None:
        p.error("Supply --run --work fresh_output or --preflight")
    run_trial(base,source_work,args.work.expanduser().resolve(),
              args.windows,args.core.expanduser().resolve(strict=True),
              args.source_job,args.diagnostic_g2)


if __name__=="__main__":
    main()
