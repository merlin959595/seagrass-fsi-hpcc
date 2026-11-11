#!/usr/bin/env bash
# Verify the EXISTING downloaded Open MPI 5.0.7 SIF on an allocated UM HPCC compute node.
# Run on LOGIN node: bash hpcc/validate-ompi507.sh
# This does NOT download images, overwrite SIFs, or launch a long FSI solve.
set -euo pipefail
SIF="$HOME/seagrass-fsi-ompi507-candidate.sif"
EXPECTED_SHA="c85973d523219a55e7c855c264ef40fe05203b50222611bb936264f199a3ee92"
LOGS="$HOME/hpcc-fsi/logs"
JOBDIR="$HOME/hpcc-fsi/ompi507-verification"
mkdir -p "$LOGS" "$JOBDIR"
test -s "$SIF" || { echo "STOP: downloaded candidate missing: $SIF"; exit 1; }
printf '%s  %s\n' "$EXPECTED_SHA" "$SIF" | sha256sum --check -
test -s "$HOME/seagrass-fsi.sif" || { echo "STOP: original rollback image missing"; exit 1; }
JOB="$JOBDIR/validate.sbatch"
cat > "$JOB" <<'SBATCH'
#!/usr/bin/env bash
set -euo pipefail
IMAGE="$HOME/seagrass-fsi-ompi507-candidate.sif"
EXPECTED_SHA="c85973d523219a55e7c855c264ef40fe05203b50222611bb936264f199a3ee92"
printf '%s  %s\n' "$EXPECTED_SHA" "$IMAGE" | sha256sum --check -
echo "===== ALLOCATED NODE ====="
hostname
date -Is
echo "===== IN-CONTAINER BASELINE ====="
singularity exec --cleanenv "$IMAGE" /opt/openmpi-5.0.7/bin/mpirun --version
echo "===== IN-CONTAINER OPENFOAM/MPI TEST ====="
singularity exec --cleanenv "$IMAGE" bash -c '
# OpenFOAM vendor bashrc must NOT be sourced with nounset; also avoid errexit
# while optional feature probes run. Validate the resulting environment instead.
set +eu
export WM_MPLIB=SYSTEMOPENMPI
source /usr/lib/openfoam/openfoam2512/etc/bashrc
set -eo pipefail
export PATH="/opt/openmpi-5.0.7/bin:$PATH"
export LD_LIBRARY_PATH="/opt/openmpi-5.0.7/lib:/opt/openmpi-5.0.7/lib64:${LD_LIBRARY_PATH:-}"
echo "OpenFOAM version: ${WM_PROJECT_VERSION:-unset}"
test "${WM_PROJECT_VERSION:-}" = v2512
echo "WM_MPLIB: ${WM_MPLIB:-unset}"
test "${WM_MPLIB:-}" = SYSTEMOPENMPI
echo "MPI launcher: $(command -v mpirun)"
test "$(command -v mpirun)" = /opt/openmpi-5.0.7/bin/mpirun
mpirun --version | head -n 1
command -v pimpleFoam
command -v blockMesh
command -v checkMesh
command -v ccx_preCICE
precice-version
pkg-config --modversion libprecice | grep -F "3.4.1"
echo "===== TRUE TWO-RANK MPI ====="
out="$(mpirun --oversubscribe --bind-to none -np 2 /usr/local/bin/ompi5-smoke)"
printf "%s\n" "$out" | sort
grep -q "FSI_MPI_SMOKE_RANK=0/2" <<< "$out"
grep -q "FSI_MPI_SMOKE_RANK=1/2" <<< "$out"
echo "===== LINK RESOLUTION ====="
test -n "${FOAM_LIBBIN:-}"
for f in "$(command -v pimpleFoam)" "$(command -v ccx_preCICE)" "$FOAM_LIBBIN/libpreciceAdapterFunctionObject.so"; do
  echo "CHECK: $f"
  test -s "$f"
  output="$(ldd -r "$f" 2>&1)" || { echo "$output"; exit 12; }
  if grep -E "not found|undefined symbol" <<< "$output"; then
      echo "FAILED unresolved dynamic library for $f"; exit 13
  fi
done
echo "===== FOAM MPI RESOLUTION ====="
ldd "$(command -v pimpleFoam)" | grep -F "/opt/openmpi-5.0.7/lib/libmpi.so"
echo "OMPI507_CONTAINER_SMOKE_PASS"
'
echo "CONTAINER_BASIC_VERIFICATION_PASS"
echo "NOTE: custom persistent CalculiX and mesh guard still require separate compatibility and real coupled-FSI tests."
SBATCH
echo "Submitting short non-destructive compute-node verification."
sbatch --parsable -p cpu -N 1 -n 1 -c 4 --mem=8G -t 00:20:00 -J fsi-ompi507-verify \
    -o "$LOGS/ompi507-verify-%j.out" -e "$LOGS/ompi507-verify-%j.err" "$JOB"
echo "Log files: $LOGS/ompi507-verify-<JOBID>.out and .err"
