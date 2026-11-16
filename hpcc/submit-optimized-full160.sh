#!/usr/bin/env bash
# Run ONE full 160-window optimized real 3D implicit FSI gate: 8 MPI, CCX 4 OMP, IQN history 15.
# New isolated output directory. Original 87186 and all prior successful experiments remain untouched.
set -euo pipefail
BASE="$HOME/hpcc-fsi"
ROOT="$BASE/seagrass-implicit-20261111"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
SCRIPT="$BASE/benchmark-short-fsi.py"
LOGDIR="$BASE/logs"
mkdir -p "$LOGDIR"
test -s "$ROOT/fsi-implicit-production/run_production.py"
test -s "$BASE/implicit-pilot-002-8mpi-timefix-87186/production/STATE.json"
test -s "$BASE/performance-iqn20-job-88550/reuse-15/PERFORMANCE_RESULT.json"
test -s "$SCRIPT"
test -s "$SIF"
python3 - "$BASE/performance-iqn20-job-88550/reuse-15/PERFORMANCE_RESULT.json" <<'CHECK4'
import json,sys
r=json.load(open(sys.argv[1]))
if (r.get("status") != "SHORT_FSI_PERFORMANCE_PASS" or
    r.get("threads") != 4 or r.get("windows") != 20 or r.get("iqn_reuse") != 15 or
    r.get("spooles_thread_evidence",{}).get("actual_spooles_threads") != 4):
    raise SystemExit("STOP: trusted 88550 IQN15 20-window reference verification failed")
print("FROZEN_88550_IQN15_REFERENCE_PASS")
CHECK4
python3 -m py_compile "$SCRIPT"
echo "===== READ-ONLY FULL 160-WINDOW PREFLIGHT, IQN=15 ====="
python3 "$SCRIPT" --inspect-only --windows 160 --iqn-reuse 15
command -v squeue >/dev/null 2>&1 || { echo "STOP: squeue unavailable"; exit 42; }
if ! ACTIVE="$(squeue -h -u "$USER" -n fsi-full-opt,fsi-iqn20,fsi-omp-bench,fsi-omp-4only -o '%i %T' 2>&1)"; then
  echo "STOP: cannot safely check active Slurm jobs: $ACTIVE"
  exit 43
fi
if [[ -n "$ACTIVE" ]]; then
  echo "REFUSE_DUPLICATE: existing FSI benchmark(s):"
  printf '%s\n' "$ACTIVE"
  exit 41
fi
if [[ -s "$SIF.sha256" ]]; then sha256sum -c "$SIF.sha256"; fi

# Freeze the script by content hash so queue delay cannot change its code.
SHA="$(sha256sum "$SCRIPT" | awk '{print $1}')"
SNAPSHOT="$BASE/benchmark-full-160-iqn15-${SHA:0:16}.py"
if [[ -e "$SNAPSHOT" ]]; then
  cmp -s "$SCRIPT" "$SNAPSHOT" || { echo "STOP: snapshot name collision"; exit 44; }
else
  cp "$SCRIPT" "$SNAPSHOT"
  chmod a-w "$SNAPSHOT"
fi

BATCH="$(mktemp "$BASE/full160-fsi.XXXXXXXX.sbatch")"
cat >"$BATCH" <<'SBATCH'
#!/usr/bin/env bash
set -euo pipefail
BASE="$HOME/hpcc-fsi"
ROOT="$BASE/seagrass-implicit-20261111"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
WORK="$BASE/performance-full160-job-${SLURM_JOB_ID:?}"
SCRIPT="${FSI_FULL160_SCRIPT:?}"
EXPECTED="${FSI_FULL160_SHA:?}"
test ! -e "$WORK" || { echo "FATAL: existing work directory $WORK"; exit 21; }
mkdir "$WORK"
ACTUAL="$(sha256sum "$SCRIPT" | awk '{print $1}')"
test "$ACTUAL" = "$EXPECTED" || { echo "FATAL: benchmark source changed"; exit 22; }
printf 'SOURCE_SHA256=%s\n' "$ACTUAL" >"$WORK/SOURCE_SHA256.txt"
echo "FULL160_OPTIMIZED_BENCHMARK_START job=$SLURM_JOB_ID host=$(hostname) time=$(date -Is)"
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
RUN_BASE="$1"
SCRIPT="$2"
echo "========== START OPTIMIZED FULL FSI: IQN=15, CCX OMP=4, fluid MPI=8, windows=160 =========="
python3 "$SCRIPT" --work "$RUN_BASE/optimized-160" \
  --threads 4 --windows 160 --iqn-reuse 15
python3 - "$RUN_BASE" <<"PY"
import json,sys
from pathlib import Path
b=Path(sys.argv[1])
p=b/"optimized-160/PERFORMANCE_RESULT.json"
r=json.loads(p.read_text())
if (r.get("status")!="OPTIMIZED_0P02_FSI_PASS"
    or r.get("windows")!=160 or r.get("iqn_reuse")!=15
    or r.get("threads")!=4 or
    r.get("spooles_thread_evidence",{}).get("actual_spooles_threads")!=4):
    raise RuntimeError("Full optimized FSI 160-window independent acceptance failed")
summary={
    "status":"OPTIMIZED_0P02_FSI_PASS",
    "baseline_job":87186,
    "fluid_mpi":8,
    "solid_omp":4,
    "iqn_history":15,
    "windows":160,
    "physical_time_s":0.02,
    "wall_s":r["wall_s"],
    "coupling_iterations":r["coupling_iterations"],
    "tip_and_load_comparison":r["tip_and_load_comparison"],
    "quality":r["quality"],
    "restart_verified":False
}
(b/"OPTIMIZED_160_SUMMARY.json").write_text(json.dumps(summary,indent=2)+"\n")
print("OPTIMIZED_FULL160_SUMMARY",json.dumps(summary))
PY
echo "OPTIMIZED_FULL160_PASS"
' bash "$WORK" "$SCRIPT"
echo "OPTIMIZED_FULL160_EXIT=0"
SBATCH
JOB="$(sbatch --parsable -p cpu -N 1 -n 1 -c 12 --mem=24G -t 24:00:00 \
  --export="ALL,FSI_FULL160_SCRIPT=$SNAPSHOT,FSI_FULL160_SHA=$SHA" \
  -J fsi-full-opt -o "$LOGDIR/fsi-full-opt-%j.out" -e "$LOGDIR/fsi-full-opt-%j.err" "$BATCH")"
echo "SUBMITTED_JOB_ID=$JOB"
echo "RUN_DIR=$BASE/performance-full160-job-$JOB"
echo "STDOUT=$LOGDIR/fsi-full-opt-$JOB.out"
echo "STDERR=$LOGDIR/fsi-full-opt-$JOB.err"
echo "FROZEN_SCRIPT_SHA256=$SHA"
