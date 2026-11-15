#!/usr/bin/env bash
# One real 72h 3D FSI Slurm allocation, no silent cross-session continuation.
set -euo pipefail
BASE="$HOME/hpcc-fsi"
SRC="$BASE/clean-production-src/run-three-day.py"
ROOT="$BASE/three-day-proven"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
CORE="$BASE/seagrass-fsi-mainline/bin/segment.py"
test -s "$SRC" && test -s "$SIF" && test -s "$CORE"
test -s "$BASE/FSI_91006_RESUME_CERT.json"
mkdir -p "$ROOT"
python3 -m py_compile "$SRC"
python3 "$SRC" --self-test
python3 "$SRC" --base "$BASE" --preflight
JOBS="$(squeue -h -u "$USER" -o '%j %T')" || exit 42
if printf '%s\n' "$JOBS" | grep -Eiq '(^|[[:space:]])[^[:space:]]*(fsi|seagrass|precice|ccx)[^[:space:]]*[[:space:]]';then
  echo "Another FSI or CCX Slurm job exists; no duplicate compute" >&2
  printf '%s\n' "$JOBS" >&2
  exit 43
fi
if [[ -e "$ROOT/long-job.submitted" ]];then
  echo "This 3-day experiment already submitted; no duplicate" >&2
  exit 44
fi
HASH="$(sha256sum "$SRC"|awk '{print $1}')"
PIN="$ROOT/driver-$(printf %.16s "$HASH").py"
if [[ -e "$PIN" ]];then cmp -s "$SRC" "$PIN" || exit 45
else cp "$SRC" "$PIN";chmod a-w "$PIN";fi
BATCH="$ROOT/run-3day.sbatch"
test ! -e "$BATCH" || { echo "Batch script already exists" >&2; exit 46; }
cat > "$BATCH" <<'BATCH'
#!/usr/bin/env bash
set -euo pipefail
BASE="$HOME/hpcc-fsi"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
WORK="$BASE/three-day-proven/long-job-$SLURM_JOB_ID"
test ! -e "$WORK"
test "$(sha256sum "$FSI_THREEDAY_SCRIPT" | awk '{print $1}')" = "$FSI_THREEDAY_SHA"
echo "REAL_3D_FSI_ALLOCATION_START $(date -Is) NODE=$(hostname)"
env -u BASH_ENV -u ENV singularity exec --cleanenv "$SIF" \
  /usr/bin/env -u BASH_ENV -u ENV /bin/bash --noprofile --norc -c '
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
test -x "$(command -v pimpleFoam)"
test -x "$(command -v precice-config-validate)"
test -x "$ROOT/scripts/native/bin/ccx_preCICE_persistent_v2"
test -f "$ROOT/scripts/native/lib/libseagrassReferenceRestart.so"
test -x /usr/bin/time
ldd "$(command -v pimpleFoam)" > "$2/fluid-loader-$3.log"
ldd "$ROOT/scripts/native/bin/ccx_preCICE_persistent_v2" > "$2/solid-loader-$3.log"
if grep -Ei "not found" "$2/fluid-loader-$3.log" "$2/solid-loader-$3.log";then
  echo "FATAL unresolved shared library" >&2;exit 127
fi
mpirun --oversubscribe -np 2 --bind-to none pimpleFoam -help \
 > "$2/mpi-loader-$3.log" 2>&1 || { echo "MPI preflight failed" >&2;exit 127; }
echo "FSI_PRODUCTION_MPI_LOADER_PREFLIGHT_PASS"
export SLURM_JOB_ID="$3"
python3 "$1" --base "$HOME/hpcc-fsi" --work "$4" --run
' bash "$FSI_THREEDAY_SCRIPT" "$BASE/three-day-proven" "$SLURM_JOB_ID" "$WORK"
echo "REAL_3D_FSI_NORMAL_SCRIPT_EXIT $(date -Is)"
BATCH
bash -n "$BATCH"
job="$(sbatch --parsable --partition=cpu --nodes=1 --ntasks=1 \
  --cpus-per-task=12 --mem=24G --time=3-00:00:00 --no-requeue \
  --job-name=fsi-3d-safe \
  --export="ALL,BASH_ENV=,ENV=,FSI_THREEDAY_SCRIPT=$PIN,FSI_THREEDAY_SHA=$HASH" \
  --output="$ROOT/long-%j.out" --error="$ROOT/long-%j.err" "$BATCH")"
printf 'JOB=%s\nSOURCE=%s\nSHA256=%s\nSTART=0.0025\nTARGET=0.1625\nWINDOWS=1280\n' \
 "$job" "$PIN" "$HASH" > "$ROOT/long-job.submitted"
echo "FSI_3DAY_SINGLE_CONTINUOUS_JOB_SUBMITTED"
echo "计算段: $ROOT/long-job-$job"
echo "监控: bash $BASE/clean-production-src/monitor-three-day.sh"
echo "如成功结束，生成两个求解器一致的续算检查点；异常中断时不能保证结构restart存在。"
