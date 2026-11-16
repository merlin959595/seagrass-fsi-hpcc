#!/usr/bin/env python3
"""G2 targeted candidate: CPU affinity isolation, SAME solver/model/physics.

Reuses frozen 87186-based 20-window benchmark, actual preCICE 1e-5 checks,
and proven 4 OMP + IQN15. Only changes CPU affinity on the two participants:
8 CPU cores Fluid MPI vs 4 CPU cores CalculiX, with no core overlap.

In Slurm compute allocation only. Never changes original cases.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

def split_cpus(cpus):
    xs=sorted(cpus)
    if len(xs)<12:
        raise RuntimeError(f"Need >=12 permitted CPUs for 8 MPI + 4 OMP; found {xs}")
    fluid=xs[:8]
    solid=xs[8:12]
    assert not(set(fluid)&set(solid))
    return fluid,solid

def resolve_cwd(cwd):
    return Path(cwd).resolve() if cwd is not None else Path.cwd()

def self_test():
    a,b=split_cpus(range(16,28))
    assert a==list(range(16,24)) and b==list(range(24,28))
    try:split_cpus(range(11))
    except RuntimeError:pass
    else:raise AssertionError("Accepted fewer than 12 permitted CPUs")
    # Regression for failed job 91019: subprocess.run() leaves cwd=None.
    # The exact bug was Path(None) during initial native checkMesh.
    assert resolve_cwd(None)==Path.cwd()
    assert resolve_cwd(Path("/tmp/a"))==Path("/tmp/a")
    print("G2_AFFINITY_ISOLATION_SELF_TEST_PASS")

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--work",type=Path)
    p.add_argument("--base",type=Path,default=Path.home()/"hpcc-fsi")
    p.add_argument("--self-test",action="store_true")
    args=p.parse_args()
    if args.self_test:self_test();return
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("Affinity candidate requires a compute allocation")
    allowed=os.sched_getaffinity(0)
    fluid,solid=split_cpus(allowed)
    if not shutil_which_taskset():
        raise RuntimeError("taskset executable missing")
    if args.work is None:p.error("--work is required")
    work=args.work.expanduser().resolve()
    base=args.base.expanduser().resolve(strict=True)
    for src in ("implicit-pilot-002-8mpi-timefix-87186",
                "performance-full160-job-89038",
                "seagrass-implicit-20261111"):
        if work==base/src or (base/src) in work.parents:
            raise RuntimeError("Cannot mutate frozen source")
    bench=base/"benchmark-short-fsi.py"
    spec=importlib.util.spec_from_file_location("benchmark_g2_pinned",bench)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Popen monkeypatch only during imported benchmark run. The original
    # benchmark controller intercepts CalculiX to set OMP_NUM_THREADS=4.
    # We only change process affinity via taskset, never dictionaries.
    orig=subprocess.Popen
    hits={"fluid":0,"solid":0}
    record={"fluid_cpus":fluid,"solid_cpus":solid,
            "allowed_cpus":sorted(allowed),
            "parameters":{"fluid_mpi":8,"solid_omp":4,
                          "iqn_reuse":15,"windows":20,"dt_s":0.000125},
            "affinity_candidate_only":True,
            "solver_changes":False,"model_changes":False}
    def wrapper(cmd,*pos,**kw):
        # subprocess.run uses Popen(..., cwd=None) when no cwd was supplied.
        # Never evaluate Path(None); the unmodified benchmark calls utilities
        # with both explicit cwd and no cwd.
        cwd_value=kw.get("cwd")
        cwd=resolve_cwd(cwd_value)
        components=[str(x) for x in cmd]
        name=None
        if cwd.name=="fluid" and cwd.parent.name=="hpcc-implicit-002":
            if any("pimpleFoam" in item for item in components):
                name="fluid"
        elif cwd.name=="solid" and cwd.parent.name=="hpcc-implicit-002":
            if any("ccx_preCICE_persistent_v2" in item for item in components):
                name="solid"
        if name:
            cores=fluid if name=="fluid" else solid
            cmd=["taskset","-c",",".join(map(str,cores))]+list(cmd)
            hits[name]+=1
            print("G2_AFFINITY_APPLIED",name,"cpus",cores,
                  "hits",hits[name],flush=True)
        return orig(cmd,*pos,**kw)

    subprocess.Popen=wrapper
    old_argv=sys.argv[:]
    try:
        sys.argv=[str(bench),"--work",str(work),
                  "--windows","20","--threads","4","--iqn-reuse","15"]
        module.main()
    finally:
        sys.argv=old_argv
        subprocess.Popen=orig

    if hits!={"fluid":1,"solid":1}:
        raise RuntimeError(f"Expected one actual launch per participant: {hits}")
    result=work/"PERFORMANCE_RESULT.json"
    if not result.is_file():
        raise RuntimeError("No actual benchmark success evidence")
    outcome=json.loads(result.read_text())
    if outcome.get("status")!="SHORT_FSI_PERFORMANCE_PASS":
        raise RuntimeError("Benchmark did not pass coupled FSI acceptance")
    record.update({"status":"G2_AFFINITY_20WINDOW_PASS",
                   "participant_launches":hits,
                   "wall_s":outcome.get("wall_s"),
                   "s_per_window":outcome.get("s_per_window"),
                   "coupling_iterations":outcome.get("coupling_iterations"),
                   "comparability_note":"Cross-node runtime comparison is indicative; require same-node or repeat for confirmed speedup."})
    (work/"G2_AFFINITY_RESULT.json").write_text(json.dumps(record,indent=2)+"\n")
    print("G2_AFFINITY_20WINDOW_PASS",json.dumps(record),flush=True)

def shutil_which_taskset():
    from shutil import which
    return which("taskset") is not None

if __name__=="__main__":
    main()
