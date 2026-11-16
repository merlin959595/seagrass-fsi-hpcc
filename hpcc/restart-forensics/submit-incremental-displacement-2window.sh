#!/usr/bin/env bash
# Explicit opt-in only: one 2-window validation. Never auto-start production.
set -euo pipefail
BASE="$HOME/hpcc-fsi"
# Explicit isolated source paths can be pinned outside any existing
# source directory; never replace scripts while another job is using them.
SRC="${FSI_DELTA_SOURCE:-$BASE/crossjob-fix-20261116/try-incremental-displacement-restart.py}"
CORE="${FSI_DELTA_CORE:-$BASE/crossjob-fix-20261116/segment.py}"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
ROOT="$BASE/crossjob-fix-20261116/delta-2window"
for f in "$SRC" "$CORE" "$SIF";do
  test -s "$f" || { echo "MISSING_REQUIRED_FILE: $f" >&2; exit 2; }
done
test -s "$BASE/FSI_91006_RESUME_CERT.json"
python3 -m py_compile "$SRC" "$CORE"
python3 "$SRC" --self-test
python3 "$SRC" --base "$BASE" --core "$CORE" --preflight
RUNNING="$(squeue -h -u "$USER" -n fsi-delta2 -o '%j:%T')" || exit 4
if [[ -n "$RUNNING" ]];then
  echo "Already running/queued isolated delta test: $RUNNING" >&2
  exit 5
fi
mkdir -p "$ROOT"
H_SRC="$(sha256sum "$SRC" | awk '{print $1}')"
H_CORE="$(sha256sum "$CORE" | awk '{print $1}')"
PIN_SRC="$ROOT/candidate-$(printf %.16s "$H_SRC").py"
PIN_CORE="$ROOT/core-$(printf %.16s "$H_CORE").py"
if [[ -e "$PIN_SRC" ]];then
  cmp -s "$SRC" "$PIN_SRC" || exit 7
else
  cp "$SRC" "$PIN_SRC"
  chmod a-w "$PIN_SRC"
fi
if [[ -e "$PIN_CORE" ]];then
  cmp -s "$CORE" "$PIN_CORE" || exit 8
else
  cp "$CORE" "$PIN_CORE"
  chmod a-w "$PIN_CORE"
fi
BATCH="$ROOT/delta2-$(printf %.12s "$H_SRC").sbatch"
test ! -e "$BATCH" || {
  echo "Submission script already used; refusing duplicate test" >&2
  exit 9
}
cat > "$BATCH" <<'SBATCH'
#!/usr/bin/env bash
set -euo pipefail
BASE="$HOME/hpcc-fsi"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
WORK="$BASE/crossjob-fix-20261116/delta-2window/trial-$SLURM_JOB_ID"
test ! -e "$WORK"
test "$(sha256sum "$FSI_DELTA_SCRIPT" | awk '{print $1}')" = "$FSI_DELTA_SCRIPT_SHA"
test "$(sha256sum "$FSI_DELTA_CORE" | awk '{print $1}')" = "$FSI_DELTA_CORE_SHA"
echo "INCREMENTAL_DISPLACEMENT_TWO_WINDOW_START $(date -Is)"
env -u BASH_ENV -u ENV singularity exec --cleanenv "$SIF" \
  /usr/bin/env -u BASH_ENV -u ENV /bin/bash --noprofile --norc -c '
TEST_SCRIPT="$1"
TEST_CORE="$2"
TEST_WORK="$3"
TEST_JOB="$4"
set --
set +eu
export WM_MPLIB=SYSTEMOPENMPI
source /usr/lib/openfoam/openfoam2512/etc/bashrc
export PATH="/opt/precice-3.4.1-ompi5/bin:/opt/openmpi-5.0.7/bin:$PATH"
export LD_LIBRARY_PATH="/opt/scotch-compat/lib:/opt/precice-3.4.1-ompi5/lib:/opt/precice-3.4.1-ompi5/lib64:/opt/openmpi-5.0.7/lib:/opt/openmpi-5.0.7/lib64:${LD_LIBRARY_PATH:-}"
export PKG_CONFIG_PATH="/opt/precice-3.4.1-ompi5/lib/pkgconfig:/opt/precice-3.4.1-ompi5/lib64/pkgconfig:${PKG_CONFIG_PATH:-}"
export OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ROOT="$HOME/hpcc-fsi/seagrass-implicit-20261111"
export LD_LIBRARY_PATH="$ROOT/scripts/native/lib:$ROOT/fsi-explicit-test/mesh-guard/lib:$LD_LIBRARY_PATH"
set -euo pipefail
test "$WM_PROJECT_VERSION" = "v2512"
test "$(command -v mpirun)" = "/opt/openmpi-5.0.7/bin/mpirun"
test -x "$ROOT/scripts/native/bin/ccx_preCICE_persistent_v2"
test -f "$ROOT/scripts/native/lib/libseagrassReferenceRestart.so"
export SLURM_JOB_ID="$TEST_JOB"
python3 "$TEST_SCRIPT" --base "$HOME/hpcc-fsi" \
  --core "$TEST_CORE" --work "$TEST_WORK" --run
' bash "$FSI_DELTA_SCRIPT" "$FSI_DELTA_CORE" \
  "$WORK" "$SLURM_JOB_ID"
echo "INCREMENTAL_DISPLACEMENT_TWO_WINDOW_WORKFLOW_EXIT_ZERO"
SBATCH
bash -n "$BATCH"
EXCLUDE=()
ACTIVE_LIVE="$(squeue -h -j 91543 -o '%T %N')" || exit 11
if [[ "$ACTIVE_LIVE" == RUNNING\ * ]];then
  NODE="${ACTIVE_LIVE#RUNNING }"
  if [[ -z "$NODE" || "$NODE" == "(null)" || "$NODE" == "None" ]];then
    echo "Could not safely identify live 91543 compute node" >&2
    exit 12
  fi
  EXCLUDE=(--exclude="$NODE")
fi
JOB="$(sbatch --parsable --partition=cpu --nodes=1 --ntasks=1 \
  --cpus-per-task=12 --mem=24G --time=01:00:00 \
  "${EXCLUDE[@]}" --job-name=fsi-delta2 \
  --export="ALL,BASH_ENV=,ENV=,FSI_DELTA_SCRIPT=$PIN_SRC,FSI_DELTA_SCRIPT_SHA=$H_SRC,FSI_DELTA_CORE=$PIN_CORE,FSI_DELTA_CORE_SHA=$H_CORE" \
  --output="$ROOT/slurm-%j.out" --error="$ROOT/slurm-%j.err" "$BATCH")"
echo "SUBMITTED_ISOLATED_TWO_WINDOW_INCREMENTAL_DISPLACEMENT_JOB=$JOB"
echo "REPORT=$ROOT/trial-$JOB/INCREMENTAL_DISPLACEMENT_RESULT.json"
echo "NO_AUTOMATIC_3DAY_CHAIN"
