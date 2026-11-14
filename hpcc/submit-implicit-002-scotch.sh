#!/usr/bin/env bash
# Deploy Scotch-fixed SIF, then run real one-stage 0.02s implicit FSI.
# Existing SIFs and failed tests are never overwritten.
set -euo pipefail
ROOT="$HOME/hpcc-fsi/seagrass-implicit-20261111"
SIF="$HOME/seagrass-fsi-ompi507-scotch.sif"
LOGS="$HOME/hpcc-fsi/logs"
OUT="$HOME/hpcc-fsi/implicit-pilot-002-8mpi-scotch-20261111"
BATCH="$HOME/hpcc-fsi/implicit-pilot-002-8mpi-scotch.sbatch"
test -s "$ROOT/hpcc/implicit-002-scotch-driver.py"
test -s "$ROOT/fsi-implicit-production/run_production.py"
test -s "$HOME/seagrass-fsi-ompi507-fullstack.sif"
test ! -e "$OUT" || { echo "STOP: $OUT exists"; exit 1; }
mkdir -p "$LOGS"
cat > "$BATCH" <<'SBATCH'
#!/usr/bin/env bash
set -euo pipefail
SIF="$HOME/seagrass-fsi-ompi507-scotch.sif"
TMP="$HOME/seagrass-fsi-ompi507-scotch.partial.sif"
IMG="docker://ghcr.io/merlin959595/seagrass-fsi-hpcc:ompi5.0.7-precice3.4.1-scotch-candidate"
OUT="$HOME/hpcc-fsi/implicit-pilot-002-8mpi-scotch-20261111"
test ! -e "$OUT" || { echo "STOP: previous pilot output exists"; exit 1; }
hostname; date -Is
if [ ! -s "$SIF" ]; then
  test ! -e "$SIF" && test ! -e "$TMP"
  trap 'rm -f "$TMP"' EXIT
  singularity pull "$TMP" "$IMG"
  singularity sif list "$TMP" >/dev/null
  mv "$TMP" "$SIF"
  trap - EXIT
fi
sha256sum "$SIF"
singularity exec --cleanenv "$SIF" bash -c '
set +eu
export WM_MPLIB=SYSTEMOPENMPI
source /usr/lib/openfoam/openfoam2512/etc/bashrc
export PATH="/opt/precice-3.4.1-ompi5/bin:/opt/openmpi-5.0.7/bin:$PATH"
export LD_LIBRARY_PATH="/opt/scotch-compat/lib:/opt/precice-3.4.1-ompi5/lib:/opt/precice-3.4.1-ompi5/lib64:/opt/openmpi-5.0.7/lib:/opt/openmpi-5.0.7/lib64:${LD_LIBRARY_PATH:-}"
export PKG_CONFIG_PATH="/opt/precice-3.4.1-ompi5/lib/pkgconfig:/opt/precice-3.4.1-ompi5/lib64/pkgconfig:${PKG_CONFIG_PATH:-}"
export LD_LIBRARY_PATH="$HOME/hpcc-fsi/seagrass-implicit-20261111/scripts/native/lib:$HOME/hpcc-fsi/seagrass-implicit-20261111/fsi-explicit-test/mesh-guard/lib:$LD_LIBRARY_PATH"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
set -eo pipefail
echo "=== ENVIRONMENT ==="
mpirun --version | head -n 1
precice-version
test "$WM_PROJECT_VERSION" = v2512
echo "=== DECOMPOSEPAR ABI ==="
report="$(ldd -r "$(command -v decomposePar)" 2>&1)" || { echo "$report"; exit 7; }
if grep -E "not found|undefined symbol|libmpi_cxx" <<< "$report"; then
  echo "DECOMPOSEPAR_ABI_FAILED"; exit 8
fi
echo "DECOMPOSEPAR_ABI_PASS"
python3 "$HOME/hpcc-fsi/seagrass-implicit-20261111/hpcc/implicit-002-scotch-driver.py" \
  --root "$HOME/hpcc-fsi/seagrass-implicit-20261111" \
  --work "$HOME/hpcc-fsi/implicit-pilot-002-8mpi-scotch-20261111" --ranks 8
'
SBATCH
JOBID="$(sbatch --parsable -p cpu -N 1 -n 1 -c 12 --mem=24G -t 12:00:00 \
  -J fsi-002-scotch -o "$LOGS/fsi-002-scotch-%j.out" \
  -e "$LOGS/fsi-002-scotch-%j.err" "$BATCH")"
echo "JOBID=$JOBID"
echo "OUT=$LOGS/fsi-002-scotch-$JOBID.out"
echo "ERR=$LOGS/fsi-002-scotch-$JOBID.err"
echo "STATE=$OUT/STATE.json"
