#!/usr/bin/env python3
"""Isolated t=.0325s -> .0335s 8-window ALE-FSI restart initialization candidate.

Underlying physics is unchanged. Only one preCICE exchange tag in the COPIED
candidate XML is patched:
<exchange data="Displacement" ... from="Solid" to="Fluid" initialize="yes" />
Fluid restartFromDeformed remains true (the production setting).
The preCICE 3.4.1 / CCX adapter 2.20.2 source supports pre-initialize()
structural absolute displacement via requiresInitialData().

Scientific acceptance requires:
 - 8 accepted real implicit two-way coupling time windows
 - both native participants exit with 0
 - real terminal parallel native checkMesh PASS
 - ALL logged mesh Courant <= .5, all fluid Courant <= .5
 - CCX writes initial displacement before initialization (support check)
 - no 'skipped zero sample' for initial t=0 displacement map
Fail closed: never auto-convert an isolated experiment to production.
Source 91006/cert and previous failed segment-A are never modified.
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

ROOT=Path.home()/"hpcc-fsi"
XML_PATTERN=re.compile(r'<exchange\b[^>]*\bdata="Displacement"[^>]*/>')
DT=.000125
N=8
CHECKPOINT=.0325

def patch_precice_xml(xml):
    choices=XML_PATTERN.findall(xml)
    if len(choices)!=1:
        raise RuntimeError(f"Expected exactly one outgoing Displacement exchange, got {len(choices)}")
    old=choices[0]
    for tag in ('mesh="Solid-Mesh"','from="Solid"','to="Fluid"'):
        if tag not in old:raise RuntimeError(f"Unexpected displacement exchange: missing {tag}")
    if re.search(r'\binitialize\s*=',old):
        raise RuntimeError("Source XML already initializes displacement; no silent re-patching")
    new=old[:-2].rstrip()+' initialize="yes" />'
    changed=xml.replace(old,new)
    if changed==xml or changed.count('initialize="yes"')!=1:
        raise RuntimeError("Failed to install exactly one nonzero displacement initialization")
    if "<coupling-scheme:parallel-implicit>" not in changed:
        raise RuntimeError("Not a parallel-implicit coupling")
    return changed

def check_source(base):
    source=base/"fsi-long-stage0-job91006/runs/hpcc-implicit-002"
    cert=json.loads((base/"FSI_91006_RESUME_CERT.json").read_text())
    if (cert.get("status")!="FSI_91006_CONDITIONAL_RESTART_ELIGIBLE"
        or cert.get("source_job")!=91006 or cert.get("next_step")!=3
        or cert.get("native_terminal_checkMesh",{}).get("status")!="PASS"):
        raise RuntimeError("Missing independently certified t=0.0325 restart")
    text=(source/"precice-config.xml").read_text()
    patch_precice_xml(text)
    precice=(source/"fluid/system/preciceDict").read_text()
    if "restartFromDeformed true;" not in precice:
        raise RuntimeError("Baseline fluid restartFromDeformed TRUE was modified")
    if "readData (Displacement)" not in precice:
        raise RuntimeError("Fluid must read full absolute Displacement")
    return source

def load_core(core):
    sp=importlib.util.spec_from_file_location("frozen_fsi_core",core)
    m=importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m

def analyze_initialization(work):
    fluid=(work/"fluid.log")
    solid=(work/"solid.log")
    f=fluid.read_text(errors="replace") if fluid.is_file() else ""
    s=solid.read_text(errors="replace") if solid.is_file() else ""
    init_received=[line.strip() for line in f.splitlines()
           if 'Mapping "Displacement" for t=0' in line]
    solid_written=s.find("Writing DISPLACEMENTS coupling data.")
    solid_init=s.find("Initializing coupling data")
    first_mesh=re.findall(r'Mesh Courant Number mean:\s*[\d.eE+-]+\s+max:\s*([\d.eE+-]+)',f)
    failed=bool(re.search(r'Signal: Floating point exception|FOAM FATAL',f))
    return {
      "solid_write_before_initialize":
        solid_written>=0 and solid_init>=0 and solid_written<solid_init,
      "solid_initial_write_log_index":solid_written,
      "solid_initialize_log_index":solid_init,
      "first_initial_displacement_mappings":init_received[:5],
      "t0_mapping_skipped_zero":any("skipped zero sample" in v for v in init_received),
      "initial_displacement_mapping_observed":bool(init_received),
      "mesh_courant_first_records":first_mesh[:10],
      "max_logged_mesh_courant":max(map(float,first_mesh)) if first_mesh else None,
      "fluid_fpe_or_fatal":failed,
      "note":"Nonzero preCICE mapping indicates initialized data; a CCX write log alone does not prove vold nonzero."
    }

def self_test():
    sample='''<precice-configuration>
<coupling-scheme:parallel-implicit>
<exchange data="Force" mesh="Solid-Mesh" from="Fluid" to="Solid" />
<exchange data="Displacement" mesh="Solid-Mesh" from="Solid" to="Fluid" />
</coupling-scheme:parallel-implicit>
</precice-configuration>'''
    newer=patch_precice_xml(sample)
    assert newer.count('initialize="yes"')==1
    assert '<exchange data="Force" mesh="Solid-Mesh" from="Fluid" to="Solid" />' in newer
    assert 'from="Solid" to="Fluid" initialize="yes" />' in newer
    try:patch_precice_xml(newer)
    except RuntimeError:pass
    else:raise AssertionError("Repatch silently accepted")
    sample_bad=sample.replace('to="Fluid"','to="Solid"')
    try:patch_precice_xml(sample_bad)
    except RuntimeError:pass
    else:raise AssertionError("Wrong exchange accepted")
    print("ALE_INITIAL_DISPLACEMENT_CANDIDATE_SELF_TEST_PASS")

def run(base,work):
    source=check_source(base)
    core=base/"seagrass-fsi-mainline/bin/segment.py"
    if not core.is_file():raise RuntimeError("Missing certified frozen legacy segment core")
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("An isolated Slurm compute-node allocation is required")
    if work.exists():
        raise RuntimeError("Refuse to overwrite existing test work dir")
    if not work.is_relative_to(base) or source in work.parents or work==source:
        raise RuntimeError("Test may not overlap original checkpoint")
    mod=load_core(core)
    oldchoose=mod.choose_windows
    oldstage=mod.stage_inputs

    def choose(stage,max_windows,sec):
        if stage!=1 or max_windows!=N:raise RuntimeError("Only eight-window stage1 restart is permitted")
        return N

    def stage_inputs(b,stage,previous_job,dst,max_windows,chain_root=None):
        run_dir,metadata=oldstage(b,stage,previous_job,dst,max_windows,chain_root)
        xml=run_dir/"precice-config.xml"
        before=xml.read_text()
        after=patch_precice_xml(before)
        xml.write_text(after)
        check=(run_dir/"fluid/system/preciceDict").read_text()
        if "restartFromDeformed true;" not in check:
            raise RuntimeError("Candidate unexpectedly altered native fluid restart coordinates")
        metadata.update({
          "isolated_candidate":True,
          "scientific_change":"PreCICE absolute Displacement exchange initialize=yes",
          "original_restartFromDeformed":True,
          "required_accepted_windows":N,
          "do_not_promote_without_accepted_coupling":True
        })
        mod.jwrite(dst/"FSI_SEGMENT_STAGE.json",metadata)
        return run_dir,metadata

    mod.choose_windows=choose
    mod.stage_inputs=stage_inputs
    error=None
    try:
        print("ALE_INITIAL_DISPLACEMENT_REAL_FSI_TRIAL start=.0325 target=.0335 windows=8",flush=True)
        mod.run(base,1,91006,work,N,3*3600,base/"seagrass-fsi-mainline")
    except BaseException as e:
        error=e
        traceback.print_exc()
    finally:
        mod.choose_windows=oldchoose
        mod.stage_inputs=oldstage
    diag=analyze_initialization(work)
    result_file=work/"FSI_SEGMENT_RESULT.json"
    result=json.loads(result_file.read_text()) if result_file.is_file() else None
    q=result.get("quality",{}) if result else {}
    strict=bool(
        error is None and result and
        result.get("status")=="FSI_LONG_SEGMENT_PASS" and
        result.get("accepted_windows")==N and
        math.isclose(result.get("final_time_s",0),CHECKPOINT+N*DT,abs_tol=1e-9) and
        result.get("participant_exit_codes")=={"fluid":0,"solid":0} and
        q.get("max_mesh_Co",float("inf"))<=.5 and
        q.get("max_fluid_Co",float("inf"))<=.5 and
        result.get("native_terminal_mesh",{}).get("status")=="PASS" and
        diag["solid_write_before_initialize"] and
        diag["initial_displacement_mapping_observed"] and
        not diag["t0_mapping_skipped_zero"]
    )
    report={
        "status":"ALE_NONZERO_INITIAL_DISPLACEMENT_8WINDOW_PASS" if strict
          else "ALE_NONZERO_INITIAL_DISPLACEMENT_8WINDOW_FAIL",
        "source_time_s":CHECKPOINT,"target_time_s":CHECKPOINT+N*DT,
        "candidate_change":"initialize=yes on Solid-to-Fluid Displacement XML exchange",
        "restarted_fluid_interface_reference_deformed":True,
        "original_91006_and_failed_runs_untouched":True,
        "real_initial_exchange_evidence":diag,
        "error":repr(error) if error else None,
        "real_fsi_result":result,
        "verified_suitable_for_3day_production":False
    }
    if work.is_dir():
        (work/"INITIAL_DISPLACEMENT_TEST_RESULT.json").write_text(
            json.dumps(report,indent=2,ensure_ascii=False)+"\n")
    print(report["status"],"INITIAL_ZERO_MAPPING",diag["t0_mapping_skipped_zero"],
          "CO_MAX",diag["max_logged_mesh_courant"],"ERROR",repr(error),flush=True)
    if not strict:sys.exit(3)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base",type=Path,default=ROOT)
    p.add_argument("--work",type=Path)
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--preflight",action="store_true")
    p.add_argument("--run",action="store_true")
    a=p.parse_args()
    if a.self_test:return self_test()
    base=a.base.expanduser().resolve(strict=True)
    src=check_source(base)
    if a.preflight:
        load_core(base/"seagrass-fsi-mainline/bin/segment.py").source_for(
            base,1,91006,base/"seagrass-fsi-mainline")
        print("ALE_INITIAL_DISPLACEMENT_PREFLIGHT_PASS from=.0325 windows=8",flush=True)
        return
    if not a.run or a.work is None:p.error("Run requires --run --work")
    run(base,a.work.expanduser().resolve(),)

if __name__=="__main__":
    main()
