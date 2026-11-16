#!/usr/bin/env bash
# Real 20-window FSI validation of combined winner:
# fluid 8 MPI + CalculiX 12 OMP + preCICE IQN-ILS history reuse 15.
# Isolated comparison against successful 88550 4-OMP / IQN15 / 20 windows.
# Never modifies 87186, 88550, 89038, 89079 or original controller.
set -euo pipefail
BASE="$HOME/hpcc-fsi"
ROOT="$BASE/seagrass-implicit-20261111"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
SCRIPT="$BASE/benchmark-short-fsi.py"
REF="$BASE/performance-iqn20-job-88550/reuse-15/PERFORMANCE_RESULT.json"
THREAD12_REF="$BASE/performance-omp-scale-job-89079/threads-12/PERFORMANCE_RESULT.json"
LOGDIR="$BASE/logs"
mkdir -p "$LOGDIR"
test -s "$ROOT/fsi-implicit-production/run_production.py"
test -s "$BASE/implicit-pilot-002-8mpi-timefix-87186/production/STATE.json"
test -s "$REF"
test -s "$THREAD12_REF"
test -s "$SIF"
test -s "$SCRIPT"
python3 - "$REF" "$THREAD12_REF" <<'VERIFY'
import json,sys
a,b=(json.load(open(x)) for x in sys.argv[1:])
assert a["status"]=="SHORT_FSI_PERFORMANCE_PASS"
assert (a["threads"],a["windows"],a["iqn_reuse"])==(4,20,15)
assert a["spooles_thread_evidence"]["actual_spooles_threads"]==4
assert b["status"]=="SHORT_FSI_PERFORMANCE_PASS"
assert (b["threads"],b["windows"])==(12,6)
assert b["spooles_thread_evidence"]["actual_spooles_threads"]==12
print("REFERENCE_88550_IQN15_20_AND_89079_THREAD12_VERIFIED")
VERIFY
python3 -m py_compile "$SCRIPT"
python3 "$SCRIPT" --inspect-only --windows 20 --iqn-reuse 15
command -v squeue >/dev/null || { echo "STOP: Slurm status command unavailable"; exit 42; }
if ! ACTIVE="$(squeue -h -u "$USER" -n fsi-omp12-iqn15,fsi-omp-scale -o '%i %T' 2>&1)"; then
  echo "STOP: Slurm job status unavailable: $ACTIVE"
  exit 43
fi
if [[ -n "$ACTIVE" ]]; then
  echo "REFUSE_DUPLICATE: $ACTIVE"
  exit 41
fi
if [[ -s "$SIF.sha256" ]]; then sha256sum -c "$SIF.sha256"; fi
SHA="$(sha256sum "$SCRIPT" | awk '{print $1}')"
SNAPSHOT="$BASE/benchmark-omp12-iqn15-${SHA:0:16}.py"
if [[ -f "$SNAPSHOT" ]]; then
  cmp -s "$SCRIPT" "$SNAPSHOT" || { echo "STOP: snapshot hash collision"; exit 44; }
else
  cp "$SCRIPT" "$SNAPSHOT"
  chmod a-w "$SNAPSHOT"
fi
BATCH="$(mktemp "$BASE/omp12-iqn15.XXXXXXXX.sbatch")"
cat >"$BATCH" <<'SBATCH'
#!/usr/bin/env bash
set -euo pipefail
BASE="$HOME/hpcc-fsi"
ROOT="$BASE/seagrass-implicit-20261111"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
WORK="$BASE/performance-omp12-iqn15-job-${SLURM_JOB_ID:?}"
SCRIPT="${FSI_OMP12_SCRIPT:?}"
EXPECTED="${FSI_OMP12_SHA:?}"
test ! -e "$WORK" || { echo "STOP: existing work directory: $WORK"; exit 21; }
test "$(sha256sum "$SCRIPT" | awk '{print $1}')" = "$EXPECTED" \
  || { echo "STOP: frozen benchmark code changed"; exit 22; }
mkdir "$WORK"
echo "OMP12_IQN15_START job=$SLURM_JOB_ID host=$(hostname) time=$(date -Is)"
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
echo "========== START REAL FSI: MPI8 CCX12 IQN15 windows20 =========="
python3 "$SCRIPT" --work "$RUN_BASE/optimized-20" \
  --threads 12 --windows 20 --iqn-reuse 15
python3 - "$RUN_BASE" <<"PY"
import json,sys
from pathlib import Path
b=Path(sys.argv[1])
ref=json.loads((Path.home()/"hpcc-fsi/performance-iqn20-job-88550/reuse-15/PERFORMANCE_RESULT.json").read_text())
r=json.loads((b/"optimized-20/PERFORMANCE_RESULT.json").read_text())
assert r["status"]=="SHORT_FSI_PERFORMANCE_PASS"
assert r["threads"]==12 and r["windows"]==20 and r["iqn_reuse"]==15
assert r["spooles_thread_evidence"]["actual_spooles_threads"]==12
assert r["participant_exit_codes"]=={"fluid":0,"solid":0}
out={
 "status":"OPTIMIZED_20_12THREAD_IQN15_PASS",
 "baseline_4_threads_job":88550,
 "new_job":b.name,
 "reference_wall_s":ref["wall_s"],
 "new_wall_s":r["wall_s"],
 "wall_time_saved_pct":100*(ref["wall_s"]-r["wall_s"])/ref["wall_s"],
 "reference_coupling_iterations":ref["coupling_iterations"],
 "new_coupling_iterations":r["coupling_iterations"],
 "tip_and_load_comparison":r["tip_and_load_comparison"],
 "quality":r["quality"],
 "restart_verified":False
}
(b/"OMP12_IQN15_20_COMPARISON.json").write_text(json.dumps(out,indent=2)+"\n")
print("OMP12_IQN15_20_COMPARISON",json.dumps(out))
PY
echo "OMP12_IQN15_20_PASS"
' bash "$WORK" "$SCRIPT"
echo "OMP12_IQN15_20_EXIT=0"
SBATCH
JOB="$(sbatch --parsable -p cpu -N 1 -n 1 -c 24 --mem=48G -t 04:00:00 \
  --export="ALL,FSI_OMP12_SCRIPT=$SNAPSHOT,FSI_OMP12_SHA=$SHA" \
  -J fsi-omp12-iqn15 -o "$LOGDIR/fsi-omp12-iqn15-%j.out" \
  -e "$LOGDIR/fsi-omp12-iqn15-%j.err" "$BATCH")"
echo "SUBMITTED_JOB_ID=$JOB"
echo "RUN_DIR=$BASE/performance-omp12-iqn15-job-$JOB"
echo "STDOUT=$LOGDIR/fsi-omp12-iqn15-$JOB.out"
echo "STDERR=$LOGDIR/fsi-omp12-iqn15-$JOB.err"
echo "FROZEN_SCRIPT_SHA256=$SHA"
