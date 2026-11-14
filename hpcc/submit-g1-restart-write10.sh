#!/usr/bin/env bash
# G1 phase A only. Creates a NEW 10-window double-coupled FSI job.
# Its success means only that a nonempty CCX restart file was written.
set -euo pipefail
BASE="$HOME/hpcc-fsi"
ROOT="$BASE/seagrass-implicit-20261111"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
SCRIPT="$BASE/benchmark-short-fsi.py"
mkdir -p "$BASE/logs"
test -s "$ROOT/fsi-implicit-production/run_production.py"
test -s "$BASE/performance-full160-job-89038/OPTIMIZED_160_SUMMARY.json"
test -s "$SCRIPT"
test -s "$SIF"
python3 -m py_compile "$SCRIPT"
python3 "$SCRIPT" --inspect-only --windows 10 --threads 4 --iqn-reuse 5 --g1-restart-write-step1
if ! ACTIVE="$(squeue -h -u "$USER" -n fsi-g1-rout10 -o '%i %T' 2>&1)"; then
  echo "STOP: cannot inspect Slurm jobs" >&2; exit 42
fi
if [[ -n "$ACTIVE" ]]; then
  echo "STOP: duplicate G1 job $ACTIVE" >&2; exit 43
fi
if [[ -f "$SIF.sha256" ]]; then sha256sum -c "$SIF.sha256"; fi
SHA="$(sha256sum "$SCRIPT" | awk '{print $1}')"
FROZEN="$BASE/benchmark-g1-rout10-$(printf %.16s "$SHA").py"
if [[ -e "$FROZEN" ]]; then
  cmp -s "$SCRIPT" "$FROZEN" || { echo "STOP: source snapshot mismatch"; exit 44; }
else
  cp "$SCRIPT" "$FROZEN"; chmod a-w "$FROZEN"
fi
BATCH="$(mktemp "$BASE/g1-rout10.XXXXXXXX.sbatch")"
cat > "$BATCH" <<'SBATCH'
#!/usr/bin/env bash
set -euo pipefail
BASE="$HOME/hpcc-fsi"
ROOT="$BASE/seagrass-implicit-20261111"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
WORK="$BASE/g1-rout10-job-${SLURM_JOB_ID:?}"
SCRIPT="${G1_SCRIPT:?}"
EXPECTED="${G1_SHA:?}"
test ! -e "$WORK" || { echo "STOP: G1 work already exists"; exit 21; }
mkdir "$WORK"
test "$(sha256sum "$SCRIPT" | awk '{print $1}')" = "$EXPECTED"
printf '%s\n' "$EXPECTED" > "$WORK/SOURCE_SHA256.txt"
echo "G1_RESTART_WRITE_START job=$SLURM_JOB_ID host=$(hostname) time=$(date -Is)"
singularity exec --cleanenv "$SIF" bash -c '
set +eu
export WM_MPLIB=SYSTEMOPENMPI
source /usr/lib/openfoam/openfoam2512/etc/bashrc
export PATH="/opt/precice-3.4.1-ompi5/bin:/opt/openmpi-5.0.7/bin:$PATH"
export LD_LIBRARY_PATH="/opt/scotch-compat/lib:/opt/precice-3.4.1-ompi5/lib:/opt/precice-3.4.1-ompi5/lib64:/opt/openmpi-5.0.7/lib:/opt/openmpi-5.0.7/lib64:${LD_LIBRARY_PATH:-}"
export PKG_CONFIG_PATH="/opt/precice-3.4.1-ompi5/lib/pkgconfig:/opt/precice-3.4.1-ompi5/lib64/pkgconfig:${PKG_CONFIG_PATH:-}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OMP_NUM_THREADS=1
ROOT="$HOME/hpcc-fsi/seagrass-implicit-20261111"
export LD_LIBRARY_PATH="$ROOT/scripts/native/lib:$ROOT/fsi-explicit-test/mesh-guard/lib:$LD_LIBRARY_PATH"
set -euo pipefail
test "$WM_PROJECT_VERSION" = "v2512"
test "$(command -v mpirun)" = "/opt/openmpi-5.0.7/bin/mpirun"
test -x /usr/bin/time
test -x "$ROOT/scripts/native/bin/ccx_preCICE_persistent_v2"
WORK="$1"; SCRIPT="$2"
python3 "$SCRIPT" --work "$WORK/candidate-10" --threads 4 --windows 10 \
  --iqn-reuse 5 --g1-restart-write-step1
python3 - "$WORK" << "PY"
import json,sys
from pathlib import Path
w=Path(sys.argv[1])
e=json.loads((w/"candidate-10/G1_RESTART_WRITE_EVIDENCE.json").read_text())
v=json.loads((w/"candidate-10/PERFORMANCE_RESULT.json").read_text())
assert e["status"]=="G1_PHASE_A_RESTART_FILE_PRESENT_NOT_RESTART_VERIFIED"
assert e["restart_verified"] is False
assert v["status"]=="SHORT_FSI_PERFORMANCE_PASS"
assert v["participant_exit_codes"]=={"fluid":0,"solid":0}
print("G1_PHASE_A_RESTART_WRITE_ONLY_PASS",flush=True)
PY
' bash "$WORK" "$SCRIPT"
echo "G1_PHASE_A_EXIT=0"
SBATCH
JOB="$(sbatch --parsable -p cpu -N 1 -n 1 -c 12 --mem=24G -t 04:00:00 \
  --export="ALL,G1_SCRIPT=$FROZEN,G1_SHA=$SHA" -J fsi-g1-rout10 \
  -o "$BASE/logs/fsi-g1-rout10-%j.out" \
  -e "$BASE/logs/fsi-g1-rout10-%j.err" "$BATCH")"
echo "SUBMITTED_G1_PHASE_A_JOB_ID=$JOB"
echo "RUN_DIR=$BASE/g1-rout10-job-$JOB"
echo "STDOUT=$BASE/logs/fsi-g1-rout10-$JOB.out"
echo "STDERR=$BASE/logs/fsi-g1-rout10-$JOB.err"
echo "FROZEN_SCRIPT_SHA256=$SHA"
