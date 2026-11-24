#!/usr/bin/env python3
"""Native OpenFOAM-only diagnostic of job98512 at first failed time 0.563625s.

Creates a NEW independent mesh copy on /data/icto only when --submit is
explicitly provided. No change to native FSI cases/checkpoints. No new FSI.
Native checkMesh runs in a small 8-core Slurm job on 0.563500 and 0.563625.
"""
import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

TIMES=("0.5635","0.563625")
JOB="98512"
RANKS=range(8)

def fail(code,problem):
    print("NATIVE98512_PRECHECK_BLOCKED",problem,file=sys.stderr)
    raise SystemExit(code)

def paths():
    user=os.environ.get("USER")
    if not user:fail(10,"USER_NOT_SET")
    base=Path("/data/icto")/user/"seagrass-fsi558-runs.sNIpi9"
    work=base/"trial-98512-bed2758-s1"
    source=work/"runs/hpcc-implicit-002/fluid"
    dest=base/"diagnostics/native-first-window-98512"
    img=Path.home()/"seagrass-fsi-ompi507-scotch-time.sif"
    return work,source,dest,img

def snapshot_manifest(source):
    missing=[]
    filemap=[]
    for r in RANKS:
        local=source/f"processor{r}"
        for name in ("points","faces","owner","neighbour","boundary"):
            path=local/"constant/polyMesh"/name
            if not path.is_file() or path.stat().st_size==0:
                missing.append(str(path))
            else:filemap.append((path,f"processor{r}/constant/polyMesh/{name}"))
        for t in TIMES:
            path=local/t/"polyMesh/points"
            if not path.is_file() or path.stat().st_size==0:
                missing.append(str(path))
            else:filemap.append((path,f"processor{r}/{t}/polyMesh/points"))
        for name in ("fvSchemes","fvSolution"):
            path=local/"system"/name
            if not path.is_file() or path.stat().st_size==0:
                path=source/"system"/name
            if not path.is_file() or path.stat().st_size==0:
                missing.append(str(path))
            else:filemap.append((path,f"processor{r}/system/{name}"))
    return filemap,missing

def preflight():
    work,source,dest,img=paths()
    if not source.is_dir() or not img.is_file():
        fail(11,"SOURCE_CASE_OR_NATIVE_IMAGE_NOT_FOUND")
    log=work/"fluid.log"
    if not log.is_file():fail(12,"NATIVE_98512_FLUID_LOG_MISSING")
    evidence=False
    with log.open(errors="replace") as f:
        for line in f:
            if ("SEAGRASS_MESH_GUARD time=0.563625" in line and
                "concave=1" in line and "tetFailed=1" in line):
                evidence=True
                print("CONFIRMED_FIRST_WINDOW_FAILED_GUARD",line.strip())
                break
    if not evidence:fail(13,"REQUIRED_NATIVE_98512_FIRST_WINDOW_FAILURE_NOT_CONFIRMED")
    filemap,missing=snapshot_manifest(source)
    if missing:
        print("FIRST_WINDOW_SNAPSHOT_INCOMPLETE",len(missing))
        for name in missing[:20]:print("MISSING",name)
        fail(14,"ONE_OR_MORE_MPI_MESH_SNAPSHOTS_OR_SYSTEM_DICTIONARIES_MISSING")
    print("ALL_8_MPI_SNAPSHOTS_VERIFIED_AT",TIMES)
    print("COPIABLE_INPUT_FILES",len(filemap))
    print("NATIVE_CHECKMESH_PRIVATE_DESTINATION",dest)
    print("AUTHORITATIVE_SOURCE_UNCHANGED",source)
    return work,source,dest,img,filemap

