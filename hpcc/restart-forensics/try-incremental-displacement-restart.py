#!/usr/bin/env python3
"""Two-window FSI restart with displacement INCREMENTS, not a replay of full D.

Hypothesis:
- Current t=.0325 fluid already contains the accepted absolute pointDisplacement.
- Remapping absolute D after a new preCICE RBF registration changes the initial
  boundary field and produces an artificial first ALE mesh motion.
- Preserve saved absolute field; map only post-checkpoint DisplacementDelta.
- Use matching original-reference coupling mesh registrations (false, custom
  CCX referenceRestore hook) and keep initial Force exchange for CCX.

Critical upstream source checks:
- CalculiX adapter v2.20.2 PreciceInterface.c DISPLACEMENTDELTAS calls
  getNodeDisplacementDeltas(vold, coupling_init_v).
- The first Precice_WriteIterationCheckpoint() snapshots the current vold
  before first structural increment, so the initial delta reference is correct.
- OpenFOAM adapter v1.4.0 FSI/DisplacementDelta.C READ uses += on
  pointDisplacement, versus absolute Displacement.C READ uses assignment.

This is a NEW, unverified numerical method at the cross-job boundary.
Isolated directories only; never start multi-day work on its result without
matching 91543 at both accepted physical times and independent long tests.
All source files and ongoing job 91543 remain untouched.

The --self-test and --preflight paths never start FSI or Slurm.
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

DT = .000125
START = .0325
WINDOWS = 2
ROOT = Path.home() / "hpcc-fsi"
REFERENCE = ROOT / "three-day-proven/long-job-91543/runs/hpcc-implicit-002/solid/precice-Solid-watchintegral-Interface-Integral.log"
WATCH = "precice-Solid-watchintegral-Interface-Integral.log"


def exact(pattern, replacement, value, reason):
    changed, n = re.subn(pattern, replacement, value, count=0, flags=re.M)
    if n != 1:
        raise RuntimeError(f"{reason}: expected 1 substitution, got {n}")
    return changed


def patch_foam(text):
    # The native structural LD_PRELOAD hook always registers ORIGINAL coords.
    # Use original fluid coords as targets to avoid a mixed-frame new mapping.
    text = exact(r"\brestartFromDeformed\s+true\s*;",
                 "restartFromDeformed false;", text, "Fluid reference frame")
    text = exact(r"\breadData\s*\(\s*Displacement\s*\)\s*;",
                 "readData (DisplacementDelta);", text, "Fluid delta reader")
    if "readData (Displacement)" in text:
        raise RuntimeError("Absolute Displacement reader still present")
    return text


def patch_xml(xml):
    if "<coupling-scheme:parallel-implicit>" not in xml:
        raise RuntimeError("Expected source implicit coupling")
    original = re.findall(r'<exchange\b[^>]*\bdata="Displacement"[^>]*/>', xml)
    if len(original) != 1:
        raise RuntimeError(f"Exactly one absolute Displacement exchange required, got {len(original)}")
    old = original[0]
    if any(tag not in old for tag in ('mesh="Solid-Mesh"', 'from="Solid"', 'to="Fluid"')):
        raise RuntimeError("Unexpected displacement exchange mesh/direction")
    if re.search(r"\binitialize\s*=", old):
        raise RuntimeError("Displacement must NOT carry an initial exchange in the source")
    f = re.findall(r'<exchange\b[^>]*\bdata="Force"[^>]*/>', xml)
    if len(f) != 1 or any(tag not in f[0] for tag in ('mesh="Solid-Mesh"', 'from="Fluid"', 'to="Solid"')):
        raise RuntimeError("Expected one fluid-to-solid Force exchange")
    if re.search(r"\binitialize\s*=", f[0]):
        raise RuntimeError("Source Force already initialized")
    # Rename all names referring to preCICE's displacement data, while leaving
    # unrelated names (Force, mesh identifiers, schemes, limits) untouched.
    renamed, n = re.subn(r'(?<=")Displacement(?=")', "DisplacementDelta", xml)
    if n < 4:
        raise RuntimeError(f"Missing Displacement data/mesh/exchange/criterion references: {n}")
    if re.search(r'(?<=")Displacement(?=")', renamed):
        raise RuntimeError("Legacy absolute data remains in preCICE XML")
    if 'name="DisplacementDelta"' not in renamed:
        raise RuntimeError("No DisplacementDelta data definition")
    delta = re.findall(r'<exchange\b[^>]*\bdata="DisplacementDelta"[^>]*/>', renamed)
    if len(delta) != 1 or "initialize=" in delta[0]:
        raise RuntimeError("DisplacementDelta must exchange without initialize")
    old_force = f[0]
    new_force = old_force[:-2].rstrip() + ' initialize="yes" />'
    renamed = renamed.replace(old_force, new_force)
    force = re.findall(r'<exchange\b[^>]*\bdata="Force"[^>]*/>', renamed)
    if len(force) != 1 or 'initialize="yes"' not in force[0]:
        raise RuntimeError("Force must provide initial data to CCX")
    if renamed.count('initialize="yes"') != 1:
        raise RuntimeError("Force alone must have initialize=yes")
    return renamed


def patch_solid_yaml(text):
    # Preserve topology and patch names. A fail-closed source compatibility
    # check: exactly one write data name, no silent YAML transformations.
    if "write-data" not in text:
        raise RuntimeError("CalculiX config.yml lacks write-data")
    changed, n = re.subn(r"(?<![A-Za-z0-9_-])Displacement(?![A-Za-z0-9_-])",
                         "DisplacementDelta", text)
    if n != 1:
        raise RuntimeError(f"Expected one CCX absolute write-data, got {n}")
    if not re.search(r"\bwrite-data\s*:", changed):
        raise RuntimeError("CCX write-data key unavailable")
    if "DisplacementDelta" not in changed:
        raise RuntimeError("CCX delta writer not installed")
    return changed


def watch(path):
    if not path.is_file():
        raise RuntimeError(f"Missing accepted force reference: {path}")
    result = {}
    with path.open(errors="replace") as f:
        for line in f:
            cols = line.split()
            if len(cols) < 7:
                continue
            try:
                vals = [float(x) for x in cols[:7]]
            except ValueError:
                continue
            if all(math.isfinite(x) for x in vals):
                result[round(vals[0], 9)] = vals[1:]
    return result


def compare_accepted(reference, candidate):
    cont = watch(reference)
    new = watch(candidate)
    result = []
    for n in (1, 2):
        rel = round(n*DT, 9)
        cont_rel = round(.030 + rel, 9)  # continuous 91543 begins at .0025
        if rel not in new or cont_rel not in cont:
            raise RuntimeError(
                f"Unaccepted/missing matched window n={n} candidate={rel} reference={cont_rel}")
        f = new[rel]
        r = cont[cont_rel]
        fx_err = abs(f[0]-r[0])/max(abs(r[0]), 1e-12)
        if not all(math.isfinite(v) for v in (fx_err, *f, *r)):
            raise RuntimeError("Nonfinite accepted state")
        # The watch is a surface integral, not a local tip displacement.
        result.append({"window":n,"physical_time_s":START+rel,
                       "candidate_Fx_N":f[0],"continuous_Fx_N":r[0],
                       "Fx_rel_error":fx_err,
                       "candidate_Disp0_integral":f[3],
                       "continuous_Disp0_integral":r[3],
                       "candidate_Disp2_integral":f[5],
                       "continuous_Disp2_integral":r[5]})
    return result


def load_core(path):
    spec = importlib.util.spec_from_file_location("incremental_restart_private_core", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Invalid isolated core: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def source_check(base):
    source = base / "fsi-long-stage0-job91006/runs/hpcc-implicit-002"
    if not source.is_dir():
        raise RuntimeError("Missing frozen 91006 source")
    inputs = {
        "xml": source/"precice-config.xml",
        "fluid": source/"fluid/system/preciceDict",
        "solid": source/"solid/config.yml",
    }
    for label, path in inputs.items():
        if not path.is_file():
            raise RuntimeError(f"Missing source {label}: {path}")
    patch_xml(inputs["xml"].read_text())
    patch_foam(inputs["fluid"].read_text())
    patch_solid_yaml(inputs["solid"].read_text())
    if not (source/"restart_reference/Solid-Mesh.coords").is_file():
        raise RuntimeError("Missing CCX original-reference mesh snapshot")
    return source


def prepare(runfolder, meta, core, root):
    source = Path(meta["parent_run"])
    history = core.verify_staged_fluid_history(source, runfolder, 1)
    if any(r["staged_time_folders"] < 2 for r in history.values()):
        raise RuntimeError("Expected preserved historical fluid time directories")
    modifications = (
        ("precice-config.xml", patch_xml),
        ("fluid/system/preciceDict", patch_foam),
        ("solid/config.yml", patch_solid_yaml),
    )
    for relative, operation in modifications:
        p = runfolder / relative
        before = p.read_text()
        after = operation(before)
        if before == after:
            raise RuntimeError(f"No-op patch in {relative}")
        p.write_text(after)
    # This is an isolated short test; never purge the staged history.
    c = runfolder/"fluid/system/controlDict"
    conf = exact(r"\bpurgeWrite\s+\d+\s*;", "purgeWrite 0;", c.read_text(),
                 "Private history retention")
    c.write_text(conf)
    meta.update({
        "status":"STAGED_INCREMENTAL_DISPLACEMENT_CANDIDATE",
        "delta_data_from_solid":"DisplacementDelta",
        "fluid_pointDisplacement_kept_from_checkpoint":True,
        "initial_DisplacementDelta_required":False,
        "initial_Force_enabled":True,
        "new_preCICE_session_without_IQN_history":True,
        "source_restartFromDeformed_true_to_false":True,
        "scientific_equivalence_not_verified":True,
        "do_not_auto_chain":True,
    })
    core.jwrite(root/"FSI_SEGMENT_STAGE.json", meta)
    return runfolder, meta


def trial(base, work, corefile):
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("Must run in an isolated Slurm compute allocation")
    source = source_check(base)
    if work.exists() or not work.is_relative_to(base):
        raise RuntimeError("Refusing overlap or existing work")
    if source in work.parents or work in source.parents:
        raise RuntimeError("Refusing overwrite of frozen source")
    if "long-job-91543" in str(work) or "seagrass-fsi-mainline" in str(work):
        raise RuntimeError("Do not change live/production paths")
    core = load_core(corefile)
    old_choose, old_stage = core.choose_windows, core.stage_inputs

    def choose(stage, limit, speed):
        if stage != 1 or limit != WINDOWS:
            raise RuntimeError("Only isolated two-window test is allowed")
        return WINDOWS

    def stage(b, stage_number, prev, destination, limit, chain_root=None):
        runfolder, meta = old_stage(b, stage_number, prev, destination,
                                    limit, chain_root)
        return prepare(runfolder, meta, core, destination)

    core.choose_windows = choose
    core.stage_inputs = stage
    failure = None
    try:
        core.run(base, 1, 91006, work, WINDOWS, 3600,
                 base/"seagrass-fsi-mainline")
    except BaseException as exc:
        failure = repr(exc)
        traceback.print_exc()
    finally:
        core.choose_windows, core.stage_inputs = old_choose, old_stage

    saved = work/"FSI_SEGMENT_RESULT.json"
    native = json.loads(saved.read_text()) if saved.is_file() else None
    accepted, watch_error = [], None
    try:
        accepted = compare_accepted(
            base/"three-day-proven/long-job-91543/runs/hpcc-implicit-002/solid"/WATCH,
            work/"runs/hpcc-implicit-002/solid"/WATCH)
    except Exception as ex:
        watch_error = repr(ex)
    quality = native.get("quality", {}) if native else {}
    correct = bool(
        failure is None and watch_error is None and native is not None
        and native.get("status") == "FSI_LONG_SEGMENT_PASS"
        and native.get("accepted_windows") == WINDOWS
        and native.get("participant_exit_codes") == {"fluid":0,"solid":0}
        and native.get("native_terminal_mesh",{}).get("status") == "PASS"
        and quality.get("max_mesh_Co", math.inf) <= .5
        and quality.get("max_fluid_Co", math.inf) <= .5
        and all(row["Fx_rel_error"] <= .01 for row in accepted))
    report = {
        "status": "INCREMENTAL_DISPLACEMENT_TWO_WINDOW_PASS" if correct
                  else "INCREMENTAL_DISPLACEMENT_TWO_WINDOW_FAIL",
        "source_t_s": START,"next_t_s":START+WINDOWS*DT,
        "source_checkpoint_unchanged":True,"long_91543_untouched":True,
        "actual_native_result":native,"accepted_vs_continuous":accepted,
        "native_failure":failure,"watch_error":watch_error,
        "NEVER_AUTO_START_MULTIDAY":True,
    }
    if work.is_dir():
        (work/"INCREMENTAL_DISPLACEMENT_RESULT.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(report["status"],
          "errors", [x.get("Fx_rel_error") for x in accepted],
          "native_error", failure, "watch_error", watch_error, flush=True)
    if not correct:
        raise SystemExit(3)


def self_test():
    foam = """FSI {
    restartFromDeformed true; solverType incompressible;
    DisplacementInterface { readData (Displacement); }
    ForceInterface { readData (); }
    }"""
    corrected = patch_foam(foam)
    assert "restartFromDeformed false;" in corrected
    assert "readData (DisplacementDelta);" in corrected
    try:
        patch_foam(corrected)
    except RuntimeError:
        pass
    else:
        raise AssertionError("Repatch accepted")
    xml = """<precice-configuration>
