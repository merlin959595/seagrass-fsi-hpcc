#!/usr/bin/env bash
# Isolated native OpenFOAM v2512 geometry diagnosis of failed C2 snapshots.
# Only copies mesh input (2 times, 8 MPI partitions) to a new private case.
# checkMesh writes sets ONLY into the copy, never source production data.
set -Eeuo pipefail
ROOT="/data/icto/${USER:?}/seagrass-fsi558-runs.sNIpi9"
SRC="$ROOT/trial-97576-repair96764-c2-stage1/runs/hpcc-implicit-002/fluid"
DST="$ROOT/diagnostics/native-concavity-97576-c2"
IMG="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
if [[ ! -d "$SRC" || ! -s "$IMG" ]];then
    echo "SOURCE_OR_NATIVE_CONTAINER_MISSING" >&2; exit 10
fi
if squeue -h -u "$USER" -n ale96764repair,ale96764go | grep -q .;then
    echo "FSI_REPAIR_OR_PRODUCTION_STILL_ACTIVE; DO_NOT_ADD_DIAGNOSTIC_IO" >&2; exit 11
fi
if [[ -e "$DST" ]];then
    echo "DIAGNOSTIC_ALREADY_EXISTS_NO_OVERWRITE $DST" >&2; exit 12
fi
mkdir -p "$(dirname "$DST")"
mkdir "$DST"
mkdir "$DST/system"
cat >"$DST/system/controlDict" <<'FOAM'
FoamFile
{
    version 2.0;
    format ascii;
    class dictionary;
    object controlDict;
}
application checkMesh;
startFrom startTime;
startTime 0.5805;
stopAt endTime;
endTime 0.58075;
deltaT 0.000125;
writeControl timeStep;
writeInterval 1;
FOAM
printf '%s\n' 'PRIVATE_NATIVE_CONCAVITY_COPY_IN_PROGRESS' > "$DST/PREPARATION_STATE.txt"
for i in {0..7};do
    base="$SRC/processor$i"
    poly="$DST/processor$i/constant/polyMesh"
    mkdir -p "$poly"
    for f in faces owner neighbour boundary points;do
        input="$base/constant/polyMesh/$f"
        [[ -f "$input" ]] || { echo "MISSING_POLYMESH_FILE $input" >&2; exit 13; }
        cp -L -- "$input" "$poly/$f"
    done
    for t in 0.5805 0.58075;do
        input="$base/$t/polyMesh/points"
        [[ -f "$input" ]] || { echo "NO_SAVED_POINTS $input" >&2; exit 14; }
        mkdir -p "$DST/processor$i/$t/polyMesh"
        cp -L -- "$input" "$DST/processor$i/$t/polyMesh/points"
    done
done
BATCH="$DST/checkNativeConcavity.sbatch"
cat > "$BATCH" <<EOF
#!/bin/bash
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=8
#SBATCH --cpus-per-task=1
#SBATCH --mem=16G
#SBATCH --time=00:30:00
#SBATCH --job-name=ale96764diag
#SBATCH --output=$DST/slurm-%j.out
#SBATCH --error=$DST/slurm-%j.err
set -Eeuo pipefail
module load gnu14/14.2.0 openmpi5/5.0.7
export SINGULARITYENV_USER="\$USER"
for t in 0.5805 0.58075;do
    echo "START_NATIVE_GEOMETRY_DIAG time=\$t"
    set +e
    singularity exec --cleanenv -B /data/icto:/data/icto "$IMG" /bin/bash "$DST/native-check.sh" "$DST" "\$t" >"$DST/checkMesh-\$t.log" 2>&1
    code=\$?
    set -e
    echo "NATIVE_CHECKMESH_EXIT time=\$t code=\$code"
    grep -Eia 'Concave cells|concaveCells|concav|Mesh OK|Failed|error|non.?orth' "$DST/checkMesh-\$t.log" | tail -25 || true
done
echo "NATIVE_CONCAVITY_DIAGNOSTIC_FILES"
find "$DST" \( -iname '*concave*' -o -name 'checkMesh-*.log' \) -print | head -100
echo "NATIVE_DIAGNOSTIC_COMPLETE_NOT_FSI_PASS"
EOF
cat >"$DST/native-check.sh" <<'SH'
#!/bin/bash
set -Eeuo pipefail
caseDir="$1"
t="$2"
export WM_MPLIB=SYSTEMOPENMPI
unset BASH_ENV ENV
set +eu
source /usr/lib/openfoam/openfoam2512/etc/bashrc
rc=$?
set -eu
[[ "$rc" -eq 0 ]] || exit 50
export PATH="/opt/openmpi-5.0.7/bin:/opt/precice-3.4.1-ompi5/bin:$PATH"
export LD_LIBRARY_PATH="/opt/openmpi-5.0.7/lib:/opt/openmpi-5.0.7/lib64:/opt/scotch-compat/lib:${LD_LIBRARY_PATH:-}"
[[ "$WM_PROJECT_VERSION" == v2512 ]] || { echo "WRONG_FOAM_VERSION" >&2; exit 51; }
command -v checkMesh || exit 52
cd "$caseDir"
exec mpirun --oversubscribe -np 8 checkMesh -parallel -time "$t" -allGeometry -writeSets vtk
SH
bash -n "$DST/native-check.sh"
bash -n "$BATCH"
printf '%s\n' 'PRIVATE_NATIVE_CONCAVITY_COPY_PASS; SLURM_PENDING_SUBMISSION' >"$DST/PREPARATION_STATE.txt"
jid="$(sbatch --parsable "$BATCH")"
jid="${jid%%;*}"
[[ "$jid" =~ ^[0-9]+$ ]] || { echo "SLURM_RETURNED_BAD_JOB_ID: $jid" >&2; exit 15; }
printf '%s\n' "$jid" >"$DST/diagnostic-job-id.txt"
echo "NATIVE_CONCAVITY_DIAG_SUBMITTED $jid"
echo "CHECK_LOG $DST/slurm-$jid.out"
echo "SOURCE_AND_BACKUPS_UNMODIFIED"
