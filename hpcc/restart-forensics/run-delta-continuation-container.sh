#!/usr/bin/env bash
# Runs on a Slurm compute node INSIDE the validated OMPI5 fullstack SIF.
set -euo pipefail
SCRIPT="$1"
CORE="$2"
PARENT="$3"
JOB="$4"
WORK="$5"
WINDOWS="$6"
PREV="$7"
# Do not leak Python/bash paths into the OpenFOAM etc/bashrc.
set --
set +eu
export WM_MPLIB=SYSTEMOPENMPI
source /usr/lib/openfoam/openfoam2512/etc/bashrc
export PATH="/opt/precice-3.4.1-ompi5/bin:/opt/openmpi-5.0.7/bin:$PATH"
export LD_LIBRARY_PATH="/opt/scotch-compat/lib:/opt/precice-3.4.1-ompi5/lib:/opt/precice-3.4.1-ompi5/lib64:/opt/openmpi-5.0.7/lib:/opt/openmpi-5.0.7/lib64:$LD_LIBRARY_PATH"
export PKG_CONFIG_PATH="/opt/precice-3.4.1-ompi5/lib/pkgconfig:/opt/precice-3.4.1-ompi5/lib64/pkgconfig:$PKG_CONFIG_PATH"
export OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ROOT="$HOME/hpcc-fsi/seagrass-implicit-20261111"
export LD_LIBRARY_PATH="$ROOT/scripts/native/lib:$ROOT/fsi-explicit-test/mesh-guard/lib:$LD_LIBRARY_PATH"
set -euo pipefail
test "$WM_PROJECT_VERSION" = "v2512"
test "$(command -v mpirun)" = "/opt/openmpi-5.0.7/bin/mpirun"
test -x "$ROOT/scripts/native/bin/ccx_preCICE_persistent_v2"
test -f "$ROOT/scripts/native/lib/libseagrassReferenceRestart.so"
test -n "$JOB"
export SLURM_JOB_ID="$JOB"
python3 "$SCRIPT" --base "$HOME/hpcc-fsi" --core "$CORE" \
  --source-work "$PARENT" --source-job "$PREV" \
  --windows "$WINDOWS" --work "$WORK" --run
