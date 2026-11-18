#!/usr/bin/env python3
"""Read-only independent audit for G1=92479; NO original reports rewritten.

The original 1% Fx scientific gate remains FAILED at 1.025275%; explicitly
distinguish native completion and a bounded, non-production G2 diagnostic.
Require real native evidence and 20 physically matched accepted windows.
This script does not create output files, launch Slurm, or approve production.
"""
import argparse
import importlib.util
import json
import math
from pathlib import Path
import sys

ORIGIN=.0025
DT=.000125
PARENT_JOB=92264
G1_JOB=92479
START=.03275
END=.03525
COUNT=20
EXPECTED_ROOT="crossjob-fix-20261116/delta-continuation/trial-92479"


def load(path):
    spec=importlib.util.spec_from_file_location("delta_g1_audit_module",path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Invalid shared delta module: {path}")
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def same(a,b,tol=1e-9):
    return math.isfinite(a) and abs(a-b)<=tol


def classify(native,stage,scientific,mesh,source_force,initial_row,raw_result):
    """Return all individual gates, never translate a FAIL into native PASS."""
    first=initial_row if initial_row is not None else []
    last_ref=source_force
    init=bool(
        len(first)>=6 and last_ref is not None and
        abs(first[0]-last_ref)<=max(abs(last_ref)*1e-7,1e-9) and
        all(abs(x)<1e-13 for x in first[3:6])
    )
    native_q=native.get("quality",{}) if isinstance(native,dict) else {}
    native_ok=bool(
        isinstance(native,dict)
        and native.get("status")=="FSI_LONG_SEGMENT_PASS"
        and native.get("participant_exit_codes")=={"fluid":0,"solid":0}
        and native.get("accepted_windows")==COUNT
        and same(float(native.get("final_time_s",-1)),END)
        and native.get("native_terminal_mesh",{}).get("status")=="PASS"
        and native_q.get("max_fluid_Co",math.inf)<=.5
        and native_q.get("max_mesh_Co",math.inf)<=.5
        and native_q.get("native_guard_checks",0)>=COUNT
        and native_q.get("min_ale_volume_m3",0)>0
        and not native_q.get("first_window_restart_transient_exception",True)
    )
    stage_ok=bool(
        stage.get("read_restart_step")==4
        and stage.get("accepted_windows")==COUNT
        and same(float(stage.get("parent_time_s",-1)),START)
        and same(float(stage.get("final_time_s",-1)),END)
        and stage.get("delta_protocol_inherited_not_repatched") is True
        and stage.get("initial_force_only") is True
        and stage.get("mesh_registration_original_reference") is True
        and stage.get("mpi_fluid")==8
        and stage.get("omp_solid")==4
    )
    first_mesh=bool(
        mesh.get("tenfold_first_native_meshco_pass") is True
        and mesh.get("ratio") is not None
        and .8<=mesh["ratio"]<=1.2
        and same(float(mesh.get("physical_time_s",-1)),START+DT)
    )
    rows=scientific.get("accepted",[])
    accurate_rows=bool(
        len(rows)==COUNT
        and all(row.get("n")==i and
                same(float(row.get("physical_t",-1)),START+i*DT)
                for i,row in enumerate(rows,1)))
    fx=scientific.get("max_Fx_relative_error",math.inf)
    d0=scientific.get("max_delta0_relative_error",math.inf)
    d2=scientific.get("max_delta2_relative_error",math.inf)
    strictly=accurate_rows and all(math.isfinite(x) and x<=.01 for x in (fx,d0,d2))
    # 2% is a *separate, explicit diagnostic-only guardrail*, NOT an
    # unannounced change to the pre-established 1% scientific criterion.
    bounded=accurate_rows and all(math.isfinite(x) for x in (fx,d0,d2)) \
        and fx<=.02 and d0<=.005 and d2<=.005
    original_fail=bool(
        raw_result.get("status")=="DELTA_CONTINUATION_SHORT_STAGE_FAIL"
        and raw_result.get("exception") is None
        and raw_result.get("scientific_vs_91543",{}).get("status")=="FAIL"
    )
    gates={
        "native_completed_successfully":native_ok,
        "restored_step_and_delta_protocol":stage_ok,
        "initial_force_and_zero_delta_continuity":init,
        "first_ale_meshco_near_continuous":first_mesh,
        "all_twenty_same_physical_time_accepted":accurate_rows,
        "strict_preexisting_1pct_scientific_gate":strictly,
        "diagnostic_only_2pct_Fx_0p5pct_delta_guardrail":bounded,
        "original_Fx_scientific_FAIL_preserved":original_fail,
    }
    available_for_g2=all((
        native_ok,stage_ok,init,first_mesh,accurate_rows,bounded,original_fail
    ))
    return {
        "verdict":(
            "G1_STRICT_SCIENCE_AND_NATIVE_PASS" if strictly and all(
              (native_ok,stage_ok,init,first_mesh,accurate_rows))
            else "G1_NATIVE_PASS_G2_DIAGNOSTIC_ELIGIBLE_STRICT_SCIENCE_FAIL"
                 if available_for_g2 else "G1_NOT_QUALIFIED_FOR_G2"),
        "g2_diagnostic_eligible":available_for_g2,
        "production_restart_approved":False,
        "original_G1_result_was_rewritten":False,
        "gates":gates,
        "errors":{
            "max_Fx_relative":fx,"max_Delta0_relative":d0,
            "max_Delta2_relative":d2,
            "Fx_strict_1pct_exceedance_percentage_points":max(0,(fx-.01)*100)
        },
        "max_error_window":max(rows,key=lambda row:row["Fx_error"]) if rows else None,
    }


def audit(base,driver_path):
    mod=load(driver_path)
    work=base/EXPECTED_ROOT
    original=mod.read_json(work/"DELTA_CONTINUATION_RESULT.json")
    native=mod.read_json(work/"FSI_SEGMENT_RESULT.json")
    stage=mod.read_json(work/"FSI_SEGMENT_STAGE.json")
    source=base/"crossjob-fix-20261116/delta-2window/trial-92264"
    g0=mod.read_json(source/"INCREMENTAL_DISPLACEMENT_RESULT.json")
    if g0.get("status")!="INCREMENTAL_DISPLACEMENT_TWO_WINDOW_PASS":
        raise RuntimeError("G0 source had not accepted 2 windows")
    history=mod.watch(source/"runs/hpcc-implicit-002/solid"/mod.WATCH)
    last=history.get(round(.00025,9))
    if last is None:
        raise RuntimeError("G0 accepted terminal Force missing")
    now=mod.watch(work/"runs/hpcc-implicit-002/solid"/mod.WATCH)
    initial=now.get(0.)
    first_mesh=mod.meshco_reference_gate(base,work,START)
    science=mod.scientific_gate(base,source,work,START,COUNT)
    result=classify(native,stage,science,first_mesh,last[0],initial,original)
    fluid=work/"runs/hpcc-implicit-002/fluid"
    source_ok=bool(
        (work/"STATE.json").is_file()
        and (work/"runs/hpcc-implicit-002/solid/seagrass.rout").is_file()
        and (work/"runs/hpcc-implicit-002/solid/kinematic_state.bin").is_file()
        and all(len(mod.load_core(driver_path.with_name("segment.py")).numeric_time_names(
           fluid/f"processor{rank}"))>=2 for rank in range(8))
    )
    physical,_=mod.load_core(driver_path.with_name("segment.py")).latest_time(fluid)
    physical_ok=same(physical,END)
    result["source_has_complete_8_rank_and_solid_checkpoint"]=source_ok
    result["source_checkpoint_physical_time_verified"]=physical_ok
    result["g2_diagnostic_eligible"]=bool(result["g2_diagnostic_eligible"] and source_ok and physical_ok)
    if not result["g2_diagnostic_eligible"] and result["verdict"].endswith("ELIGIBLE_STRICT_SCIENCE_FAIL"):
        result["verdict"]="G1_NOT_QUALIFIED_FOR_G2"
    result.update({
      "source":"real HPCC files read-only","g1_job":G1_JOB,
      "g0_job":PARENT_JOB,"g1_original_report_status":original.get("status"),
      "native_status":native.get("status"),"physical_time_interval":[START,END],
      "window_count":COUNT,
      "G2_if_diagnostic_start_s":END,
      "G2_if_diagnostic_end_s":END+2*DT,
      "note":"Conditional G2 is only a short numerical diagnostic; not production permission."
    })
    return result


def self_test():
    native={"status":"FSI_LONG_SEGMENT_PASS","accepted_windows":20,
     "final_time_s":END,"participant_exit_codes":{"fluid":0,"solid":0},
     "native_terminal_mesh":{"status":"PASS"},
     "quality":{"max_mesh_Co":.12,"max_fluid_Co":.4,"native_guard_checks":400,
                "min_ale_volume_m3":2e-11,"first_window_restart_transient_exception":False}}
    stage={"read_restart_step":4,"accepted_windows":20,
      "parent_time_s":START,"final_time_s":END,"delta_protocol_inherited_not_repatched":True,
      "initial_force_only":True,"mesh_registration_original_reference":True,
      "mpi_fluid":8,"omp_solid":4}
    science={"accepted":[{"n":i,"physical_t":START+i*DT,"Fx_error":.008}
                         for i in range(1,21)],
      "max_Fx_relative_error":.010252751525572316,
      "max_delta0_relative_error":5.4627645726802694e-05,
      "max_delta2_relative_error":.0009584332019428214}
    mesh={"tenfold_first_native_meshco_pass":True,"ratio":.9989209108826642,
          "physical_time_s":START+DT}
    original={"status":"DELTA_CONTINUATION_SHORT_STAGE_FAIL","exception":None,
     "scientific_vs_91543":{"status":"FAIL"}}
    r=classify(native,stage,science,mesh,.0182393924,
      [.0182393924,0,0,0,0,0],original)
    assert r["g2_diagnostic_eligible"]
    assert not r["gates"]["strict_preexisting_1pct_scientific_gate"]
    assert r["verdict"]=="G1_NATIVE_PASS_G2_DIAGNOSTIC_ELIGIBLE_STRICT_SCIENCE_FAIL"
    science["max_Fx_relative_error"] = .03
    assert not classify(native,stage,science,mesh,.0182393924,
      [.0182393924,0,0,0,0,0],original)["g2_diagnostic_eligible"]
    science["max_Fx_relative_error"] = .010252751525572316
    native["participant_exit_codes"]={"fluid":0,"solid":1}
    assert not classify(native,stage,science,mesh,.0182393924,
      [.0182393924,0,0,0,0,0],original)["g2_diagnostic_eligible"]
    print("G1_READONLY_G2_DIAGNOSTIC_GATE_SELFTEST_PASS")


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--base",type=Path,default=Path.home()/"hpcc-fsi")
    p.add_argument("--driver",type=Path,default=Path(__file__).with_name("delta-continuation.py"))
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--require-g2-eligible",action="store_true")
    args=p.parse_args()
    if args.self_test:
        self_test();return
    result=audit(args.base.expanduser().resolve(strict=True),args.driver.expanduser().resolve(strict=True))
    print(json.dumps(result,indent=2,ensure_ascii=False))
    if args.require_g2_eligible and not result["g2_diagnostic_eligible"]:
        raise SystemExit("G1_BLOCKED_G2_DUE_TO_NATIVE_OR_BOUNDED_ERROR_FAILURE")


if __name__=="__main__":
    main()
