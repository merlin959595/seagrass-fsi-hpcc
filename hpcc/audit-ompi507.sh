#!/usr/bin/env bash
# Read-only ABI audit of existing Open MPI 5.0.7 SIF, run from a UM HPCC login node.
# No downloads or modifications of the SIF, no production solver execution.
set -euo pipefail
SIF="$HOME/seagrass-fsi-ompi507-candidate.sif"
LOGS="$HOME/hpcc-fsi/logs"
EXPECTED_SHA=c85973d523219a55e7c855c264ef40fe05203b50222611bb936264f199a3ee92
test -s "$SIF" || { echo "STOP: candidate SIF missing"; exit 1; }
printf '%s  %s\n' "$EXPECTED_SHA" "$SIF" | sha256sum -c -
mkdir -p "$LOGS"
BATCH="$HOME/hpcc-fsi/audit-ompi507.sbatch"
cat > "$BATCH" <<'SBATCH'
#!/usr/bin/env bash
set -euo pipefail
IMAGE="$HOME/seagrass-fsi-ompi507-candidate.sif"
echo "==== COMPUTE NODE ===="
hostname
date -Is
echo "==== LINK AUDIT (DOES NOT EXECUTE THE SOLVER) ===="
singularity exec --cleanenv "$IMAGE" bash -c '
  # The vendor OpenFOAM bashrc probes unset variables: never source under nounset.
  set +eu
  export WM_MPLIB=SYSTEMOPENMPI
  source /usr/lib/openfoam/openfoam2512/etc/bashrc
  export PATH="/opt/openmpi-5.0.7/bin:$PATH"
  export LD_LIBRARY_PATH="/opt/openmpi-5.0.7/lib:/opt/openmpi-5.0.7/lib64:${LD_LIBRARY_PATH:-}"
  echo "== MPI runtime and library paths =="
  command -v mpirun
  mpirun --version | head -n 1
  ldconfig -p | grep -E "libmpi(_cxx)?\\.so|libprecice\\.so" || true
  echo "== Application NEEDED libraries and resolved MPI dependencies =="
  for program in precice-version pimpleFoam ccx_preCICE; do
    file="$(command -v "$program")"
    echo "----- $program: $file -----"
    readelf -d "$file" 2>/dev/null | grep -E "NEEDED.*(mpi|precice|petsc)" || true
    ldd -r "$file" 2>&1 | grep -E "(libmpi|libprecice|libpetsc|not found|undefined symbol)" || true
  done
  echo "== OpenFOAM adapter dependencies =="
  adapter="${FOAM_LIBBIN:-}/libpreciceAdapterFunctionObject.so"
  if [ -s "$adapter" ]; then
    echo "$adapter"
    readelf -d "$adapter" 2>/dev/null | grep -E "NEEDED.*(mpi|precice|petsc)" || true
    ldd -r "$adapter" 2>&1 | grep -E "(libmpi|libprecice|libpetsc|not found|undefined symbol)" || true
  else
    echo "MISSING adapter at $adapter"
  fi
  echo "== MPI C++ legacy dependency =="
  cxx="$(ldconfig -p | awk "/libmpi_cxx[.]so[.]40 / {print \\$NF; exit}")"
  if [ -n "$cxx" ]; then
    echo "$cxx"
    readelf -d "$cxx" 2>/dev/null | grep -E "NEEDED.*mpi" || true
    ldd -r "$cxx" 2>&1 | grep -E "(libmpi|not found|undefined symbol)" || true
  fi
  echo "== Runtime command (may fail; shown for diagnosis) =="
  precice-version 2>&1
  echo "precice-version exit: $?"
  echo "== DIAGNOSTIC_COMPLETE (not a pass) =="
'
SBATCH
JOBID="$(sbatch --parsable -p cpu -N 1 -n 1 -c 2 --mem=4G -t 00:10:00 -J ompi507-audit     -o "$LOGS/ompi507-audit-%j.out" -e "$LOGS/ompi507-audit-%j.err" "$BATCH")"
echo "Audit submitted: $JOBID"
echo "Read: $LOGS/ompi507-audit-$JOBID.out"
echo "Errors: $LOGS/ompi507-audit-$JOBID.err"
