#!/usr/bin/env bash
# One three-hour Slurm allocation, ONLY the missing 4-thread variant after 88107.
set -euo pipefail
BASE="$HOME/hpcc-fsi"
ROOT="$BASE/seagrass-implicit-20261111"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
SCRIPT="$BASE/benchmark-short-fsi.py"
AUDIT="$BASE/performance-threads-audit-88107/thread1.json"
LOGDIR="$BASE/logs"
mkdir -p "$LOGDIR"
test -s "$ROOT/fsi-implicit-production/run_production.py"
test -s "$SIF"
test -s "$SCRIPT"
test -s "$BASE/implicit-pilot-002-8mpi-timefix-87186/production/STATE.json"
test -s "$BASE/performance-threads-job-88107/threads-2/PERFORMANCE_RESULT.json"
test -s "$AUDIT"
python3 - "$AUDIT" <<'AUDIT_CHECK'
import json,sys
a=json.load(open(sys.argv[1]))
assert a["status"]=="READ_ONLY_RETROSPECTIVE_AUDIT_PASS" and a["job"]==88107 and a["threads"]==1 and a["windows"]==6
print("88107_THREAD1_READ_ONLY_AUDIT_VERIFIED")
AUDIT_CHECK
python3 -m py_compile "$SCRIPT"
# Validate actual 87186 dictionaries BEFORE consuming a Slurm allocation.
python3 "$SCRIPT" --inspect-only --windows 6
# Prevent accidental duplicate runs; do not cancel or alter any existing job.
if command -v squeue >/dev/null 2>&1; then
  ACTIVE="$(squeue -h -u "$USER" -n fsi-omp-bench,fsi-omp-4only -o '%i %T' 2>/dev/null || true)"
  if [[ -n "$ACTIVE" ]]; then
    echo "REFUSE_DUPLICATE: existing FSI thread benchmark job(s):"
    printf '%s\n' "$ACTIVE"
    exit 41
  fi
else
  echo "STOP: Slurm squeue unavailable, cannot safely check duplicates"
  exit 42
fi
if test -s "$SIF.sha256"; then sha256sum -c "$SIF.sha256"; fi
BATCH="$(mktemp "$BASE/short-fsi-threads.XXXXXXXX.sbatch")"
cat >"$BATCH" <<'SBATCH'
#!/usr/bin/env bash
set -euo pipefail
BASE="$HOME/hpcc-fsi"
ROOT="$BASE/seagrass-implicit-20261111"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
WORK="$BASE/performance-thread4-job-${SLURM_JOB_ID:?}"
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
for thr in 4; do
  echo "========== START REAL FSI: CCX OMP threads=$thr =========="
  python3 "$SCRIPT" --work "$RUN_BASE/threads-$thr" --threads "$thr" --windows 6 --iqn-reuse 5
  echo "========== PASS REAL FSI: CCX OMP threads=$thr =========="
done
python3 - "$RUN_BASE" <<"PY"
import json,sys
from pathlib import Path
b=Path(sys.argv[1])
rows=[]
original=Path.home()/"hpcc-fsi/performance-threads-job-88107"
audit=Path.home()/"hpcc-fsi/performance-threads-audit-88107/thread1.json"
inputs=[
    json.loads((original/"threads-2/PERFORMANCE_RESULT.json").read_text()),
    json.loads(audit.read_text()),
    json.loads((b/"threads-4/PERFORMANCE_RESULT.json").read_text()),
]
for r in inputs:
    if r["status"] not in ("SHORT_FSI_PERFORMANCE_PASS", "READ_ONLY_RETROSPECTIVE_AUDIT_PASS"):
        raise RuntimeError(f"Non-accepted performance record for thread {r.get('threads')}")
    rows.append({"threads":r["threads"],"wall_s":r["wall_s"],"s_per_window":r["s_per_window"],
                 "iterations":r["coupling_iterations"],
                 "s_per_iteration":r["wall_s"]/r["coupling_iterations"],
                 "tip_error_m":r["tip_and_load_comparison"]["tip"]["error_norm"],
                 "force_error_N":r["tip_and_load_comparison"]["loads"]["error_norm"]})
if sorted(x["threads"] for x in rows) != [1,2,4]:
    raise RuntimeError("Missing or duplicate thread candidates")
(b/"PERFORMANCE_RANKING.json").write_text(json.dumps(sorted(rows,key=lambda x:x["s_per_window"]),indent=2)+"\n")
print("THREAD_BENCHMARK_RANKING",json.dumps(sorted(rows,key=lambda x:x["s_per_window"])))
PY
echo "THREAD_BENCHMARK_ALL_VARIANTS_PASS"
' bash "$WORK" "$SCRIPT"
echo "THREAD_BENCHMARK_EXIT=0"
SBATCH
JOB="$(sbatch --parsable -p cpu -N 1 -n 1 -c 12 --mem=24G -t 03:00:00 \
  -J fsi-omp-4only -o "$LOGDIR/fsi-omp-4only-%j.out" -e "$LOGDIR/fsi-omp-4only-%j.err" "$BATCH")"
echo "SUBMITTED_JOB_ID=$JOB"
echo "RUN_DIR=$BASE/performance-thread4-job-$JOB"
echo "STDOUT=$LOGDIR/fsi-omp-4only-$JOB.out"
echo "STDERR=$LOGDIR/fsi-omp-4only-$JOB.err"
