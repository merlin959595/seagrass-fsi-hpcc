#!/usr/bin/env python3
"""Test an untested *combination* in isolation: 2-way ALE-FSI at 0.0325s.

This experiment changes ONLY:
  (1) preCICE initializes both Force and absolute Displacement with copied
      solver fields, as validated in prior 91542
  (2) OpenFOAM restartFromDeformed TRUE -> FALSE, to align the fluid
      interface reference x0 with CCX's frozen Solid-Mesh.coords reference
      after structural geometry restoration.

The previous trial of FALSE (91504) did NOT use nonzero displacement
initialization and failed at the ALE step. It DOES NOT falsify this new
reference-alignment hypothesis.

Fail-closed criteria: 2 genuinely accepted implicit coupling windows, both
exits 0, native terminal mesh check, initial mapped force matches previous
0.01766382N within 10%, first *computed* Force within 20%, and fluid Co
within 0.5 and ALE mesh Co <=0.5. Never promote without this evidence.
Do not submit while long successful 91543 run is being interfered with.
"""
import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import sys
import traceback

BASE=Path.home()/"hpcc-fsi"
# Optional isolated version of OUR driver. Never edit a running job's pinned core.
CORE=Path(os.environ.get("FSI_ISOLATED_CORE",
            str(BASE/"seagrass-fsi-mainline/bin/segment.py"))).expanduser()
SOURCE=BASE/"fsi-long-stage0-job91006/runs/hpcc-implicit-002"
ORIG_WATCH_FORCE=.0176638208
N=2
DT=.000125

def imported(path,name):
    if not path.is_file():raise RuntimeError("Missing tested dependency "+str(path))
    sp=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m

def patch_ref(txt):
    pat=r'\brestartFromDeformed\s+true\s*;'
    changed,n=re.subn(pat,"restartFromDeformed false;",txt)
    if n!=1 or "restartFromDeformed true" in changed:
        raise RuntimeError(f"Unexpected restartFromDeformed field count={n}")
    if not re.search(r'(?s)\bFSI\s*\{[^}]*restartFromDeformed false;',changed):
        raise RuntimeError("Motion reference flag not in FSI block")
    return changed

def patch_xml(txt):
    # Prefer the isolated copies shipped with this experiment. Do not
    # depend on or mutate the long job's or old mainline's scripts.
    f=Path(__file__).resolve().with_name("restart-both-initial-fields-candidate.py")
    if not f.is_file():
        f=BASE/"clean-production-src/restart-both-initial-fields-candidate.py"
    if not f.is_file():
        f=Path(__file__).resolve().parent.parent/"clean-production/restart-both-initial-fields-candidate.py"
    b=imported(f,"verified_both_initial_fields")
    return b.patch(txt)

def provenance(base):
    root=base/"fsi-long-stage0-job91006/runs/hpcc-implicit-002"
    cert=json.loads((base/"FSI_91006_RESUME_CERT.json").read_text())
    if cert.get("status")!="FSI_91006_CONDITIONAL_RESTART_ELIGIBLE" or \
       cert.get("source_job")!=91006 or \
       cert.get("native_terminal_checkMesh",{}).get("status")!="PASS":
        raise RuntimeError("Source checkpoint is not qualified")
    xml=(root/"precice-config.xml").read_text()
    patch_xml(xml)
    ref=(root/"fluid/system/preciceDict").read_text()
    patch_ref(ref)
    mesh=(root/"restart_reference/Solid-Mesh.coords")
    if not mesh.is_file() or mesh.stat().st_size<1000:
        raise RuntimeError("Missing frozen CCX original mesh coordinate reference")
    for rank in range(8):
        d=root/f"fluid/processor{rank}/0.0325"
        if not (d/"pointDisplacement").is_file() or not (d/"polyMesh/points").is_file():
            raise RuntimeError(f"Rank {rank} lacks certified ALE restart fields")
    return root

def choose(stage,maxwin,prior_t):
    if stage!=1 or maxwin!=N:
        raise RuntimeError("Only two restarted FSI time windows allowed")
    return N

