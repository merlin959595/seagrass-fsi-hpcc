#!/usr/bin/env bash
# A single 8-window scientific restart-reference experiment; NOT the long run.
set -euo pipefail
BASE="$HOME/hpcc-fsi"
SOURCE="$BASE/clean-production-src/restart-reference-candidate.py"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
test -s "$SOURCE"
test -s "$BASE/seagrass-fsi-mainline/bin/segment.py"
test -s "$SIF"
mkdir -p "$BASE/ale-restart-reference-tests"
python3 -m py_compile "$SOURCE"
python3 "$SOURCE" --self-test
ACTIVE="$(squeue -h -u "$USER" -n fsi-ref-8w -o '%T' || exit 42)"
if [[ -n "$ACTIVE" ]];then
  echo "STOP: an active reference trial already exists: $ACTIVE" >&2
  exit 43
fi
HASH="$(sha256sum "$SOURCE" | awk '{print $1}')"
PIN="$BASE/ale-restart-reference-tests/test-$(printf %.16s "$HASH").py"
if [[ -e "$PIN" ]];then
  cmp -s "$PIN" "$SOURCE" || exit 44
else
  cp "$SOURCE" "$PIN"
  chmod a-w "$PIN"
fi
SBATCH="$BASE/ale-restart-reference-tests/run.sbatch"
if [[ -e "$SBATCH" ]];then
  echo "STOP: run.sbatch already exists; no silent overwrite" >&2
  exit 45
fi
cat > "$SBATCH" <<'BATCH'
#!/usr/bin/env bash
set -euo pipefail
BASE="$HOME/hpcc-fsi"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
OUT="$BASE/ale-restart-reference-tests/trial-$SLURM_JOB_ID"
test ! -e "$OUT"
test "$(sha256sum "$FSI_REF_SRC" | awk '{print $1}')" = "$FSI_REF_SHA"
echo "START_ALE_FSI_RESTART_8_WINDOW_REFERENCE_TRIAL=$(date -Is)"
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
test -x "$ROOT/scripts/native/bin/ccx_preCICE_persistent_v2"
# Only the source and mesh copies within the private trial are changed.
export SLURM_JOB_ID="$3"
python3 "$1" --base "$HOME/hpcc-fsi" --work "$2" --run
' bash "$FSI_REF_SRC" "$OUT" "$SLURM_JOB_ID"
echo "ALE_REFERENCE_8_WINDOW_SCRIPT_COMPLETED"
BATCH
job="$(sbatch --parsable -p cpu -N 1 -n 1 -c 12 --mem=24G -t 04:00:00 \
    -J fsi-ref-8w \
    --export="ALL,BASH_ENV=,ENV=,FSI_REF_SRC=$PIN,FSI_REF_SHA=$HASH" \
    -o "$BASE/ale-restart-reference-tests/test-%j.out" \
    -e "$BASE/ale-restart-reference-tests/test-%j.err" \
    "$SBATCH")"
echo "已提交独立ALE参考构形修复候选。"
echo "查看状态: squeue -u \"\$USER\" -n fsi-ref-8w"
echo "结果目录: $BASE/ale-restart-reference-tests/trial-$job"
echo "说明: 不修改原始0.0325s检查点，不启动长程FSI接力。"
