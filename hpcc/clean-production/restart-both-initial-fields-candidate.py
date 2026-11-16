#!/usr/bin/env python3
"""Real 2-window FSI restart trial initializing BOTH absolute Displacement and Force.

Candidate ONLY; requires a native Slurm allocation. Frozen source: certified
91006, t=0.0325 s. Other physics/dynamic-mesh and restart settings unchanged.
One added XML attribute on each exchange, nothing else. Report:
  * actual Force initialization mapping in Fluid log (no skipped zero sample)
  * Solid watchintegral initial Force0 compared to certified t=0.0325 source
  * 2 native accepted windows, both exit0, and strict meshCo<=0.5 throughout
  * no FPE, mesh guard/native checkMesh PASS, new state and checkpoint files.
"""
import argparse
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
import traceback

ROOT=Path.home()/"hpcc-fsi"
PREV=ROOT/"clean-production-src/restart-initial-data-candidate.py"
SOURCE=ROOT/"fsi-long-stage0-job91006/runs/hpcc-implicit-002"

def import_previous():
    # Use a private helper shipped with this isolated test when present.
    local=Path(__file__).resolve().with_name("restart-initial-data-candidate.py")
    source=local if local.is_file() else PREV
    if not source.is_file():
        raise RuntimeError("Missing previously self-tested absolute-displacement candidate")
    sp=importlib.util.spec_from_file_location("prior_initial_candidate",source)
    p=importlib.util.module_from_spec(sp)
    sp.loader.exec_module(p)
    return p

def add_force(xml):
    pattern=r'(<exchange\b[^>]*\bdata="Force"[^>]*/>)'
    found=re.findall(pattern,xml)
    if len(found)!=1:
        raise RuntimeError("Expected one fluid-to-solid Force exchange")
    old=found[0]
    for key in ('mesh="Solid-Mesh"','from="Fluid"','to="Solid"'):
        if key not in old:
            raise RuntimeError("Unexpected force exchange")
    if re.search(r'\binitialize\s*=',old):
        raise RuntimeError("Force was already initialized in source")
    new=old[:-2].rstrip()+' initialize="yes" />'
    xml=xml.replace(old,new)
    if xml.count('initialize="yes"')!=2:
        raise RuntimeError("Expected exactly two initial data exchanges")
    return xml

def patch(xml):
    p=import_previous()
    return add_force(p.patch_precice_xml(xml))

def parse_watch(path):
    if not path.is_file():
        raise RuntimeError(f"No watch integral: {path}")
    rows=[]
    for line in path.read_text().splitlines():
        p=line.split()
        if not p or p[0]=="Time":continue
        if len(p)<7:continue
        try:rows.append((float(p[0]),float(p[1])))
        except ValueError:continue
    return rows

def evidence(base,work,source):
    old=source/"solid/precice-Solid-watchintegral-Interface-Integral.log"
    new=work/"runs/hpcc-implicit-002/solid/precice-Solid-watchintegral-Interface-Integral.log"
    old_rows=parse_watch(old)
    if not old_rows:raise RuntimeError("Original Force reference log empty")
    expected_time=old_rows[-1][0]
    expected=old_rows[-1][1]
    if abs(expected_time-.030)>1e-7 or not 0.01<expected<0.03:
        raise RuntimeError("Source t=0.0325 FSI interface Force is not qualified")
    try:new_rows=parse_watch(new)
    except Exception:new_rows=[]
    zero=[x for x in new_rows if abs(x[0])<1e-12]
    observed=zero[0][1] if zero else None
    diff=(abs(observed-expected)/abs(expected)) if observed is not None else None
    fpath=work/"fluid.log";spath=work/"solid.log"
    fluid=fpath.read_text(errors="replace") if fpath.is_file() else ""
    solid=spath.read_text(errors="replace") if spath.is_file() else ""
    # Avoid counting a fallback force sample at a later t as proof of initial
    # loaded pressure forces. Require t=0 map without 'skipped zero sample'.
    initial_lines=[s.strip() for s in fluid.splitlines()
      if 'Mapping "Force" for t=0 from "Fluid-Mesh-Faces" to "Solid-Mesh"' in s]
    initialized=any("skipped zero sample" not in x for x in initial_lines)
    first_force=[]
    chunks=fluid.split("forces bladeForces write:")
    for c in chunks[1:]:
        m=re.search(r'Total\s*:\s*\(([-+\d.eE]+)\s+([-+\d.eE]+)\s+([-+\d.eE]+)\)',c)
        if m:first_force.append([float(x) for x in m.groups()])
    first_force0=first_force[0][0] if first_force else None
    first_force_error=(abs(first_force0-expected)/abs(expected)) if first_force0 is not None else None
    return dict(
      source_last_force0_N=expected,
      source_last_watch_time_relative_s=expected_time,
      new_initial_force0_N=observed,
      new_initial_force0_rel_error=diff,
      initial_force_map_lines=initial_lines[:6],
      initial_force_map_not_zero_skipped=initialized,
      first_fluid_forces=first_force[:3],
      first_fluid_force0_relative_jump=first_force_error,
      first_fluid_force0_within_20pct=(first_force_error is not None and first_force_error<=.20),
      min_displacement_mesh_courant_note="Check original independent quality evidence",
      solid_finished_with_error=bool(re.search(r"\*ERROR:.*|solution seems to diverge",solid,re.I)),
      initial_force_within_10pct=(diff is not None and diff<=.10),
    )