def validation(work,orig):
    fresh=work/"runs/hpcc-implicit-002"
    original=orig/"solid/precice-Solid-watchintegral-Interface-Integral.log"
    current=fresh/"solid/precice-Solid-watchintegral-Interface-Integral.log"
    def vals(p):
        if not p.is_file():return []
        rows=[]
        for line in p.read_text(errors="replace").splitlines():
            a=line.split()
            if len(a)<7:continue
            try:rows.append((float(a[0]),float(a[1])))
            except ValueError:pass
        return rows
    old=[fx for t,fx in vals(original) if abs(t-.03)<1e-8]
    new=[fx for t,fx in vals(current) if abs(t)<1e-9]
    target=old[-1] if old else None
    initial=new[0] if new else None
    diff=(abs(initial-target)/abs(target)
          if initial is not None and target is not None and target else None)
    fl=(work/"fluid.log").read_text(errors="replace") if (work/"fluid.log").is_file() else ""
    sol=(work/"solid.log").read_text(errors="replace") if (work/"solid.log").is_file() else ""
    firstforce=None
    m=re.search(r'forces bladeForces write:.*?\bTotal\s*:\s*\(([-+\deE.]+)\s+([-+\deE.]+)\s+([-+\deE.]+)\)',fl,re.S)
    if m:firstforce=[float(x) for x in m.groups()]
    first_rel=(abs(firstforce[0]-target)/abs(target)
               if firstforce and target else None)
    meshco=[float(x) for x in re.findall(
       r'Mesh Courant Number mean:\s*[-+\deE.]+\s+max:\s*([-+\deE.]+)',fl)]
    return {
       "certified_last_force0_N":target,
       "initialized_force0_N":initial,
       "initial_force0_relative_error":diff,
       "initial_force0_10pct":diff is not None and diff<=.10,
       "first_computed_force0_N":firstforce[0] if firstforce else None,
       "first_computed_force0_relative_error":first_rel,
       "first_computed_force0_20pct":first_rel is not None and first_rel<=.20,
       "initial_force_mapping_not_skipped_zero":any(
           'Mapping "Force" for t=0 from "Fluid-Mesh-Faces" to "Solid-Mesh"' in l
           and 'skipped zero sample' not in l for l in fl.splitlines()),
       "initial_displacement_mapping_not_skipped_zero":any(
           'Mapping "Displacement" for t=0 from "Solid-Mesh" to "Fluid-Mesh-Nodes"' in l
           and 'skipped zero sample' not in l for l in fl.splitlines()),
       "meshCo_first_values":meshco[:12],
       "meshCo_peak":max(meshco) if meshco else None,
       "solid_nonlinear_divergence":'*ERROR: solution seems to diverge' in sol,
       "fluid_FPE":('Floating point exception' in fl and 'Signal' in fl),
    }

def self_test():
    example="FSI { restartFromDeformed true; solverType incompressible; }"
    assert patch_ref(example).count("restartFromDeformed false;")==1
    try:patch_ref(example.replace(" true;"," false;"))
    except RuntimeError:pass
    else:raise AssertionError("Accepted no-op reference")
    sample='''<precice-configuration><coupling-scheme:parallel-implicit>
<exchange data="Force" mesh="Solid-Mesh" from="Fluid" to="Solid" />
<exchange data="Displacement" mesh="Solid-Mesh" from="Solid" to="Fluid" />
</coupling-scheme:parallel-implicit></precice-configuration>'''
    fixed=patch_xml(sample)
    assert fixed.count('initialize="yes"')==2, fixed
    assert 'data="Force" mesh="Solid-Mesh" from="Fluid" to="Solid" initialize="yes"' in fixed
    assert 'data="Displacement" mesh="Solid-Mesh" from="Solid" to="Fluid" initialize="yes"' in fixed
    try:patch_xml(fixed)
    except RuntimeError:pass
    else:raise AssertionError("Accepted already-initialized force/displacement XML")
    assert math.isclose(.0325+N*DT,.03275,abs_tol=1e-12)
    # Regression for the exact 91767 staging mistake: --preflight used our
    # isolated CORE but --run accidentally loaded the frozen mainline driver.
    # This is deliberately an offline probe; no Slurm, solver or file writes.
    import tempfile
    from unittest import mock
    class StopBeforeSolver(Exception): pass
    loaded=[]
    def capture(path,name):
        loaded.append((Path(path),name))
        raise StopBeforeSolver()
    with tempfile.TemporaryDirectory(prefix="crossjob-execution-path-") as tmp:
        base=Path(tmp)
        sentinel=base/"isolated-corrected-segment.py"
        with mock.patch.dict(os.environ,{"SLURM_JOB_ID":"MOCK_NO_SLURM"}), \
             mock.patch(__name__+".CORE",sentinel), \
             mock.patch(__name__+".provenance",return_value=base), \
             mock.patch(__name__+".imported",side_effect=capture):
            try:
                run(base,base/"trial")
            except StopBeforeSolver:
                pass
            else:
                raise AssertionError("Execution-path probe reached beyond core loader")
    assert loaded==[(sentinel,"isolated_own_restart_driver")], loaded
    print("FSI_ACTUAL_RUN_CORE_PIN_REGRESSION_PASS")
    print("FSI_RESTART_ALIGNED_REFERENCE_AND_BOTH_INITIAL_FIELDS_SELFTEST_PASS")

