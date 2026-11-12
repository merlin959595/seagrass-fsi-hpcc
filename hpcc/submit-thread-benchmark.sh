#!/usr/bin/env bash
# One three-hour Slurm allocation, independent 6-window FSI runs, 2->1->4 threads.
set -euo pipefail
BASE="$HOME/hpcc-fsi"
ROOT="$BASE/seagrass-implicit-20261111"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
SCRIPT="$BASE/benchmark-short-fsi.py"
LOGDIR="$BASE/logs"
mkdir -p "$LOGDIR"
test -s "$ROOT/fsi-implicit-production/run_production.py"
test -s "$SIF"
test -s "$SCRIPT"
test -s "$BASE/implicit-pilot-002-8mpi-timefix-87186/production/STATE.json"
python3 -m py_compile "$SCRIPT"
if test -s "$SIF.sha256"; then sha256sum -c "$SIF.sha256"; fi
BATCH="$(mktemp "$BASE/short-fsi-threads.XXXXXXXX.sbatch")"
cat >"$BATCH" <<'SBATCH'
#!/usr/bin/env bash
set -euo pipefail
BASE="$HOME/hpcc-fsi"
ROOT="$BASE/seagrass-implicit-20261111"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
WORK="$BASE/performance-threads-job-${SLURM_JOB_ID:?}"
SCRIPT="$BASE/benchmark-short-fsi.py"
test ! -e "$WORK" || { echo "FATAL: existing workdir $WORK"; exit 21; }
mkdir "$WORK"
echo "THREAD_BENCHMARK_START job=$SLURM_JOB_ID host=$(hostname) time=$(date -Is)"
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
for thr in 2 1 4; do
  echo "========== START REAL FSI: CCX OMP threads=$thr =========="
  python3 "$SCRIPT" --work "$RUN_BASE/threads-$thr" --threads "$thr" --windows 6 --iqn-reuse 5
  echo "========== PASS REAL FSI: CCX OMP threads=$thr =========="
done
python3 - "$RUN_BASE" <<"PY"
import json,sys
from pathlib import Path
b=Path(sys.argv[1])
rows=[]
for t in (2,1,4):
    r=json.loads((b/f"threads-{t}/PERFORMANCE_RESULT.json").read_text())
    rows.append({"threads":t,"wall_s":r["wall_s"],"s_per_window":r["s_per_window"],
                 "iterations":r["coupling_iterations"],
                 "s_per_iteration":r["wall_s"]/r["coupling_iterations"],
                 "tip_error_m":r["tip_and_load_comparison"]["tip"]["error_norm"],
                 "force_error_N":r["tip_and_load_comparison"]["loads"]["error_norm"]})
(b/"PERFORMANCE_RANKING.json").write_text(json.dumps(sorted(rows,key=lambda x:x["s_per_window"]),indent=2)+"\n")
print("THREAD_BENCHMARK_RANKING",json.dumps(sorted(rows,key=lambda x:x["s_per_window"])))
PY
echo "THREAD_BENCHMARK_ALL_VARIANTS_PASS"
' bash "$WORK" "$SCRIPT"
echo "THREAD_BENCHMARK_EXIT=0"
SBATCH
JOB="$(sbatch --parsable -p cpu -N 1 -n 1 -c 12 --mem=24G -t 03:00:00 \
  -J fsi-omp-bench -o "$LOGDIR/fsi-omp-bench-%j.out" -e "$LOGDIR/fsi-omp-bench-%j.err" "$BATCH")"
echo "SUBMITTED_JOB_ID=$JOB"
echo "RUN_DIR=$BASE/performance-threads-job-$JOB"
echo "STDOUT=$LOGDIR/fsi-omp-bench-$JOB.out"
echo "STDERR=$LOGDIR/fsi-omp-bench-$JOB.err"
