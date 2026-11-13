#!/usr/bin/env bash
# Independent 6-window full FSI scaling check for CCX 8 and 12 OMP threads.
set -euo pipefail
BASE="$HOME/hpcc-fsi"
ROOT="$BASE/seagrass-implicit-20261111"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
SCRIPT="$BASE/benchmark-short-fsi.py"
AUDIT="$BASE/performance-thread4-job-88475/threads-4/PERFORMANCE_RESULT.json"
LOGDIR="$BASE/logs"
mkdir -p "$LOGDIR"
test -s "$ROOT/fsi-implicit-production/run_production.py"
test -s "$SIF"
test -s "$SCRIPT"
test -s "$BASE/implicit-pilot-002-8mpi-timefix-87186/production/STATE.json"
test -s "$BASE/performance-iqn20-job-88550/reuse-15/PERFORMANCE_RESULT.json"
test -s "$AUDIT"
python3 - "$AUDIT" <<'AUDIT_CHECK'
import json,sys
r=json.load(open(sys.argv[1]))
assert r["status"]=="SHORT_FSI_PERFORMANCE_PASS"
assert r["threads"]==4 and r["windows"]==6
assert r["spooles_thread_evidence"]["actual_spooles_threads"]==4
print("BASELINE_THREAD4_REAL_6WINDOW_PASS")
AUDIT_CHECK
python3 -m py_compile "$SCRIPT"
# Validate actual 87186 dictionaries BEFORE consuming a Slurm allocation.
python3 "$SCRIPT" --inspect-only --windows 6
# Prevent accidental duplicate runs; do not cancel or alter any existing job.
if command -v squeue >/dev/null 2>&1; then
  ACTIVE="$(squeue -h -u "$USER" -n fsi-omp-scale,fsi-omp-bench,fsi-omp-4only -o '%i %T' 2>/dev/null || true)"
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
BATCH="$(mktemp "$BASE/fsi-omp-scale.XXXXXXXX.sbatch")"
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
for thr in 8 12; do
  echo "========== START REAL FSI: CCX OMP threads=$thr =========="
  python3 "$SCRIPT" --work "$RUN_BASE/threads-$thr" --threads "$thr" --windows 6 --iqn-reuse 5
  echo "========== PASS REAL FSI: CCX OMP threads=$thr =========="
done
python3 - "$RUN_BASE" <<"PY"
import json,sys
from pathlib import Path
b=Path(sys.argv[1])
ref=json.loads((Path.home()/"hpcc-fsi/performance-thread4-job-88475/threads-4/PERFORMANCE_RESULT.json").read_text())
rows=[{"threads":4,"wall_s":ref["wall_s"],"coupling_iterations":ref["coupling_iterations"],
       "s_per_window":ref["s_per_window"],"node":"cpu-40-14 (old; different allocation)"}]
for n in (8,12):
    r=json.loads((b/f"threads-{n}/PERFORMANCE_RESULT.json").read_text())
    if (r.get("status")!="SHORT_FSI_PERFORMANCE_PASS" or r.get("windows")!=6
        or r.get("threads")!=n or
        r.get("spooles_thread_evidence",{}).get("actual_spooles_threads")!=n):
        raise RuntimeError(f"Scaling candidate {n} failed acceptance")
    rows.append({"threads":n,"wall_s":r["wall_s"],"coupling_iterations":r["coupling_iterations"],
                 "s_per_window":r["s_per_window"],"node":"same new Slurm allocation"})
ranking=sorted(rows,key=lambda x:x["wall_s"])
(b/"OMP_SCALING_RANKING.json").write_text(json.dumps(ranking,indent=2)+"\n")
print("OMP_SCALING_RANKING",json.dumps(ranking))
PY
echo "OMP_SCALING_ALL_VARIANTS_PASS"
' bash "$WORK" "$SCRIPT"
echo "OMP_SCALING_EXIT=0"
SBATCH
JOB="$(sbatch --parsable -p cpu -N 1 -n 1 -c 24 --mem=48G -t 04:00:00 \
  -J fsi-omp-scale -o "$LOGDIR/fsi-omp-scale-%j.out" -e "$LOGDIR/fsi-omp-scale-%j.err" "$BATCH")"
echo "SUBMITTED_JOB_ID=$JOB"
echo "RUN_DIR=$BASE/performance-thread4-job-$JOB"
echo "STDOUT=$LOGDIR/fsi-omp-scale-$JOB.out"
echo "STDERR=$LOGDIR/fsi-omp-scale-$JOB.err"
