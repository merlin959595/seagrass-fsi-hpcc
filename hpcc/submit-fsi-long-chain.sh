#!/usr/bin/env bash
# Queue 3D true FSI production now: stage 0 + up to seven afterok successors.
# Each job has at most 3 days of wall time; no failed stage may trigger a successor.
set -euo pipefail
BASE="$HOME/hpcc-fsi"
SRC="$BASE/run-fsi-long-chain-segment.py"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
COUNT=6
if (( $# > 0 )); then COUNT="$1"; fi
if [[ ! "$COUNT" =~ ^[1-8]$ ]]; then
  echo "Usage: bash submit-fsi-long-chain.sh [1..8]" >&2
  exit 2
fi
test -s "$SRC"
test -s "$SIF"
mkdir -p "$BASE/logs"
python3 -m py_compile "$SRC"
python3 "$SRC" --self-test
python3 "$SRC" --base "$BASE" --stage 0 --max-windows 240 --preflight-only
if ! RUNNING="$(squeue -h -u "$USER" -n fsi-real-long -o '%i %T')"; then
  echo "STOP: cannot inspect Slurm queue" >&2
  exit 41
fi
if [[ -n "$RUNNING" ]]; then
  echo "STOP: duplicate FSI production chain: $RUNNING" >&2
  exit 42
fi
HASH="$(sha256sum "$SRC" | awk '{print $1}')"
PIN="$BASE/run-fsi-long-chain-segment-$(printf %.16s "$HASH").py"
if [[ -e "$PIN" ]]; then
  cmp -s "$SRC" "$PIN" || { echo "STOP: source mismatch"; exit 43; }
else
  cp "$SRC" "$PIN"
  chmod a-w "$PIN"
fi
BATCH="$(mktemp "$BASE/fsi-long-chain.XXXXXXXX.sbatch")"
cat > "$BATCH" <<'SBATCH'
#!/usr/bin/env bash
set -euo pipefail
BASE="$HOME/hpcc-fsi"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
RUN="$BASE/fsi-long-stage$CHAIN_STAGE-job$SLURM_JOB_ID"
test ! -e "$RUN"
test "$(sha256sum "$CHAIN_SOURCE" | awk '{print $1}')" = "$CHAIN_SOURCE_SHA"
echo "FSI_LONG_START job=$SLURM_JOB_ID stage=$CHAIN_STAGE parent=$CHAIN_PARENT host=$(hostname) time=$(date -Is)"
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
export SLURM_JOB_ID="$6"
python3 "$1" --base "$HOME/hpcc-fsi" --stage "$2" --previous-job "$3" \
  --max-windows "$4" --work "$5" --run --timeout-seconds 237600
' bash "$CHAIN_SOURCE" "$CHAIN_STAGE" "$CHAIN_PARENT" "$CHAIN_MAX_WINDOWS" "$RUN" "$SLURM_JOB_ID"
echo "FSI_LONG_SLURM_EXIT=0 stage=$CHAIN_STAGE"
SBATCH
manifest="$BASE/fsi-long-chain-submission-$(date +%Y%m%d-%H%M%S).txt"
: > "$manifest"
previous=""
for (( i=0; i<COUNT; i++ )); do
  maxwin=960
  if (( i==0 )); then maxwin=240; fi
  args=(--parsable -p cpu -N 1 -n 1 -c 12 --mem=24G -t 3-00:00:00
        -J fsi-real-long
        -o "$BASE/logs/fsi-long-%j.out"
        -e "$BASE/logs/fsi-long-%j.err")
  if [[ -n "$previous" ]]; then
    args+=(--dependency="afterok:$previous" --kill-on-invalid-dep=yes)
  fi
  parent=90873
  if [[ -n "$previous" ]]; then parent="$previous"; fi
  args+=(--export="ALL,CHAIN_SOURCE=$PIN,CHAIN_SOURCE_SHA=$HASH,CHAIN_STAGE=$i,CHAIN_PARENT=$parent,CHAIN_MAX_WINDOWS=$maxwin")
  if ! job="$(sbatch "${args[@]}" "$BATCH")"; then
    echo "STOP: submit failed at stage $i; prior jobs remain queued; see $manifest" >&2
    exit 55
  fi
  echo "STAGE=$i JOB=$job PREVIOUS_JOB=$parent MAX_WINDOWS=$maxwin" | tee -a "$manifest"
  previous="$job"
done
echo "AUTO_DEPENDENCY_CHAIN_SUBMITTED=$COUNT"
echo "MANIFEST=$manifest"
echo "MONITOR_COMMAND=squeue -u $USER -n fsi-real-long"
echo "NOTICE=Each successor starts only after prior stage succeeds."
