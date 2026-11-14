#!/usr/bin/env bash
# G1-B independent 10+10 restart from 90739. No production authorization.
set -euo pipefail
BASE="$HOME/hpcc-fsi"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
PROPOSAL="$BASE/g1-phase-b-stage-20261114-151247"
SCRIPT="$BASE/g1-b-real-restart.py"
mkdir -p "$BASE/logs"
test -s "$SIF"
test -s "$PROPOSAL/G1_PHASE_B_PROPOSAL.json"
test -s "$SCRIPT"
python3 -m py_compile "$SCRIPT"
python3 "$SCRIPT" --self-test
python3 "$SCRIPT" --base "$BASE" --proposal "$PROPOSAL" --preflight-only
if ! ACTIVE="$(squeue -h -u "$USER" -n fsi-g1-b10 -o '%i %T')"; then
  echo "STOP: Slurm queue unavailable" >&2
  exit 42
fi
if [[ -n "$ACTIVE" ]]; then
  echo "STOP: duplicate G1-B job: $ACTIVE" >&2
  exit 43
fi
SHA="$(sha256sum "$SCRIPT" | awk '{print $1}')"
SNAPSHOT="$BASE/g1-b-real-restart-$(printf %.16s "$SHA").py"
if [[ -e "$SNAPSHOT" ]]; then
  cmp -s "$SCRIPT" "$SNAPSHOT" || { echo "STOP: immutable script collision"; exit 44; }
else
  cp "$SCRIPT" "$SNAPSHOT"
  chmod a-w "$SNAPSHOT"
fi
BATCH="$(mktemp "$BASE/g1-b10.XXXXXXXX.sbatch")"
cat > "$BATCH" <<'SBATCH'
#!/usr/bin/env bash
set -euo pipefail
BASE="$HOME/hpcc-fsi"
ROOT="$BASE/seagrass-implicit-20261111"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
PROPOSAL="$BASE/g1-phase-b-stage-20261114-151247"
WORK="$BASE/g1-b10-job-$SLURM_JOB_ID"
test ! -e "$WORK"
test "$(sha256sum "$G1_B_SCRIPT" | awk '{print $1}')" = "$G1_B_SHA"
echo "BEGIN_G1_B_REAL_RESTART job=$SLURM_JOB_ID host=$(hostname) time=$(date -Is)"
singularity exec --cleanenv "$SIF" bash -c '
set +eu
export WM_MPLIB=SYSTEMOPENMPI
source /usr/lib/openfoam/openfoam2512/etc/bashrc
export PATH="/opt/precice-3.4.1-ompi5/bin:/opt/openmpi-5.0.7/bin:$PATH"
export LD_LIBRARY_PATH="/opt/scotch-compat/lib:/opt/precice-3.4.1-ompi5/lib:/opt/precice-3.4.1-ompi5/lib64:/opt/openmpi-5.0.7/lib:/opt/openmpi-5.0.7/lib64:${LD_LIBRARY_PATH:-}"
export PKG_CONFIG_PATH="/opt/precice-3.4.1-ompi5/lib/pkgconfig:/opt/precice-3.4.1-ompi5/lib64/pkgconfig:${PKG_CONFIG_PATH:-}"
export PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
ROOT="$HOME/hpcc-fsi/seagrass-implicit-20261111"
export LD_LIBRARY_PATH="$ROOT/scripts/native/lib:$ROOT/fsi-explicit-test/mesh-guard/lib:$LD_LIBRARY_PATH"
set -euo pipefail
test "$WM_PROJECT_VERSION" = "v2512"
test "$(command -v mpirun)" = "/opt/openmpi-5.0.7/bin/mpirun"
test -x /usr/bin/time
test -x "$ROOT/scripts/native/bin/ccx_preCICE_persistent_v2"
python3 "$1" --base "$HOME/hpcc-fsi" --proposal "$2" --work "$3" --run --max-seconds 10800
' bash "$G1_B_SCRIPT" "$PROPOSAL" "$WORK"
echo "G1_B_SLURM_EXIT=0"
SBATCH
JOB="$(sbatch --parsable -p cpu -N 1 -n 1 -c 12 --mem=24G -t 04:00:00 \
  --export="ALL,G1_B_SCRIPT=$SNAPSHOT,G1_B_SHA=$SHA" \
  -J fsi-g1-b10 -o "$BASE/logs/fsi-g1-b10-%j.out" \
  -e "$BASE/logs/fsi-g1-b10-%j.err" "$BATCH")"
echo "SUBMITTED_G1_B_REAL_RESTART_JOB_ID=$JOB"
echo "RUN_DIR=$BASE/g1-b10-job-$JOB"
echo "STDOUT=$BASE/logs/fsi-g1-b10-$JOB.out"
echo "STDERR=$BASE/logs/fsi-g1-b10-$JOB.err"