<data:vector name="Force" />
<data:vector name="Displacement" />
<mesh name="Solid-Mesh" dimensions="3"><use-data name="Force" /><use-data name="Displacement" /></mesh>
<mesh name="Fluid-Mesh-Nodes" dimensions="3"><use-data name="Displacement" /></mesh>
<participant name="Fluid"><read-data name="Displacement" mesh="Fluid-Mesh-Nodes" /></participant>
<participant name="Solid"><write-data name="Displacement" mesh="Solid-Mesh" /></participant>
<coupling-scheme:parallel-implicit>
<exchange data="Force" mesh="Solid-Mesh" from="Fluid" to="Solid" />
<exchange data="Displacement" mesh="Solid-Mesh" from="Solid" to="Fluid" />
<relative-convergence-measure limit="1e-5" data="Displacement" mesh="Solid-Mesh" />
</coupling-scheme:parallel-implicit></precice-configuration>"""
    changed = patch_xml(xml)
    assert 'name="DisplacementDelta"' in changed
    assert 'data="DisplacementDelta"' in changed
    assert changed.count('initialize="yes"') == 1
    assert re.search(r'<exchange\b[^>]*data="DisplacementDelta"[^>]*initialize=',changed) is None
    assert "data:vector name=\"Force\"" in changed
    try:
        patch_xml(changed)
    except RuntimeError:
        pass
    else:
        raise AssertionError("Double XML patch accepted")
    for yaml in ("interfaces:\n  - write-data: [Displacement]\n",
                 "interfaces:\n  - write-data:\n      - Displacement\n"):
        assert patch_solid_yaml(yaml).count("DisplacementDelta") == 1
    try:
        patch_solid_yaml("write-data: [Displacement, Displacement]")
    except RuntimeError:
        pass
    else:
        raise AssertionError("Ambiguous CCX output accepted")
    import tempfile
    with tempfile.TemporaryDirectory() as temp:
        a=Path(temp)/"ref.log"
        b=Path(temp)/"trial.log"
        a.write_text("Time Force0 Force1 Force2 Displacement0 Displacement1 Displacement2\n"
                     "0.030125 0.018 0 0 30.1 0 -1.5\n"
                     "0.030250 0.019 0 0 30.2 0 -1.6\n")
        b.write_text("Time Force0 Force1 Force2 Displacement0 Displacement1 Displacement2\n"
                     "0.000125 0.018 0 0 30.1 0 -1.5\n"
                     "0.000250 0.019 0 0 30.2 0 -1.6\n")
        assert all(x["Fx_rel_error"]<1e-12 for x in compare_accepted(a,b))
        b.write_text(b.read_text().replace("0.018 0","0.072 0"))
        assert compare_accepted(a,b)[0]["Fx_rel_error"]>3
    print("INCREMENTAL_DISPLACEMENT_RESTART_OFFLINE_SELFTEST_PASS")


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--base",type=Path,default=ROOT)
    p.add_argument("--core",type=Path)
    p.add_argument("--work",type=Path)
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--preflight",action="store_true")
    p.add_argument("--run",action="store_true")
    args=p.parse_args()
    if args.self_test:
        return self_test()
    base=args.base.expanduser().resolve(strict=True)
    core=args.core or base/"crossjob-fix-20261116/segment.py"
    if not core.is_file():
        raise RuntimeError(f"Missing isolated FSI core: {core}")
    source_check(base)
    core_module=load_core(core)
    core_module.source_for(base,1,91006,base/"seagrass-fsi-mainline")
    if args.preflight:
        print("INCREMENTAL_DISPLACEMENT_RESTART_PREFLIGHT_PASS",
              "two-window only; no Slurm, no mutation")
        return
    if not args.run or args.work is None:
        p.error("Use --preflight or --run --work new_path")
    return trial(base,args.work.expanduser().resolve(),core)


if __name__=="__main__":
    main()
