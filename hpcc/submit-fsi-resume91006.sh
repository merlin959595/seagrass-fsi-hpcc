#!/usr/bin/env bash
# Recover completed 91006 without rerunning its 240 windows. First schedule
# independent terminal checkMesh certificate, then Slurm afterok 3-day segments.
set -euo pipefail
BASE="$HOME/hpcc-fsi"
QUAL="$BASE/qualify-91006-resume.py"
DIAG="$BASE/diagnose-91006-meshco-and-checkpoints.py"
CHAIN="$BASE/run-fsi-long-chain-segment.py"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
COUNT=6
if (( $# > 0 )); then COUNT="$1"; fi
if [[ ! "$COUNT" =~ ^[1-6]$ ]]; then
    echo "Usage: bash submit-fsi-resume91006.sh [1..6]" >&2; exit 2
fi
mkdir -p "$BASE/logs"
for file in "$QUAL" "$DIAG" "$CHAIN" "$SIF"; do
    test -s "$file" || { echo "Missing $file" >&2; exit 3; }
done
test ! -e "$BASE/FSI_91006_RESUME_CERT.json" || {
    echo "STOP: resume certificate already exists; avoid duplicate chain" >&2; exit 4; }
python3 -m py_compile "$QUAL" "$DIAG" "$CHAIN"
python3 "$QUAL" --self-test
python3 "$CHAIN" --self-test
python3 "$QUAL" --base "$BASE" --preflight
ACTIVE="$(squeue -h -u "$USER" -o '%i %j %T')" || exit 42
if grep -Eq ' (fsi-91006-qual|fsi-real-long) ' <<< "$ACTIVE"; then
    echo "STOP: an FSI qualification/long job is already queued" >&2
    echo "$ACTIVE"
    exit 43
fi
QSHA="$(sha256sum "$QUAL" | awk '{print $1}')"
CSHA="$(sha256sum "$CHAIN" | awk '{print $1}')"
QPIN="$BASE/qualify-91006-$(printf %.16s "$QSHA").py"
CPIN="$BASE/resume-long-$(printf %.16s "$CSHA").py"
for pair in "$QUAL:$QPIN" "$CHAIN:$CPIN"; do
    source_path="$(echo "$pair" | cut -d: -f1)"
    dest_path="$(echo "$pair" | cut -d: -f2)"
    if [[ -e "$dest_path" ]]; then
        cmp -s "$source_path" "$dest_path" || exit 44
    else
        cp "$source_path" "$dest_path"
        chmod a-w "$dest_path"
    fi
done
QBATCH="$(mktemp "$BASE/qualify91006.XXXXXXXX.sbatch")"
cat > "$QBATCH" <<'SBATCH'
#!/usr/bin/env bash
set -euo pipefail
BASE="$HOME/hpcc-fsi"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
OUT="$BASE/fsi-91006-qualify-job$SLURM_JOB_ID"
test ! -e "$OUT"
test "$(sha256sum "$QUAL_SOURCE" | awk '{print $1}')" = "$QUAL_SHA"
singularity exec --cleanenv "$SIF" bash -c '
set +eu
export WM_MPLIB=SYSTEMOPENMPI
source /usr/lib/openfoam/openfoam2512/etc/bashrc
export PATH="/opt/openmpi-5.0.7/bin:/opt/precice-3.4.1-ompi5/bin:$PATH"
export LD_LIBRARY_PATH="/opt/scotch-compat/lib:/opt/openmpi-5.0.7/lib:/opt/openmpi-5.0.7/lib64:/opt/precice-3.4.1-ompi5/lib:/opt/precice-3.4.1-ompi5/lib64:${LD_LIBRARY_PATH:-}"
set -euo pipefail
test "$WM_PROJECT_VERSION" = "v2512"
test "$(command -v mpirun)" = "/opt/openmpi-5.0.7/bin/mpirun"
export SLURM_JOB_ID="$3"
python3 "$1" --base "$HOME/hpcc-fsi" --run --work "$2"
' bash "$QUAL_SOURCE" "$OUT" "$SLURM_JOB_ID"
echo "FSI_91006_QUALIFIER_JOB_EXIT=0"
SBATCH
LBATCH="$(mktemp "$BASE/resume91006.XXXXXXXX.sbatch")"
cat > "$LBATCH" <<'SBATCH'
#!/usr/bin/env bash
set -euo pipefail
BASE="$HOME/hpcc-fsi"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
WORK="$BASE/fsi-long-stage$CHAIN_STAGE-job$SLURM_JOB_ID"
test ! -e "$WORK"
test "$(sha256sum "$CHAIN_SOURCE" | awk '{print $1}')" = "$CHAIN_SHA"
echo "FSI_REAL_RESUME_START job=$SLURM_JOB_ID stage=$CHAIN_STAGE parent=$CHAIN_PARENT"
singularity exec --cleanenv "$SIF" bash -c '
set +eu
export WM_MPLIB=SYSTEMOPENMPI
source /usr/lib/openfoam/openfoam2512/etc/bashrc
export PATH="/opt/precice-3.4.1-ompi5/bin:/opt/openmpi-5.0.7/bin:$PATH"
export LD_LIBRARY_PATH="/opt/scotch-compat/lib:/opt/precice-3.4.1-ompi5/lib:/opt/precice-3.4.1-ompi5/lib64:/opt/openmpi-5.0.7/lib:/opt/openmpi-5.0.7/lib64:__LIBPATH__"
export PKG_CONFIG_PATH="/opt/precice-3.4.1-ompi5/lib/pkgconfig:/opt/precice-3.4.1-ompi5/lib64/pkgconfig:${PKG_CONFIG_PATH:-}"
export PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
export OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
ROOT="$HOME/hpcc-fsi/seagrass-implicit-20261111"
export LD_LIBRARY_PATH="$ROOT/scripts/native/lib:$ROOT/fsi-explicit-test/mesh-guard/lib:$LD_LIBRARY_PATH"
set -euo pipefail
test "$WM_PROJECT_VERSION" = "v2512"
test "$(command -v mpirun)" = "/opt/openmpi-5.0.7/bin/mpirun"
test -x "$ROOT/scripts/native/bin/ccx_preCICE_persistent_v2"
export SLURM_JOB_ID="$6"
python3 "$1" --base "$HOME/hpcc-fsi" --stage "$2" \
  --previous-job "$3" --max-windows "$4" --work "$5" \
  --run --timeout-seconds 237600
' bash "$CHAIN_SOURCE" "$CHAIN_STAGE" "$CHAIN_PARENT" "$CHAIN_MAX_WINDOWS" "$WORK" "$SLURM_JOB_ID"
echo "FSI_REAL_RESUME_JOB_EXIT=0"
SBATCH
QUAL_JOB="$(sbatch --parsable -p cpu -N 1 -n 1 -c 8 --mem=16G -t 00:45:00 \
   --export="ALL,QUAL_SOURCE=$QPIN,QUAL_SHA=$QSHA" \
   -J fsi-91006-qual -o "$BASE/logs/qualify91006-%j.out" \
   -e "$BASE/logs/qualify91006-%j.err" "$QBATCH")"
echo "QUALIFIER_JOB=$QUAL_JOB"
manifest="$BASE/fsi-91006-resume-submission-$(date +%Y%m%d-%H%M%S).txt"
echo "QUALIFIER_JOB=$QUAL_JOB" > "$manifest"
dependency="$QUAL_JOB"
parent=91006
for ((stage=1; stage<=COUNT; stage++)); do
    args=(--parsable -p cpu -N 1 -n 1 -c 12 --mem=24G -t 3-00:00:00
      --dependency="afterok:$dependency" --kill-on-invalid-dep=yes
      -J fsi-real-long
      -o "$BASE/logs/fsi-long-resume-%j.out"
      -e "$BASE/logs/fsi-long-resume-%j.err"
      --export="ALL,CHAIN_SOURCE=$CPIN,CHAIN_SHA=$CSHA,CHAIN_STAGE=$stage,CHAIN_PARENT=$parent,CHAIN_MAX_WINDOWS=960")
    if ! job="$(sbatch "${args[@]}" "$LBATCH")"; then
        echo "Partial submission: stage $stage failed, see $manifest" >&2
        exit 51
    fi
    echo "STAGE=$stage JOB=$job PARENT=$parent" | tee -a "$manifest"
    dependency="$job"
    parent="$job"
done
echo "AUTO_3DAY_FSI_RESUME_CHAIN_SUBMITTED=$COUNT"
echo "MANIFEST=$manifest"
echo "CERT=$BASE/FSI_91006_RESUME_CERT.json"
echo "NOTE: no follower starts if terminal mesh certification or earlier segment fails"
