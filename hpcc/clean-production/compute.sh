#!/usr/bin/env bash
# Clean Slurm stage: no mutable sources/old failed dirs, no direct SSH access.
set -euo pipefail
CHAIN="$HOME/hpcc-fsi/seagrass-fsi-mainline"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
DRIVER="$CHAIN/bin/segment.py"
LABEL="$1"
INDEX="$2"
PARENT="$3"
WORK="$CHAIN/segment-$LABEL"
[[ "$LABEL" =~ ^[A-L]$ ]] || { echo "Invalid stage label" >&2; exit 10; }
[[ "$INDEX" =~ ^([1-9]|1[0-2])$ ]] || { echo "Invalid stage index" >&2; exit 11; }
[[ "$PARENT" =~ ^[0-9]+$ ]] || { echo "Invalid dependency identifier" >&2; exit 12; }
test -s "$SIF"
test -s "$DRIVER"
test ! -e "$WORK" || { echo "Refusing existing segment directory: $WORK" >&2; exit 13; }
echo "CLEAN_FSI_STAGE_START segment=$LABEL host=$(hostname) at=$(date -Is)"
# Prevent inherited Bash startup script from accidentally sourcing Python.
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
test -x "$ROOT/scripts/native/bin/ccx_preCICE_persistent_v2"
test -f "$ROOT/scripts/native/lib/libseagrassReferenceRestart.so"
test -x "$(command -v pimpleFoam)"
test -x "$(command -v precice-config-validate)"
test -f /usr/bin/time
LOGDIR="$2/logs"
{
  echo "STAGE=$3 TIME=$(date -Is)"
  echo "MPI=$(command -v mpirun)"
  echo "FLUID=$(command -v pimpleFoam)"
  echo "PRECICE=$(command -v precice-config-validate)"
  echo "CCX=$ROOT/scripts/native/bin/ccx_preCICE_persistent_v2"
  echo "LD_LIBRARY_PATH=$LD_LIBRARY_PATH"
} > "$LOGDIR/runtime-$3.txt"
for exe in "$(command -v pimpleFoam)" "$ROOT/scripts/native/bin/ccx_preCICE_persistent_v2"; do
  ldd "$exe" >> "$LOGDIR/loader-$3.txt" 2>&1
done
if grep -qi "not found" "$LOGDIR/loader-$3.txt"; then
  echo "FATAL: unresolved OpenFOAM/CalculiX runtime library" >&2
  cat "$LOGDIR/loader-$3.txt" >&2
  exit 127
fi
# Exercises actual MPI and loader without touching production physical time.
if ! mpirun --oversubscribe -np 2 --bind-to none pimpleFoam -help \
       >"$LOGDIR/mpi-preflight-$3.log" 2>&1; then
  echo "FATAL: pimpleFoam failed to launch under MPI in container" >&2
  tail -n 80 "$LOGDIR/mpi-preflight-$3.log" >&2
  exit 127
fi
echo "MPI_FLUID_LOADER_PREFLIGHT_PASS stage=$3" >&2
export SLURM_JOB_ID="$7"
python3 "$1" --base "$HOME/hpcc-fsi" --chain-root "$2" \
  --stage "$4" --previous-job "$5" --work "$6" \
  --max-windows 960 --run --timeout-seconds 237600
' bash "$DRIVER" "$CHAIN" "$LABEL" "$INDEX" "$PARENT" "$WORK" "$SLURM_JOB_ID"
echo "CLEAN_FSI_STAGE_SCRIPT_EXIT=0 segment=$LABEL at=$(date -Is)"
