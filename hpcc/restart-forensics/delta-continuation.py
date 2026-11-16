#!/usr/bin/env python3
"""Reusable, FAIL-CLOSED short-stage cross-job continuation after delta FSI.

Consumes a verified completed DisplacementDelta case, NOT original 91006 and
NOT a source with absolute Displacement exchange.

Preflight and self-test are read-only. Real run needs Slurm compute allocation.
Stages only 2 or 20 windows until explicit separate long-production qualification.
No directory overwrite, no automatic subsequent job. Retains original source.
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


def verified_source(source_work, core, base):
    """Only completed, accepted cases with the same verified delta protocol."""
    source_work=source_work.resolve(strict=True)
    if source_work.name.startswith("trial-") and source_work.name=="trial-92264":
        marker=read_json(source_work/"INCREMENTAL_DISPLACEMENT_RESULT.json")
        if marker.get("status")!="INCREMENTAL_DISPLACEMENT_TWO_WINDOW_PASS":
            raise RuntimeError("92264 TWO WINDOW PROOF NOT PASSED")
    else:
        marker=read_json(source_work/"DELTA_CONTINUATION_RESULT.json")
        if marker.get("status")!="DELTA_CONTINUATION_SHORT_STAGE_PASS":
            raise RuntimeError("PARENT DELTA CONTINUATION NOT APPROVED")
    outcome=read_json(source_work/"FSI_SEGMENT_RESULT.json")
    if outcome.get("status")!="FSI_LONG_SEGMENT_PASS":
        raise RuntimeError("Source native coupling was not accepted")
    if outcome.get("participant_exit_codes")!={"fluid":0,"solid":0}:
        raise RuntimeError("Source participant exit mismatch")
    if outcome.get("native_terminal_mesh",{}).get("status")!="PASS":
        raise RuntimeError("Source native terminal mesh was not certified")
    if outcome.get("accepted_windows",0)<2:
        raise RuntimeError("Source has fewer than 2 accepted windows")
    source=source_work/"runs/hpcc-implicit-002"
    if not source.is_dir():
        raise RuntimeError("Source native run missing")
    physical,times=core.latest_time(source/"fluid")
    declared=float(outcome["final_time_s"])
    if abs(physical-declared)>1e-9:
        raise RuntimeError(f"Source physical checkpoint mismatch {physical} {declared}")
    start=read_json(source_work/"FSI_SEGMENT_STAGE.json")
    if "read_restart_step" not in start:
        raise RuntimeError("Source structural restart step metadata missing")
    current_step=int(start["read_restart_step"])
    if current_step<3:
        raise RuntimeError("Structural restart chain step too early")
    deck=(source/"solid/seagrass.inp").read_text()
    got=re.search(r"(?im)^\s*\*RESTART\s*,\s*READ\s*,\s*STEP=(\d+)",deck)
    if got is None or int(got.group(1))!=current_step:
        raise RuntimeError("Structural .inp restart chain mismatch")
    if not (source/"solid/seagrass.rout").is_file():
        raise RuntimeError("Source structural restart binary missing")
    if not (source/"solid/kinematic_state.bin").is_file():
        raise RuntimeError("Source persistent HHT state missing")
    if not (source/"restart_reference/Solid-Mesh.coords").is_file():
        raise RuntimeError("Source original Solid-Mesh reference missing")
    foam=(source/"fluid/system/preciceDict").read_text()
    xml=(source/"precice-config.xml").read_text()
    yaml=(source/"solid/config.yml").read_text()
    if "restartFromDeformed false;" not in foam or "readData (DisplacementDelta);" not in foam:
        raise RuntimeError("Parent fluid is not original-reference + DisplacementDelta")
    if 'name="DisplacementDelta"' not in xml or 'data="DisplacementDelta"' not in xml:
        raise RuntimeError("Parent preCICE XML is not delta mapped")
    if 'data="Displacement" mesh="Solid-Mesh"' in xml:
        raise RuntimeError("Parent still exchanges absolute Displacement")
    if 'initialize="yes"' not in xml or xml.count('initialize="yes"')!=1:
        raise RuntimeError("Parent must initialize Force only")
    if "DisplacementDelta" not in yaml:
        raise RuntimeError("Parent CalculiX config does not write DisplacementDelta")
    # This cumulative result is mandatory; existing source numerical evidence
    # does not authorize changing its coupling frame or reverting to absolute D.
    for rank in range(8):
        p=source/f"fluid/processor{rank}"
        if len(core.numeric_time_names(p))<2:
            raise RuntimeError(f"Insufficient source time history processor{rank}")
    # IMPORTANT: job 92264 was launched with an earlier pinned driver whose
    # PASS report checked Fx and MeshCo, but NOT Delta0/Delta2 integrals.
    # Recompute the scientific gate from immutable accepted logs BEFORE a
    # subsequent Slurm job can be submitted, regardless of parent report.
    count=int(outcome["accepted_windows"])
    physical_start=declared-count*DT
    evidence=scientific_gate(base,source_work,source_work,physical_start,count)
    if evidence["status"]!="PASS":
        raise RuntimeError(
            "PARENT_SCIENTIFIC_DELTA_CONTINUITY_FAILED "
            f"Fx={evidence['max_Fx_relative_error']:.8g} "
            f"Delta0={evidence['max_delta0_relative_error']:.8g} "
            f"Delta2={evidence['max_delta2_relative_error']:.8g}")
    return source,declared,current_step+1,outcome


def build_private_stage(core,base,source_work,destination,windows,source_job):
    source,t0,step,parent=verified_source(source_work,core,base)
    if windows not in (2,20):
        raise RuntimeError("Only 2 or 20 windows allowed until separate long-job qualification")
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
    def ignore(parent,names):
        return [x for x in names if x=="precice-profiling"] if Path(parent).name in ("fluid","solid") else []
    shutil.copytree(source,dst,ignore=ignore,symlinks=False)
    core.verify_staged_fluid_history(source,dst,1)
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
    conf=core.exact(r"(purgeWrite\s+)\d+(\s*;)",r"\g<1>0\2",
                    conf,"Keep history for future delta restart")
    control.write_text(conf)
    xml=dst/"precice-config.xml"
    doc=xml.read_text()
    doc=core.exact(r'(<max-time value=")[\d.eE+-]+(")',
                   lambda m:m.group(1)+f"{windows*DT:.12g}"+m.group(2),
                   doc,"New preCICE session duration")
    xml.write_text(doc)
    metadata={
        "status":"STAGED_DELTA_CONTINUATION",
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
    """Every accepted window: compare Fx and two delta displacement integrals."""
    ref=watch(base/"three-day-proven/long-job-91543/runs/hpcc-implicit-002/solid"/WATCH)
    new=watch(work/"runs/hpcc-implicit-002/solid"/WATCH)
    fail=[]
    max_fx=max_dx=max_dz=0.
    results=[]
    for n in range(1,windows+1):
        rel=round(n*DT,9)
        rt=round(start+n*DT-ORIGIN,9)
        prev=round(rt-DT,9)
        if rel not in new or rt not in ref or prev not in ref:
            raise RuntimeError(f"Matched continuous/accepted window absent n={n} t={rt}")
        f=new[rel]
        r=ref[rt]
        rp=ref[prev]
        fx=abs(f[0]-r[0])/max(abs(r[0]),1e-12)
        ddx=abs(f[3]-(r[3]-rp[3]))/max(abs(r[3]-rp[3]),1e-10)
        ddz=abs(f[5]-(r[5]-rp[5]))/max(abs(r[5]-rp[5]),1e-10)
        max_fx=max(max_fx,fx);max_dx=max(max_dx,ddx);max_dz=max(max_dz,ddz)
        if fx>.01 or ddx>.01 or ddz>.01:
            fail.append(n)
        results.append({"n":n,"physical_t":start+n*DT,
                        "Fx":f[0],"reference_Fx":r[0],"Fx_error":fx,
                        "delta0_error":ddx,"delta2_error":ddz})
    return {"status":"PASS" if not fail else "FAIL","failed_windows":fail,
            "max_Fx_relative_error":max_fx,
            "max_delta0_relative_error":max_dx,
            "max_delta2_relative_error":max_dz,
            "accepted":results}


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
    t=start+DT
    reference=first_native_meshco(base/"three-day-proven/long-job-91543/fluid.log",t)
    observed=first_native_meshco(work/"fluid.log",t)
    ratio=observed/reference if reference is not None and reference>0 and observed is not None else None
    return {"physical_time_s":t,"91543_first_meshco":reference,
            "candidate_first_meshco":observed,"ratio":ratio,
            "tenfold_first_native_meshco_pass":ratio is not None and 0<=ratio<=10}


def run_trial(base,source_work,work,windows,core_path,source_job):
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("Compute node Slurm allocation required")
    core=load_core(core_path)
    # Fail-closed source before any files created.
    source,start,step,parent=verified_source(source_work,core,base)
    if work.exists():
        raise RuntimeError("Work already exists")
    def staged(_base,_stage,_job,_dest,_n,_chain_root=None):
        return build_private_stage(core,base,source_work,work,windows,source_job)
    original=core.stage_inputs
    core.stage_inputs=staged
    error=None
    try:
        core.run(base,1,int(source_job),work,windows,7200,base/"seagrass-fsi-mainline")
    except BaseException as e:
        error=repr(e)
        traceback.print_exc()
    finally:
        core.stage_inputs=original
    status_path=work/"FSI_SEGMENT_RESULT.json"
    native=read_json(status_path) if status_path.is_file() else None
    first_meshco=meshco_reference_gate(base,work,start)
    validation=None
    try:
        validation=scientific_gate(base,source_work,work,start,windows)
    except Exception as e:
        if error is None:error=repr(e)
    ok=(
        error is None and native is not None and validation is not None
        and native.get("status")=="FSI_LONG_SEGMENT_PASS"
        and native.get("accepted_windows")==windows
        and native.get("participant_exit_codes")=={"fluid":0,"solid":0}
        and native.get("native_terminal_mesh",{}).get("status")=="PASS"
        and validation.get("status")=="PASS"
        and first_meshco["tenfold_first_native_meshco_pass"]
    )
    report={
        "status":"DELTA_CONTINUATION_SHORT_STAGE_PASS" if ok
                 else "DELTA_CONTINUATION_SHORT_STAGE_FAIL",
        "parent_source":str(source_work),
        "start_t":start,"end_t":start+windows*DT,
        "windows":windows,"next_structural_step":step,
        "native_result":native,"scientific_vs_91543":validation,
        "first_native_meshco_vs_91543":first_meshco,
        "exception":error,
        "NEVER_AUTO_QUEUE_NEXT_STAGE":True,
    }
    if work.is_dir():
        (work/"DELTA_CONTINUATION_RESULT.json").write_text(
            json.dumps(report,indent=2,ensure_ascii=False)+"\n")
    print(report["status"],"window_count",windows,
          "Fx_err",validation.get("max_Fx_relative_error") if validation else None,
          "exception",error,flush=True)
    if not ok:
        raise SystemExit(3)


def self_test():
    import tempfile
    from types import SimpleNamespace
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp)
        ref=root/"ref.log"
        cand=root/"cand.log"
        base=root/"three-day-proven/long-job-91543/runs/hpcc-implicit-002/solid"
        base.mkdir(parents=True)
        ref=base/WATCH
        ref.write_text(
            "Time Fx Fy Fz D0 D1 D2\n"
            "0.030125 0.0179 0 0 30.1 0 -1.51\n"
            "0.030250 0.0181 0 0 30.2 0 -1.52\n"
            "0.030375 0.0183 0 0 30.3 0 -1.53\n"
            "0.030500 0.0185 0 0 30.4 0 -1.54\n")
        case=root/"trial-1/runs/hpcc-implicit-002/solid"
        case.mkdir(parents=True)
        cand=case/WATCH
        cand.write_text(
            "Time Fx Fy Fz DD0 DD1 DD2\n"
            "0.000125 0.0183 0 0 0.1 0 -0.01\n"
            "0.000250 0.0185 0 0 0.1 0 -0.01\n")
        x=scientific_gate(root,root,root/"trial-1",.03275,2)
        assert x["status"]=="PASS"
        assert x["max_Fx_relative_error"]==0.
        assert x["max_delta0_relative_error"]<1e-10
        assert x["max_delta2_relative_error"]<1e-10
        cand.write_text(cand.read_text().replace("0.0183 0","0.1 0"))
        assert scientific_gate(root,root,root/"trial-1",.03275,2)["status"]=="FAIL"
    with tempfile.TemporaryDirectory() as d:
        root=Path(d)
        native=root/"native.log"
        native.write_text("Time = 0.032875\n"
                          "Mesh Courant Number mean: 1e-8 max: 1.80e-5\n")
        assert first_native_meshco(native,.032875)==1.8e-5
        assert first_native_meshco(native,.032999) is None
    assert set((2,20))=={2,20}
    print("DELTA_CONTINUATION_SHORT_STAGE_OFFLINE_SELFTEST_PASS")


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--base",type=Path,default=Path.home()/"hpcc-fsi")
    p.add_argument("--core",type=Path)
    p.add_argument("--source-work",type=Path)
    p.add_argument("--source-job",type=int)
    p.add_argument("--work",type=Path)
    p.add_argument("--windows",type=int,choices=(2,20),default=20)
    p.add_argument("--preflight",action="store_true")
    p.add_argument("--run",action="store_true")
    p.add_argument("--self-test",action="store_true")
    args=p.parse_args()
    if args.self_test:
        return self_test()
    if args.source_work is None or args.core is None or args.source_job is None:
        p.error("Supply --source-work, --source-job and --core")
    base=args.base.expanduser().resolve(strict=True)
    core=load_core(args.core.expanduser().resolve(strict=True))
    source_work=args.source_work.expanduser().resolve(strict=True)
    source,start,step,outcome=verified_source(source_work,core,base)
    if args.preflight:
        print("DELTA_CONTINUATION_PREFLIGHT_PASS",
              "source",source_work,"from",start,
              "to",start+args.windows*DT,
              "structural_restart_step",step,
              "windows",args.windows,
              "NO_SBATCH_NO_SOURCE_WRITES")
        return
    if not args.run or args.work is None:
        p.error("Supply --run --work fresh_output or --preflight")
    run_trial(base,source_work,args.work.expanduser().resolve(),
              args.windows,args.core.expanduser().resolve(strict=True),
              args.source_job)


if __name__=="__main__":
    main()
