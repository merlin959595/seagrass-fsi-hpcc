#!/usr/bin/env bash
# Sole purpose: true 2-window restart at t=0.0325 with aligned original
# interface reference + BOTH initialized Force and Displacement; no long chain.
# Independent scratch case; leave 91543 running, no writes to original checkpoints.
set -euo pipefail
BASE="$HOME/hpcc-fsi"
SRC="$BASE/clean-production-src/try-aligned-reference-and-both-initial.py"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
ROOT="$BASE/ale-aligned-reference-bothinit"
test -s "$SRC" && test -s "$SIF"
test -s "$BASE/seagrass-fsi-mainline/bin/segment.py"
mkdir -p "$ROOT"
python3 -m py_compile "$SRC"
python3 "$SRC" --self-test
python3 "$SRC" --base "$BASE" --preflight
ACTIVE="$(squeue -h -u "$USER" -n fsi-frame2 -o '%j %T')" || exit 42
if [[ -n "$ACTIVE" ]];then
  echo "STOP: candidate already queued/running" >&2
  exit 43
fi
for name in seagrassFSI fsi-real-long fsi-ref-8w fsi-initial8 fsi-bothinit2;do
  BUSY="$(squeue -h -u "$USER" -n "$name" -o '%j %T')" || exit 44
  if [[ -n "$BUSY" ]];then
    echo "STOP: another FSI calculation is running or queued under $name" >&2
    exit 45
  fi
done
HASH="$(sha256sum "$SRC"|awk '{print $1}')"
PIN="$ROOT/test-$(printf %.16s "$HASH").py"
if [[ -e "$PIN" ]];then
  cmp -s "$PIN" "$SRC" || exit 46
else
  cp "$SRC" "$PIN"
  chmod a-w "$PIN"
fi
BATCH="$ROOT/reference2.$(printf %.12s "$HASH").sbatch"
if [[ -e "$BATCH" ]];then
  echo "STOP: archived submission already exists; no accidental double-use" >&2
  exit 47
fi
cat > "$BATCH" <<'SBATCH'
#!/usr/bin/env bash
set -euo pipefail
BASE="$HOME/hpcc-fsi"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
WORK="$BASE/ale-aligned-reference-bothinit/trial-$SLURM_JOB_ID"
test ! -e "$WORK"
test "$(sha256sum "$FSI_INITIAL_SOURCE"|awk '{print $1}')" = "$FSI_INITIAL_HASH"
echo "FSI_ALIGNED_REFERENCE_BOTH_INITIAL_DATA_START $(date -Is)"
env -u BASH_ENV -u ENV singularity exec --cleanenv "$SIF" \
  /usr/bin/env -u BASH_ENV -u ENV /bin/bash --noprofile --norc -c '
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
test -x "$(command -v pimpleFoam)"
test -x "$(command -v precice-config-validate)"
test -x "$ROOT/scripts/native/bin/ccx_preCICE_persistent_v2"
test -f "$ROOT/scripts/native/lib/libseagrassReferenceRestart.so"
export SLURM_JOB_ID="$3"
python3 "$1" --base "$HOME/hpcc-fsi" --work "$2" --run
' bash "$FSI_INITIAL_SOURCE" "$WORK" "$SLURM_JOB_ID"
echo "FSI_REFERENCE_ALIGNMENT_TEST_EXECUTION_COMPLETE"
SBATCH
bash -n "$BATCH"
job="$(sbatch --parsable --partition=cpu --nodes=1 --ntasks=1 \
  --cpus-per-task=12 --mem=24G --time=01:00:00 \
  --job-name=fsi-frame2 \
  --export="ALL,BASH_ENV=,ENV=,FSI_INITIAL_SOURCE=$PIN,FSI_INITIAL_HASH=$HASH" \
  --output="$ROOT/test-%j.out" \
  --error="$ROOT/test-%j.err" "$BATCH")"
echo "已提交: 一次2窗口参考构形对齐+双向非零初始化的真实FSI实验；不触发后续长程计算。"
echo "STATUS_COMMAND=squeue -u \"\$USER\" -n fsi-frame2"
echo "RESULT_DIRECTORY=$ROOT/trial-$job"
echo "RESULT_FILE=$ROOT/trial-$job/REFERENCE_ALIGNED_BOTH_FIELDS_RESULT.json"
