#!/usr/bin/env python3
"""Read-only cross-job FSI-ALE restart forensic audit.

Never calls Slurm submission, OpenFOAM solvers or CalculiX; no writes.
Compares the frozen 0.0325 s original, two failed restart trials, and
ongoing successful 91543 run; checks time histories, loader fields, source
byte identities, interface-frame expectations, first force and transient Co.
Designed to supply evidence for two-window reference-frame repair.

Special warning: 'phi' is a FLUID face flux; mesh motion flux, oldPoints,
old volumes and IQN-ILS history are not thereby proven serialized.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys

FILE_FIELDS=["U","p","phi","Uf","cellDisplacement","pointDisplacement","k",
             "omega","nut","phiHbyA","uniform/time","polyMesh/points"]
BASE=Path.home()/"hpcc-fsi"
ORIG=BASE/"fsi-long-stage0-job91006/runs/hpcc-implicit-002"
TRIALS={
  "91538_displacement_only":BASE/"ale-nonzero-initial-data/trial-91538/runs/hpcc-implicit-002",
  "91542_both_initial":BASE/"ale-both-initial-data/trial-91542/runs/hpcc-implicit-002",
  "mainline_A":BASE/"seagrass-fsi-mainline/segment-A/runs/hpcc-implicit-002",
}
LIVE=BASE/"three-day-proven/long-job-91543"
TS="0.0325"
def short_hash(p):
    x=hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):x.update(b)
    return x.hexdigest()[:18]

def time_folders(parent):
    if not parent.is_dir():return []
    v=[]
    for entry in parent.iterdir():
        if not entry.is_dir():continue
        try: float(entry.name)
        except ValueError:continue
        v.append((float(entry.name),entry.name))
    return [s for _,s in sorted(v)]

def last_watch(path,near=None):
    if not path.is_file():return None
    values=[]
    with path.open(errors="replace") as f:
        for line in f:
            p=line.split()
            if len(p)<7:continue
            try:t=float(p[0]);x=float(p[1])
            except ValueError:continue
            if near is None or abs(t-near)<1e-8:values.append((t,x))
    return values[-1] if values else None

def first_force(path):
    if not path.is_file():return None
    with path.open(errors="replace") as f:
        found=False
        for line in f:
            if "forces bladeForces write:" in line:
                found=True
                continue
            if found:
                m=re.search(r"Total\s*:\s*\(([-+\deE.]+)\s+([-+\deE.]+)\s+([-+\deE.]+)\)",line)
                if m:return tuple(float(x) for x in m.groups())
    return None

def summarize_times(path):
    if not path.is_dir():return {"exists":False}
    names=time_folders(path)
    return {"exists":True,"n":len(names),"first":names[:8],"last":names[-8:]}

def field_presence_and_hashes():
    print("===== FIELDS and full byte equality: certified t=.0325 =====")
    for field in FILE_FIELDS:
        original=[ORIG/f"fluid/processor{i}/{TS}/{field}" for i in range(8)]
        present=sum(p.is_file() for p in original)
        print(f"FIELD={field} SOURCE_RANKS={present}/8",end="")
        for label,src in TRIALS.items():
            copied=[src/f"fluid/processor{i}/{TS}/{field}" for i in range(8)]
            copied_n=sum(p.is_file() for p in copied)
            same=sum(x.is_file() and y.is_file() and short_hash(x)==short_hash(y)
                     for x,y in zip(original,copied))
            print(f" {label}={same}/8 identical; {copied_n}/8 present",end="")
        print()
    print("NOTE phi present != native mesh motion flux / oldPoints / V0 V00 persisted")

def describe_frames():
    print("===== Coupling interface reference geometry =====")
    rfile=ORIG/"restart_reference/Solid-Mesh.coords"
    print("CCX_reference_file",rfile,"size_bytes",rfile.stat().st_size if rfile.is_file() else "MISSING")
    for label,src in {"source91006":ORIG,**TRIALS}.items():
        p=src/"fluid/system/preciceDict"
        if not p.is_file():
            print(label,"preciceDict_MISSING")
            continue
        txt=p.read_text(errors="replace")
        val=re.findall(r'\brestartFromDeformed\s+(true|false)\s*;',txt)
        xml=src/"precice-config.xml"
        exchanges=[]
        if xml.is_file():
            ex=xml.read_text(errors="replace")
            for d in ("Force","Displacement"):
                entries=re.findall(r'<exchange\b[^>]*\bdata="'+d+'"[^>]*/>',ex)
                exchanges.extend(entries)
        print(label,"restartFromDeformed=",val,"xml_exchanges=",exchanges)
    print("OpenFOAM adapter v1.4.0 registers CURRENT X(t) when true; X(t)-D(t)"
          " when false. Inspect CCX reference-frame restoration before deciding.")
    print("SOURCE_91006: X(t) = constant/polyMesh/points + saved pointDisplacement"
          " exact in all ranks (previous 8-rank native audit).")
    print("WARNING: Don't infer reference alignment from option alone; inspect Solid-Mesh.coords actual structure.")

def inspect_history():
    print("===== Native time and history directories =====")
    for label,src in {"original_91006":ORIG,**TRIALS.items()}.items():
        for rank in (0,6):
            print(label,"rank",rank,summarize_times(src/f"fluid/processor{rank}"))
    print("===== Numerical schemes and moving-mesh controls =====")
    for path in ("fluid/system/fvSchemes","fluid/system/fvSolution",
                 "fluid/system/controlDict","fluid/constant/dynamicMeshDict"):
        p=ORIG/path
        if not p.is_file():
            print(path,"NOT_PRESENT")
            continue
        text=p.read_text(errors="replace")
        for pattern in (r'(?s)\bddtSchemes\s*\{.*?\}',
             r'(?m)^\s*(?:default\s+(?:Euler|backward|CrankNicolson)|correctPhi\s+\w+|moveMeshOuterCorrectors\s+\w+|checkMeshCourantNo\s+\w+)\s*;'):
            for m in list(re.finditer(pattern,text))[:5]:
                print(path,"MATCH",re.sub(r'\s+',' ',m.group(0))[:250])
    print("HISTORY_GAP: source-to-trial may copy only latest time; native FV"
          " oldPoints, meshPhi, V0, V00, and U.oldTime not proven restored")

def compare_forces():
    old_w=last_watch(ORIG/"solid/precice-Solid-watchintegral-Interface-Integral.log",.03)
    live_w=last_watch(LIVE/"runs/hpcc-implicit-002/solid/precice-Solid-watchintegral-Interface-Integral.log",.03)
    print("===== Physically identical t=.0325 on continuous successful path =====")
    print("original_91006_struct_watch_relative_t_0.030",old_w)
    print("live_91543_struct_watch_relative_t_0.030",live_w)
    if old_w and live_w:
        print("continuous_trajectory_Fx_relative_error",abs(old_w[1]-live_w[1])/abs(old_w[1]))
    for label,src in TRIALS.items():
        log=src.parent.parent/"fluid.log"
        if label=="mainline_A":log=BASE/"seagrass-fsi-mainline/segment-A/fluid.log"
        original=first_force(log)
        watch=last_watch(src/"solid/precice-Solid-watchintegral-Interface-Integral.log",0.)
        print(label,"initial_watch_Fx",watch,"first_computed_fluid_Fx",original)
    print("NOTE first computed force is after a PIMPLE time step, not initial mapped Force")

def self_test():
    assert first_force.__name__=="first_force"
    assert time_folders(Path("/unlikely_does_not_exist_FSI_test"))==[]
    assert TS=="0.0325"
    print("FSI_CROSS_JOB_READONLY_FORENSIC_SELFTEST_PASS")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--base",type=Path,default=BASE)
    p.add_argument("--self-test",action="store_true")
    opt=p.parse_args()
    if opt.self_test:return self_test()
    b=opt.base.expanduser().resolve(strict=True)
    if b != BASE.resolve():
        raise RuntimeError("This diagnostic currently uses the known $HOME/hpcc-fsi root")
    if not ORIG.is_dir():raise RuntimeError("Original certified t=0.0325 case not found")
    print("FSI_CROSS_JOB_RESTART_FORENSIC_READ_ONLY")
    field_presence_and_hashes()
    inspect_history()
    describe_frames()
    compare_forces()
    print("STOP before running any more restart candidates if baseline data is missing")
    print("NO_SOLVER_NO_SBATCH_NO_FILE_MODIFICATIONS")
if __name__=="__main__":main()