def run(base,work):
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("Isolated Slurm compute allocation needed")
    if work.exists() or not work.is_relative_to(base):
        raise RuntimeError("Must supply a new, non-overlapping test directory")
    if "long-job-" in str(work):
        raise RuntimeError("Never use ongoing 91543 work folder")
    source=provenance(base)
    core=imported(CORE,"isolated_own_restart_driver")
    original_choose=core.choose_windows
    original_stage=core.stage_inputs
    def stage_inputs(b,stage,parent,dest,max_windows,chain_root=None):
        out,meta=original_stage(b,stage,parent,dest,max_windows,chain_root)
        xml=out/"precice-config.xml"
        xml.write_text(patch_xml(xml.read_text()))
        foam=out/"fluid/system/preciceDict"
        foam.write_text(patch_ref(foam.read_text()))
        meta["isolation_change"]="restartFromDeformed=false PLUS both Force/Displacement initialize=yes"
        meta["no_other_solver_changes"]=True
        core.jwrite(dest/"FSI_SEGMENT_STAGE.json",meta)
        return out,meta
    core.choose_windows=choose
    core.stage_inputs=stage_inputs
    err=None
    try:
        core.run(base,1,91006,work,N,2*3600,base/"seagrass-fsi-mainline")
    except BaseException as e:
        err=repr(e)
        traceback.print_exc()
    finally:
        core.choose_windows=original_choose
        core.stage_inputs=original_stage
    v=validation(work,source)
    rfile=work/"FSI_SEGMENT_RESULT.json"
    r=json.loads(rfile.read_text()) if rfile.is_file() else None
    q=r.get("quality",{}) if r else {}
    ok=bool(not err and r and r.get("status")=="FSI_LONG_SEGMENT_PASS"
         and r.get("accepted_windows")==N
         and abs(float(r.get("final_time_s",0))-.03275)<1e-9
         and r.get("participant_exit_codes")=={"fluid":0,"solid":0}
         and r.get("native_terminal_mesh",{}).get("status")=="PASS"
         and q.get("max_fluid_Co",math.inf)<=.5
         and q.get("max_mesh_Co",math.inf)<=.5
         and v["initial_force0_10pct"]
         and v["first_computed_force0_20pct"]
         and v["initial_force_mapping_not_skipped_zero"]
         and v["initial_displacement_mapping_not_skipped_zero"]
         and not v["solid_nonlinear_divergence"]
         and not v["fluid_FPE"])
    status="REFERENCE_ALIGNED_BOTH_FIELDS_2WIN_PASS" if ok else "REFERENCE_ALIGNED_BOTH_FIELDS_2WIN_FAILED_OR_UNVERIFIED"
    report={
       "status":status,
       "original_source":"91006 t=.0325s (immutable)",
       "reference_options":"OpenFOAM restartFromDeformed false with CCX original reference",
       "data_initialization":"both Force and absolute Displacement initialize=yes",
       "first_frame_fluid_vs_solid_alignment_hypothesis_needs_verification":True,
       "real_fsi_result":r,"continuity":v,"exception":err,
       "do_not_auto_chain_to_production":True}
    if work.is_dir():
        (work/"REFERENCE_ALIGNED_BOTH_FIELDS_RESULT.json").write_text(
          json.dumps(report,indent=2,ensure_ascii=False)+"\n")
    print(status,"FIRST_FX",v["first_computed_force0_N"],
          "ORIGINAL_FX",v["certified_last_force0_N"],
          "MESH_CO_MAX",v["meshCo_peak"],"ERROR",err,flush=True)
    if not ok:sys.exit(3)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--base",type=Path,default=BASE)
    p.add_argument("--work",type=Path)
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--preflight",action="store_true")
    p.add_argument("--run",action="store_true")
    a=p.parse_args()
    if a.self_test:return self_test()
    b=a.base.expanduser().resolve(strict=True)
    provenance(b)
    core=imported(CORE,"isolated_own_restart_driver")
    core.source_for(b,1,91006,b/"seagrass-fsi-mainline")
    if a.preflight:
        print("FSI_TWO_WINDOW_REFERENCE_ALIGNED_PREFLIGHT_PASS; NO_SLURM_NO_FIELD_WRITES")
        return
    if not a.run or a.work is None:p.error("Must specify --run --work <new_directory>")
    run(b,a.work.expanduser().resolve())
if __name__=="__main__":
    main()