def digest(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for x in iter(lambda:f.read(1<<20),b""):
            h.update(x)
    return h.digest()

CONTROL="""FoamFile
{
    version 2.0;
    format ascii;
    class dictionary;
    object controlDict;
}
application checkMesh;
startFrom startTime;
startTime 0.5635;
stopAt endTime;
endTime 0.563625;
deltaT 0.000125;
writeControl timeStep;
writeInterval 1;
"""

NATIVE_SCRIPT="""#!/bin/bash
set -Eeuo pipefail
case_dir="$1"
t="$2"
unset BASH_ENV ENV
export WM_MPLIB=SYSTEMOPENMPI
set +eu
source /usr/lib/openfoam/openfoam2512/etc/bashrc
source_rc=$?
set -eu
if [ "$source_rc" -ne 0 ] || [ "$WM_PROJECT_VERSION" != v2512 ]; then
    echo "WRONG_OPENFOAM_ENVIRONMENT"
    exit 52
fi
export PATH="/opt/openmpi-5.0.7/bin:/opt/precice-3.4.1-ompi5/bin:$PATH"
export LD_LIBRARY_PATH="/opt/openmpi-5.0.7/lib:/opt/openmpi-5.0.7/lib64:/opt/scotch-compat/lib:$LD_LIBRARY_PATH"
cd "$case_dir"
exec mpirun --oversubscribe -np 8 checkMesh -parallel -time "$t" -allGeometry -writeSets vtk
"""

SLURM_SCRIPT="""#!/bin/bash
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=8
#SBATCH --cpus-per-task=1
#SBATCH --mem=16G
#SBATCH --time=00:20:00
#SBATCH --job-name=ale98512diag
#SBATCH --output=__DEST__/slurm-%j.out
#SBATCH --error=__DEST__/slurm-%j.err
set -Eeuo pipefail
module load gnu14/14.2.0 openmpi5/5.0.7
export SINGULARITYENV_USER="$USER"
for t in 0.5635 0.563625; do
    echo "NATIVE_98512_CHECKMESH_START time=$t"
    set +e
    singularity exec --cleanenv -B /data/icto:/data/icto "__IMG__" /bin/bash "__DEST__/native-check.sh" "__DEST__" "$t" >"__DEST__/checkMesh-$t.log" 2>&1
    ret=$?
    set -e
    echo "NATIVE_98512_CHECKMESH_RESULT time=$t exit=$ret"
    grep -aiE 'Concave cells|concaveCells|concav|Mesh OK|Failed [0-9]+ mesh|non.orthogonality|skewness|face.tet|FATAL|error' "__DEST__/checkMesh-$t.log" | tail -35 || true
    if grep -aqE 'FOAM FATAL|cannot find file|No such file or directory' "__DEST__/checkMesh-$t.log"; then
        echo "NATIVE_CHECKMESH_EXECUTION_ERROR time=$t"
        exit 47
    fi
    if ! grep -aqE 'Mesh OK|Failed [0-9]+ mesh check' "__DEST__/checkMesh-$t.log"; then
        echo "NATIVE_CHECKMESH_NO_GEOMETRY_VERDICT time=$t"
        exit 48
    fi
done

echo "===== PER_MPI_RANK_NATIVE_CONCAVE_CELL_SETS ====="
for rank in 0 1 2 3 4 5 6 7; do
    for t in 0.5635 0.563625; do
        F="__DEST__/processor$rank/$t/polyMesh/sets/concaveCells"
        if [ -s "$F" ]; then
            echo "RANK=$rank TIME=$t"
            grep -aE "^[[:space:]]*[0-9]+\\(" "$F" | tail -2 || true
        fi
    done
done
echo "NATIVE_CHECKMESH_DIAG_DONE_NOT_COUPLED_FSI_SUCCESS"
"""

def submit():
    work,source,dest,img,filemap=preflight()
    if dest.exists():fail(15,"DIAGNOSTIC_DIRECTORY_ALREADY_EXISTS_NO_OVERWRITE "+str(dest))
    check=subprocess.run(["squeue","-h","-u",os.environ["USER"],"-n",
                         "ale2758fsi,ale96764repair,ale96764go,ale98512diag",
                         "-o","%i %T"],capture_output=True,text=True)
    if check.returncode!=0:fail(16,"SQUEUE_NOT_AVAILABLE_NO_ACTION: "+check.stderr.strip())
    if check.stdout.strip():fail(17,"ANOTHER_ALE_JOB_ACTIVE: "+check.stdout.strip())
    dest.mkdir(parents=True)
    (dest/"system").mkdir()
    (dest/"system/controlDict").write_text(CONTROL)
    (dest/"PREPARATION_STATE.txt").write_text("PRIVATE_MESH_COPY_STARTED\n")
    for sourcefile,rel in filemap:
        out=dest/rel
        out.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(sourcefile,out)
        if sourcefile.stat().st_size!=out.stat().st_size or digest(sourcefile)!=digest(out):
            fail(18,"PRIVATE_COPY_HASH_MISMATCH: "+str(out))
    for i in RANKS:
        (dest/f"processor{i}/system/controlDict").write_text(CONTROL)
    for name in ("fvSchemes","fvSolution"):
        shutil.copyfile(dest/f"processor0/system/{name}",dest/"system"/name)
    native=dest/"native-check.sh"
    native.write_text(NATIVE_SCRIPT)
    batch=dest/"native-first-window.sbatch"
    batch.write_text(SLURM_SCRIPT.replace("__DEST__",str(dest)).replace("__IMG__",str(img)))
    for script in (native,batch):
        p=subprocess.run(["bash","-n",str(script)],capture_output=True,text=True)
        if p.returncode:fail(19,"BASH_SYNTAX_INVALID: "+str(script)+": "+p.stderr)
    (dest/"PREPARATION_STATE.txt").write_text("PRIVATE_MESH_HASH_VERIFIED_READY_NATIVE_ONLY\n")
    r=subprocess.run(["sbatch","--parsable",str(batch)],capture_output=True,text=True)
    if r.returncode:fail(20,"SBATCH_FAILED: "+r.stderr)
    jid=r.stdout.strip().split(";")[0]
    if not re.fullmatch(r"\d+",jid):fail(21,"INVALID_JOB_ID: "+r.stdout)
    (dest/"diagnostic-job-id.txt").write_text(jid+"\n")
    print("NATIVE_98512_GEOMETRY_DIAG_SUBMITTED",jid)
    print("OUTPUT",dest/f"slurm-{jid}.out")
    print("ORIGINAL_FSI_AND_CHECKPOINTS_UNMODIFIED")

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    op=parser.add_mutually_exclusive_group(required=True)
    op.add_argument("--preflight",action="store_true")
    op.add_argument("--submit",action="store_true")
    args=parser.parse_args()
    if args.preflight:
        preflight()
        print("PRECHECK_PASS_NO_SLURM_SUBMITTED")
    else:submit()

if __name__=="__main__":
    main()
