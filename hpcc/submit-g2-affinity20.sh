#!/usr/bin/env bash
# G2 independent 20-window CPU-affinity candidate, NOT production.
# Does not touch the queued long-chain 91006-91011; uses a separate Slurm job.
set -euo pipefail
BASE="$HOME/hpcc-fsi"
SOURCE="$BASE/g2-affinity-20-candidate.py"
BENCH="$BASE/benchmark-short-fsi.py"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
mkdir -p "$BASE/logs"
test -s "$SOURCE"
test -s "$BENCH"
test -s "$SIF"
python3 -m py_compile "$SOURCE"
python3 "$SOURCE" --self-test
if ! ACTIVE="$(squeue -h -u "$USER" -n fsi-g2-affinity -o '%i %T')"; then
  echo "STOP: Cannot query Slurm queue" >&2
  exit 42
fi
if [[ -n "$ACTIVE" ]]; then
  echo "STOP: existing G2 affinity trial $ACTIVE" >&2
  exit 43
fi
HASH="$(sha256sum "$SOURCE" | awk '{print $1}')"
PIN="$BASE/g2-affinity20-$(printf %.16s "$HASH").py"
if [[ -e "$PIN" ]]; then
  cmp -s "$PIN" "$SOURCE" || { echo "STOP: frozen code mismatch" >&2; exit 44; }
else
  cp "$SOURCE" "$PIN"
  chmod a-w "$PIN"
fi
BATCH="$(mktemp "$BASE/g2-affinity.XXXXXXXX.sbatch")"
cat > "$BATCH" <<'SBATCH'
#!/usr/bin/env bash
set -euo pipefail
BASE="$HOME/hpcc-fsi"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
WORK="$BASE/g2-affinity20-job-$SLURM_JOB_ID"
test ! -e "$WORK"
test "$(sha256sum "$G2_AFFINITY_SOURCE" | awk '{print $1}')" = "$G2_AFFINITY_SHA"
echo "G2_AFFINITY_START job=$SLURM_JOB_ID host=$(hostname) time=$(date -Is)"
singularity exec --cleanenv "$SIF" bash -c '
set +eu
export WM_MPLIB=SYSTEMOPENMPI
source /usr/lib/openfoam/openfoam2512/etc/bashrc
export PATH="/opt/precice-3.4.1-ompi5/bin:/opt/openmpi-5.0.7/bin:$PATH"
export LD_LIBRARY_PATH="/opt/scotch-compat/lib:/opt/precice-3.4.1-ompi5/lib:/opt/precice-3.4.1-ompi5/lib64:/opt/openmpi-5.0.7/lib:/opt/openmpi-5.0.7/lib64:${LD_LIBRARY_PATH:-}"
export PKG_CONFIG_PATH="/opt/precice-3.4.1-ompi5/lib/pkgconfig:/opt/precice-3.4.1-ompi5/lib64/pkgconfig:${PKG_CONFIG_PATH:-}"
export PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
export OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
ROOT="$HOME/hpcc-fsi/seagrass-implicit-20261111"
export LD_LIBRARY_PATH="$ROOT/scripts/native/lib:$ROOT/fsi-explicit-test/mesh-guard/lib:$LD_LIBRARY_PATH"
set -euo pipefail
test "$WM_PROJECT_VERSION" = "v2512"
test "$(command -v mpirun)" = "/opt/openmpi-5.0.7/bin/mpirun"
test -x "$ROOT/scripts/native/bin/ccx_preCICE_persistent_v2"
export SLURM_JOB_ID="$3"
python3 "$1" --base "$HOME/hpcc-fsi" --work "$2"
' bash "$G2_AFFINITY_SOURCE" "$WORK" "$SLURM_JOB_ID"
echo "G2_AFFINITY_SLURM_EXIT=0"
SBATCH
JOB="$(sbatch --parsable -p cpu -N 1 -n 1 -c 12 --mem=24G -t 04:00:00 \
  -J fsi-g2-affinity \
  --export="ALL,G2_AFFINITY_SOURCE=$PIN,G2_AFFINITY_SHA=$HASH" \
  -o "$BASE/logs/fsi-g2-affinity-%j.out" \
  -e "$BASE/logs/fsi-g2-affinity-%j.err" \
  "$BATCH")"
echo "G2_AFFINITY_JOB_SUBMITTED=$JOB"
echo "G2_AFFINITY_RESULT=$BASE/g2-affinity20-job-$JOB/G2_AFFINITY_RESULT.json"
echo "G2_LOG=$BASE/logs/fsi-g2-affinity-$JOB.out"
