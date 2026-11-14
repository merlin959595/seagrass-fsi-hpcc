#!/usr/bin/env python3
"""G1-B: evidence-only, bounded restart blocker audit for finished HPCC FSI.

This reads the deployed production controller and finished frozen cases only.
Does not execute, import, or patch the controller, launch a solver, submit
Slurm work, copy binaries, or change any result. Stdout is the only output.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

CONTROLLER = "seagrass-implicit-20261111/fsi-implicit-production/run_production.py"
RUNS = {
    "87186": "implicit-pilot-002-8mpi-timefix-87186/production/runs/hpcc-implicit-002",
    "89038": "performance-full160-job-89038/optimized-160/runs/hpcc-implicit-002",
    "89270": "performance-omp12-iqn15-job-89270/optimized-20/runs/hpcc-implicit-002",
}
EXCERPTS = ((1, 110), (145, 220), (240, 275), (302, 348))
CONFIG_NAMES = (
    "solid/seagrass.inp", "solid/config.yml", "precice-config.xml",
    "fluid/system/controlDict", "fluid/system/preciceDict",
)
HISTORY_FILTER = re.compile(
    r"restart|checkpoint|spooles|rout|rin\b|kinematic|reference|"
    r"write|persist|finish|fatal|error|terminate|time[ -]?step|"
    r"fluid[- ]?step|(?<!\w)ccx\b", re.I
)


def sha256(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1<<20),b""):
            h.update(chunk)
    return h.hexdigest()


def file_record(path):
    try:
        s=path.lstat()
        return {"exists":True,"size_bytes":s.st_size,
                "is_file":path.is_file(),"is_dir":path.is_dir(),
                "symlink":path.is_symlink()}
    except OSError:
        return {"exists":False}


def print_source(path):
    print("\n==== DEPLOYED CONTROLLER EXCERPTS (line-numbered) ====")
    if not path.is_file():
        print("BLOCKER: deployed controller missing",path)
        return
    print("path",path,"sha256",sha256(path))
    lines=path.read_text(errors="replace").splitlines()
    print("line_count",len(lines))
    for lo,hi in EXCERPTS:
        print("\n-- CONTROLLER LINES",lo,"TO",min(hi,len(lines)),"--")
        for i in range(lo,min(hi,len(lines))+1):
            print(f"{i:04d}: {lines[i-1][:260]}")
    if len(lines)>EXCERPTS[-1][1]:
        print(f"NOTE: source has {len(lines)} lines; excerpt excludes beyond {EXCERPTS[-1][1]}")


def print_file_tree(folder, max_items=55):
    if not folder.exists():
        print("MISSING:",folder)
        return
    if folder.is_file():
        print(str(folder), file_record(folder))
        return
    if not folder.is_dir():
        print("OTHER:",folder)
        return
    children=sorted(folder.iterdir(),key=lambda p:p.name)
    print("path",folder,"entries",len(children))
    for p in children[:max_items]:
        print(" ",p.name, file_record(p))
    if len(children)>max_items:
        print("  ... truncated",len(children)-max_items,"entries")


def print_binary_probe(run):
    solid=run/"solid"
    print("\n-- STRUCTURAL RESTART FILES / TOP-LEVEL INVENTORY --")
    print_file_tree(solid,max_items=55)
    candidates=[]
    if solid.is_dir():
        for p in solid.iterdir():
            if p.is_file() and (p.suffix.lower() in (
                ".rout",".rin",".bin",".dat",".sta",".res",".log"
            ) or "restart" in p.name.lower() or "spooles" in p.name.lower()):
                candidates.append(p)
    print("restart-related candidate count",len(candidates))
    for p in candidates[:60]:
        print(" candidate",p.name,file_record(p),
              "sha256" if p.suffix.lower() in (".rout",".rin",".bin") else "",
              sha256(p) if p.suffix.lower() in (".rout",".rin",".bin") and p.stat().st_size<=64*1024*1024 else "")
    for rel in ("solid/seagrass.rout","solid/seagrass.rin",
                "solid/kinematic_state.bin","solid/kinematic_state.input.bin"):
        p=run/rel
        print("required",rel,file_record(p))
    print("\n-- INTERFACE REFERENCE DIRECTORY --")
    print_file_tree(run/"restart_reference",max_items=60)
    print("\n-- DYNAMIC FLUID FIELDS FOR ALL RANKS AT END --")
    fluid=run/"fluid"
    procs=sorted(fluid.glob("processor[0-9]*"),key=lambda x:int(x.name[9:]))
    print("processors",len(procs))
    all_t=[]
    for proc in procs:
        entries=[]
        for child in proc.iterdir():
            if not child.is_dir():
                continue
            try:
                t=float(child.name)
                if t>=0 and t<1e9:
                    entries.append((t,child))
            except ValueError:
                pass
        if not entries:
            print(proc.name,"NO_NUMERIC_TIME_DIRECTORY")
            continue
        t,d=max(entries,key=lambda x:x[0])
        all_t.append(t)
        fields={f:file_record(d/f)["exists"] for f in
                ("U","p","phi","pointDisplacement",
                 "polyMesh/points","polyMesh/oldPoints","uniform/time")}
        constants={f:file_record(proc/"constant"/f)["exists"] for f in
                   ("polyMesh/points","motionReferenceDiffusivity")}
        print(proc.name, "latest_t",t,"latest",fields,"constant",constants)
    if all_t and max(all_t)-min(all_t)>1e-10:
        print("BLOCKER: processor output time mismatch",all_t)


def tail(path, max_bytes=200000, matches=15):
    if not path.is_file():
        print("MISSING LOG",path)
        return
    with path.open("rb") as f:
        f.seek(0,os.SEEK_END)
        n=f.tell()
        f.seek(max(0,n-max_bytes))
        txt=f.read().decode(errors="replace")
    print("LOG",path.name,"bytes_total",n)
    rows=[v[:220] for v in txt.splitlines() if HISTORY_FILTER.search(v)]
    for x in rows[-matches:]:
        print("  ",x)


def audit_run(key,run):
    print("\n","="*14,"CASE",key,"="*14)
    print("RUN",run)
    if not run.is_dir():
        print("BLOCKER: missing work tree")
        return
    print_binary_probe(run)
    for name in CONFIG_NAMES:
        f=run/name
        print("\n-- CONFIG",name,file_record(f),"--")
        if f.is_file():
            for idx,line in enumerate(f.read_text(errors="replace").splitlines(),1):
                if re.search(r"restart|startFrom|startTime|endTime|time-window|"
                             r"max-time|^\\s*\\*DYNAMIC|^\\s*\\*STEP|^\\s*\\*END STEP|"
                             r"^\\s*\\*RESTART|precice|displacement|"
                             r"interface|read-data|write-data|writeInterval|"
                             r"writeControl|rhoInf",line,re.I):
                    print(f"{idx:04d}: {line[:230]}")
    print("\n-- RELEVANT TERMINATION LOGS --")
    for item in ("solid.log","solid/spooles.out","fluid.log"):
        tail(run/item,100000,10)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base",type=Path,default=Path.home()/"hpcc-fsi")
    p.add_argument("--case",choices=("87186","89038","89270","all"),default="89038")
    p.add_argument("--self-test",action="store_true")
    args=p.parse_args()
    if args.self_test:
        assert re.search(r"(?<!\w)ccx\b","launch ccx -i ...",re.I)
        assert re.search(r"restart|checkpoint","*RESTART,WRITE",re.I)
        assert len(EXCERPTS)==4
        print("G1_BLOCKER_AUDIT_STATIC_TEST_PASS")
        return
    base=args.base.expanduser().resolve(strict=True)
    print("G1_BLOCKER_READ_ONLY_START")
    print("base",base)
    print_source(base/CONTROLLER)
    if args.case=="all":
        for key,rel in RUNS.items():
            audit_run(key,base/rel)
    else:
        audit_run(args.case,base/RUNS[args.case])
    print("G1_RESTART_STILL_UNVERIFIED")
    print("NO_SLURM_NO_SOLVER_NO_MODIFICATION")


if __name__=="__main__":
    sys.exit(main())
