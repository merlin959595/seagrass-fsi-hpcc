#!/usr/bin/env bash
# Compare IQN-ILS history reuse 5,10,15 in independent 20-window real FSI runs.
# Fixed 8 fluid MPI ranks, 4 CCX OMP threads; original 87186 untouched.
set -euo pipefail
BASE="$HOME/hpcc-fsi"
ROOT="$BASE/seagrass-implicit-20261111"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
SCRIPT="$BASE/benchmark-short-fsi.py"
LOGDIR="$BASE/logs"
mkdir -p "$LOGDIR"
test -s "$ROOT/fsi-implicit-production/run_production.py"
test -s "$BASE/implicit-pilot-002-8mpi-timefix-87186/production/STATE.json"
test -s "$BASE/performance-thread4-job-88475/threads-4/PERFORMANCE_RESULT.json"
test -s "$SCRIPT"
test -s "$SIF"
python3 - "$BASE/performance-thread4-job-88475/threads-4/PERFORMANCE_RESULT.json" <<'CHECK4'
import json,sys
r=json.load(open(sys.argv[1]))
if (r.get("status") != "SHORT_FSI_PERFORMANCE_PASS" or
    r.get("threads") != 4 or r.get("windows") != 6 or
    r.get("spooles_thread_evidence",{}).get("actual_spooles_threads") != 4):
    raise SystemExit("STOP: trusted 88475 4-thread reference verification failed")
print("FROZEN_88475_THREAD4_REFERENCE_PASS")
CHECK4
python3 -m py_compile "$SCRIPT"
for reuse in 5 10 15; do
  echo "===== READ-ONLY IQN20 PREFLIGHT history=$reuse ====="
  python3 "$SCRIPT" --inspect-only --windows 20 --iqn-reuse "$reuse"
done
command -v squeue >/dev/null 2>&1 || { echo "STOP: squeue unavailable"; exit 42; }
if ! ACTIVE="$(squeue -h -u "$USER" -n fsi-iqn20,fsi-omp-bench,fsi-omp-4only -o '%i %T' 2>&1)"; then
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
SNAPSHOT="$BASE/benchmark-short-fsi-iqn20-${SHA:0:16}.py"
if [[ -e "$SNAPSHOT" ]]; then
  cmp -s "$SCRIPT" "$SNAPSHOT" || { echo "STOP: snapshot name collision"; exit 44; }
else
  cp "$SCRIPT" "$SNAPSHOT"
  chmod a-w "$SNAPSHOT"
fi

BATCH="$(mktemp "$BASE/iqn20-fsi.XXXXXXXX.sbatch")"
cat >"$BATCH" <<'SBATCH'
#!/usr/bin/env bash
set -euo pipefail
BASE="$HOME/hpcc-fsi"
ROOT="$BASE/seagrass-implicit-20261111"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
WORK="$BASE/performance-iqn20-job-${SLURM_JOB_ID:?}"
SCRIPT="${FSI_IQN20_SCRIPT:?}"
EXPECTED="${FSI_IQN20_SHA:?}"
test ! -e "$WORK" || { echo "FATAL: existing work directory $WORK"; exit 21; }
mkdir "$WORK"
ACTUAL="$(sha256sum "$SCRIPT" | awk '{print $1}')"
test "$ACTUAL" = "$EXPECTED" || { echo "FATAL: benchmark source changed"; exit 22; }
printf 'SOURCE_SHA256=%s\n' "$ACTUAL" >"$WORK/SOURCE_SHA256.txt"
echo "IQN20_BENCHMARK_START job=$SLURM_JOB_ID host=$(hostname) time=$(date -Is)"
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
for reuse in 5 10 15; do
  echo "========== START REAL FSI: IQN=$reuse, CCX OMP=4, fluid MPI=8, windows=20 =========="
  python3 "$SCRIPT" --work "$RUN_BASE/reuse-$reuse" \
    --threads 4 --windows 20 --iqn-reuse "$reuse"
  echo "========== PASS REAL FSI: IQN=$reuse =========="
done
python3 - "$RUN_BASE" <<"PY"
import json,sys
from pathlib import Path
b=Path(sys.argv[1])
rows=[]
for h in (5,10,15):
    r=json.loads((b/f"reuse-{h}/PERFORMANCE_RESULT.json").read_text())
    if (r.get("status") != "SHORT_FSI_PERFORMANCE_PASS"
        or r.get("threads") != 4 or r.get("windows") != 20
        or r.get("iqn_reuse") != h
        or r.get("spooles_thread_evidence",{}).get("actual_spooles_threads") != 4):
        raise RuntimeError(f"Unverified candidate IQN reuse {h}")
    rows.append({
        "iqn_reuse":h, "wall_s":r["wall_s"],
        "s_per_window":r["s_per_window"],
        "coupling_iterations":r["coupling_iterations"],
        "iterations_per_window":r["iterations_per_window"],
        "s_per_iteration":r["wall_s"]/r["coupling_iterations"],
        "tip_error_m":r["tip_and_load_comparison"]["tip"]["error_norm"],
        "force_error_N":r["tip_and_load_comparison"]["loads"]["error_norm"]
    })
five=next(r for r in rows if r["iqn_reuse"]==5)
for r in rows:
    r["wall_time_saved_vs_reuse5_pct"] = 100*(five["wall_s"]-r["wall_s"])/five["wall_s"]
    r["iterations_saved_vs_reuse5_pct"] = 100*(five["coupling_iterations"]-r["coupling_iterations"])/five["coupling_iterations"]
ranked=sorted(rows,key=lambda x:x["wall_s"])
(b/"IQN20_PERFORMANCE_RANKING.json").write_text(json.dumps(ranked,indent=2)+"\n")
print("IQN20_PERFORMANCE_RANKING",json.dumps(ranked))
PY
echo "IQN20_ALL_VARIANTS_PASS"
' bash "$WORK" "$SCRIPT"
echo "IQN20_BENCHMARK_EXIT=0"
SBATCH
JOB="$(sbatch --parsable -p cpu -N 1 -n 1 -c 12 --mem=24G -t 06:00:00 \
  --export="ALL,FSI_IQN20_SCRIPT=$SNAPSHOT,FSI_IQN20_SHA=$SHA" \
  -J fsi-iqn20 -o "$LOGDIR/fsi-iqn20-%j.out" -e "$LOGDIR/fsi-iqn20-%j.err" "$BATCH")"
echo "SUBMITTED_JOB_ID=$JOB"
echo "RUN_DIR=$BASE/performance-iqn20-job-$JOB"
echo "STDOUT=$LOGDIR/fsi-iqn20-$JOB.out"
echo "STDERR=$LOGDIR/fsi-iqn20-$JOB.err"
echo "FROZEN_SCRIPT_SHA256=$SHA"
