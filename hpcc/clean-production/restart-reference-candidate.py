#!/usr/bin/env python3
"""Targeted 8-window recovery of certified t=0.0325 FSI snapshot.

Use precisely the original 282332-cell grid, U=0.16 and two-way FSI,
8 fluid MPI, 4 CCX OpenMP, dt=0.000125, IQN15, convergence 1e-5.
Only change: FSI/restartFromDeformed TRUE -> FALSE, to test *reference
interface coordinates* against CCX's original Solid-Mesh.coords.

This is a separate scientific candidate, NOT accepted production; reject
if ANY mesh Courant number >0.5 or mesh check fails.
Never overwrite completed 91006 or the failed mainline/segment-A.
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import sys

def load(path):
    spec=importlib.util.spec_from_file_location("fsi_original_clean_segment",path)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def patch_dict(text):
    before=r"\brestartFromDeformed\s+true\s*;"
    after="restartFromDeformed false;"
    result,num=re.subn(before,after,text)
    if num!=1 or "restartFromDeformed true;" in result:
        raise RuntimeError("Not exactly one FSI restart reference option")
    if not re.search(r"(?s)\bFSI\s*\{[^}]*restartFromDeformed false;",result):
        raise RuntimeError("Restart reference option not inside FSI block")
    return result

def check_inputs(base):
    cert=json.loads((base/"FSI_91006_RESUME_CERT.json").read_text())
    if (cert.get("status")!="FSI_91006_CONDITIONAL_RESTART_ELIGIBLE"
        or cert.get("native_terminal_checkMesh",{}).get("status")!="PASS"):
        raise RuntimeError("Missing independent completed 0.0325 s mesh certificate")
    source=base/"fsi-long-stage0-job91006/runs/hpcc-implicit-002"
    d=source/"fluid/system/preciceDict"
    raw=d.read_text()
    if not re.search(r"\brestartFromDeformed\s+true\s*;",raw):
        raise RuntimeError("Existing FSI restart assumption has changed")
    patch_dict(raw)
    coords=source/"restart_reference/Solid-Mesh.coords"
    if coords.stat().st_size<1000:raise RuntimeError("Missing structural reference geometry")
    return source

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base",type=Path,default=Path.home()/"hpcc-fsi")
    p.add_argument("--work",type=Path)
    p.add_argument("--run",action="store_true")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:
        test="""modules (FSI);\nFSI\n{\n    restartFromDeformed true;\n}\ninterfaces {}\n"""
        changed=patch_dict(test)
        assert "restartFromDeformed false;" in changed
        for wrong in ("modules (FSI);","FSI { restartFromDeformed true; restartFromDeformed true; }"):
            try:patch_dict(wrong)
            except RuntimeError:pass
            else:raise AssertionError("Accepted invalid motion policy")
        print("ALE_RESTART_REFERENCE_CANDIDATE_SELF_TEST_PASS")
        return
    if not a.run or a.work is None:
        p.error("Use --run and --work inside a Slurm allocation")
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("Requires real Slurm compute node")
    base=a.base.expanduser().resolve(strict=True)
    source=check_inputs(base)
    work=a.work.expanduser().resolve()
    if not work.is_relative_to(base) or work==source or source in work.parents:
        raise RuntimeError("Candidate cannot be placed inside original FSI source")
    if work.exists():raise RuntimeError("Refusing to reuse a previous candidate directory")
    core=base/"seagrass-fsi-mainline/bin/segment.py"
    if not core.is_file():raise RuntimeError("Missing frozen parent driver")
    mod=load(core)
    original_choose=mod.choose_windows
    original_stage=mod.stage_inputs
    def choose(stage,max_windows,previous_s_per_window):
        if stage!=1 or max_windows!=8:
            raise RuntimeError("Targeted trial allows stage 1 with 8 windows only")
        return 8
    def stage_inputs(b,stage,previous_job,destination,max_windows,chain_root=None):
        dst,meta=original_stage(b,stage,previous_job,destination,max_windows,chain_root)
        file=dst/"fluid/system/preciceDict"
        old=file.read_text()
        altered=patch_dict(old)
        file.write_text(altered)
        meta["isolated_test_only"]=True
        meta["only_changed_physics_setting"]="FSI restartFromDeformed true->false"
        meta["initial_reference_configuration_must_match_solid"]=True
        mod.jwrite(destination/"FSI_SEGMENT_STAGE.json",meta)
        return dst,meta
    mod.choose_windows=choose
    mod.stage_inputs=stage_inputs
    try:
        print("TARGET_RESTART_FIRST_8_WINDOWS source_t=0.0325 target_t=0.0335")
        mod.run(base,1,91006,work,8,3*3600,base/"seagrass-fsi-mainline")
    finally:
        mod.choose_windows=original_choose
        mod.stage_inputs=original_stage

    result=json.loads((work/"FSI_SEGMENT_RESULT.json").read_text())
    quality=result.get("quality",{})
    strict_ok=(
        result.get("status")=="FSI_LONG_SEGMENT_PASS"
        and result.get("accepted_windows")==8
        and math.isclose(result.get("final_time_s",-1),.0335,abs_tol=1e-9)
        and quality.get("max_mesh_Co",float("inf"))<=.5
        and quality.get("max_fluid_Co",float("inf"))<=.5
        and result.get("native_terminal_mesh",{}).get("status")=="PASS"
        and result.get("participant_exit_codes")=={"fluid":0,"solid":0}
    )
    verdict={
        "status":"RESTART_REFERENCE_8_WINDOW_STRICT_PASS" if strict_ok
                 else "RESTART_REFERENCE_8_WINDOW_STRICT_FAIL",
        "source":"91006 t=0.0325 certified",
        "test_only":True,
        "changed_setting":"FSI/restartFromDeformed false",
        "result":result,
        "do_not_adopt_without_scientific_review":True,
    }
    (work/"ALE_REFERENCE_CANDIDATE_RESULT.json").write_text(
        json.dumps(verdict,indent=2,ensure_ascii=False)+"\n")
    print(verdict["status"],"MESH_CO_MAX",quality.get("max_mesh_Co"),
          "ACCEPTED",result.get("accepted_windows"))
    if not strict_ok:sys.exit(3)

if __name__=="__main__":
    main()