def self_test():
    sample='''<precice-configuration><coupling-scheme:parallel-implicit>
<exchange data="Force" mesh="Solid-Mesh" from="Fluid" to="Solid" />
<exchange data="Displacement" mesh="Solid-Mesh" from="Solid" to="Fluid" />
</coupling-scheme:parallel-implicit></precice-configuration>'''
    s=patch(sample)
    assert s.count('initialize="yes"')==2
    assert 'data="Force" mesh="Solid-Mesh" from="Fluid" to="Solid" initialize="yes"' in s
    assert 'data="Displacement" mesh="Solid-Mesh" from="Solid" to="Fluid" initialize="yes"' in s
    try:patch(s)
    except RuntimeError:pass
    else:raise AssertionError("Re-patching already modified input accepted")
    print("FSI_BOTH_INITIAL_FIELDS_TWO_WINDOW_SELF_TEST_PASS")

def run(base,work):
    p=import_previous()
    orig=p.patch_precice_xml
    old_n=p.N
    p.patch_precice_xml=patch_inner=add_force_after_displacement(orig)
    p.N=2
    try:
        p.check_source(base)
        try:
            p.run(base,work)
        except BaseException as ex:
            failure=repr(ex)
        else:
            failure=None
    finally:
        p.patch_precice_xml=orig
        p.N=old_n
    diag=evidence(base,work,SOURCE)
    result_file=work/"INITIAL_DISPLACEMENT_TEST_RESULT.json"
    prior=json.loads(result_file.read_text()) if result_file.is_file() else {}
    # Parent has stringent all-window quality gates.
    ok=bool(
       failure is None and
       prior.get("status")=="ALE_NONZERO_INITIAL_DISPLACEMENT_8WINDOW_PASS" and
       diag["initial_force_map_not_zero_skipped"] and
       diag["initial_force_within_10pct"] and
       diag["first_fluid_force0_within_20pct"] and
       not diag["solid_finished_with_error"])
    outcome=dict(
       status="BOTH_INITIAL_FIELDS_2WINDOW_STRICT_PASS" if ok else "BOTH_INITIAL_FIELDS_2WINDOW_NOT_ACCEPTED",
       source=".0325s certified 91006",
       end_target=".03275s 2 windows",
       initial_data_exchanges="Force and Displacement initialize=yes",
       original_physics_parameters_untouched=True,
       successful_initial_force_continuity=diag["initial_force_within_10pct"],
       force_evidence=diag,
       original_2window_runtime_verdict=prior,
       runtime_error=failure,
       do_not_start_production_automatically=True)
    (work/"BOTH_INITIAL_FIELDS_2WINDOW_RESULT.json").write_text(
       json.dumps(outcome,indent=2,ensure_ascii=False)+"\n")
    print(outcome["status"],
          "INIT_FORCE_N",diag["new_initial_force0_N"],
          "SOURCE_N",diag["source_last_force0_N"],
          "FIRST_COMPUTED_FORCE",diag["first_fluid_forces"][:1],flush=True)
    if not ok:sys.exit(3)

def add_force_after_displacement(orig):
    def apply(xml):return add_force(orig(xml))
    return apply

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--base",type=Path,default=ROOT)
    parser.add_argument("--work",type=Path)
    parser.add_argument("--run",action="store_true")
    parser.add_argument("--preflight",action="store_true")
    parser.add_argument("--self-test",action="store_true")
    opts=parser.parse_args()
    if opts.self_test:return self_test()
    b=opts.base.expanduser().resolve(strict=True)
    p=import_previous()
    p.check_source(b)
    if opts.preflight:
        p.load_core(b/"seagrass-fsi-mainline/bin/segment.py").source_for(
          b,1,91006,b/"seagrass-fsi-mainline")
        sample=(SOURCE/"precice-config.xml").read_text()
        assert patch(sample).count('initialize="yes"')==2
        print("FSI_BOTH_INITIAL_FIELDS_PRECHECK_PASS")
        return
    if not opts.run or opts.work is None:
        parser.error("requires --run and --work")
    run(b,opts.work.expanduser().resolve())

if __name__=="__main__":
    main()
