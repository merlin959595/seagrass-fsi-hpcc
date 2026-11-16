#!/usr/bin/env bash
# G2 targeted solver acceleration feasibility: no root, rebuild, Slurm, solver or input mutation.
set -euo pipefail
BASE="$HOME/hpcc-fsi"
ROOT="$BASE/seagrass-implicit-20261111"
CCX="$ROOT/scripts/native/bin/ccx_preCICE_persistent_v2"
OUT="$BASE/g2-solver-backend-feasibility-$(date +%Y%m%d-%H%M%S).txt"
if [[ ! -f "$CCX" ]]; then
  echo "Missing custom CalculiX executable: $CCX" >&2
  exit 2
fi
{
  echo "G2_SOLVER_BACKEND_READONLY_BEGIN"
  date -Is
  echo "===== Current custom structural solver ====="
  sha256sum "$CCX"
  file "$CCX"
  echo "===== Runtime shared libraries ====="
  ldd "$CCX" 2>&1 || true
  echo "===== Solver and build symbols ====="
  if command -v nm >/dev/null 2>&1; then
    nm -D "$CCX" 2>/dev/null | grep -Ei 'pastix|pardiso|spooles|mumps' | head -n 45 || true
  fi
  echo "===== Available toolchain ====="
  for cmd in gcc gfortran g++ make cmake mpicc mpifort nvcc nvidia-smi pkg-config; do
    if command -v "$cmd" >/dev/null 2>&1; then
      echo "$cmd $(command -v "$cmd")"
    else
      echo "$cmd UNAVAILABLE"
    fi
  done
  echo "===== Installed candidate solver libraries ====="
  if command -v ldconfig >/dev/null 2>&1; then
    ldconfig -p 2>/dev/null | grep -Ei 'pastix|spooles|mumps|pardiso|mkl|scotch|metis' | head -n 100 || true
  fi
  echo "===== Existing solver/adapter source dirs ====="
  for top in "$ROOT" "$HOME"; do
    find "$top" -maxdepth 4 -type d \( \
       -iname '*pastix*' -o -iname '*spooles*' -o \
       -iname '*calculix*' -o -iname '*ccx_2.20*' -o \
       -iname '*mumps*' \) -print 2>/dev/null | head -n 70 || true
  done
  echo "===== Actual current CalculiX SOLVER directive ====="
  grep -nEi '^[[:space:]]*\*SOLVER|^[[:space:]]*\*DYNAMIC' \
    "$BASE/implicit-pilot-002-8mpi-timefix-87186/production/runs/hpcc-implicit-002/solid/seagrass.inp" || true
  echo "G2_BACKEND_FEASIBILITY_AUDIT_COMPLETE"
  echo "NO_BUILD_NO_SIMULATION_NO_CHANGE"
} | tee "$OUT"
echo "REPORT=$OUT"
