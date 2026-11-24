#!/usr/bin/env bash
# Explicit Python interpreter: /bin/bash run-96764-container.sh <script.py> --run-job
# or: /bin/bash run-96764-container.sh <script.py> --run-one <config.json>
set -Eeuo pipefail
if (( $# < 2 )); then
    echo "NATIVE_LAUNCHER_MISSING_PYTHON_SCRIPT_AND_ACTION" >&2
    exit 64
fi
PY_SCRIPT="$1"
ACTION="$2"
shift 2
case "$ACTION" in
    --run-job)
        (( $# == 0 )) || { echo "BAD_REPAIR_JOB_ARGUMENTS" >&2; exit 64; }
        ;;
    --run-one)
        (( $# == 1 )) || { echo "BAD_PRODUCTION_JOB_ARGUMENTS" >&2; exit 64; }
        ;;
    *)
        echo "UNEXPECTED_NATIVE_LAUNCHER_ACTION" >&2
        exit 64
        ;;
esac
[[ -s "$PY_SCRIPT" ]] || { echo "PYTHON_SOURCE_MISSING" >&2; exit 65; }
[[ -n "${SLURM_JOB_ID:-}" ]] || { echo "SLURM_JOB_ID_NOT_IN_CONTAINER" >&2; exit 65; }
[[ -n "${USER:-}" ]] || { echo "USER_NOT_IN_CONTAINER" >&2; exit 65; }
[[ -n "${HOME:-}" ]] || { echo "HOME_NOT_IN_CONTAINER" >&2; exit 65; }
[[ -x /usr/bin/python3 ]] || { echo "SYSTEM_PYTHON3_MISSING" >&2; exit 65; }
unset BASH_ENV ENV
set +eu
export WM_MPLIB=SYSTEMOPENMPI
source /usr/lib/openfoam/openfoam2512/etc/bashrc
source_rc=$?
set -eu
if (( source_rc != 0 )); then
    echo "OPENFOAM_BASHRC_FAILED rc=$source_rc" >&2
    exit 66
fi
export PATH="/opt/precice-3.4.1-ompi5/bin:/opt/openmpi-5.0.7/bin:$PATH"
export LD_LIBRARY_PATH="/opt/scotch-compat/lib:/opt/precice-3.4.1-ompi5/lib:/opt/precice-3.4.1-ompi5/lib64:/opt/openmpi-5.0.7/lib:/opt/openmpi-5.0.7/lib64:${LD_LIBRARY_PATH:-}"
export PKG_CONFIG_PATH="/opt/precice-3.4.1-ompi5/lib/pkgconfig:/opt/precice-3.4.1-ompi5/lib64/pkgconfig:${PKG_CONFIG_PATH:-}"
export OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ROOT="$HOME/hpcc-fsi/seagrass-implicit-20261111"
export LD_LIBRARY_PATH="$ROOT/scripts/native/lib:$ROOT/fsi-explicit-test/mesh-guard/lib:$LD_LIBRARY_PATH"
[[ "$WM_PROJECT_VERSION" == v2512 ]] || { echo "WRONG_OPENFOAM_VERSION" >&2; exit 67; }
[[ "$(command -v mpirun)" == /opt/openmpi-5.0.7/bin/mpirun ]] || { echo "WRONG_MPI_VERSION" >&2; exit 67; }
[[ -x "$ROOT/scripts/native/bin/ccx_preCICE_persistent_v2" ]] || { echo "NATIVE_SOLID_SOLVER_MISSING" >&2; exit 67; }
echo "NATIVE_FSI_PYTHON_DISPATCH python=/usr/bin/python3 action=$ACTION script=$PY_SCRIPT job=$SLURM_JOB_ID" >&2
exec /usr/bin/python3 "$PY_SCRIPT" "$ACTION" "$@"
