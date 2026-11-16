#!/usr/bin/env bash
# Run on a UM HPCC LOGIN node. Submits a short, compute-node-only Slurm job.
# Does not overwrite the original $HOME/seagrass-fsi.sif.
set -euo pipefail
BASE="${HOME}/hpcc-fsi"
LOGS="${BASE}/logs"
TARGET="${HOME}/seagrass-fsi-ompi507-candidate.sif"
IMAGE="docker://ghcr.io/merlin959595/seagrass-fsi-hpcc:ompi5.0.7-candidate"
mkdir -p "$LOGS"
if [[ -e "$TARGET" ]]; then
  echo "STOP: existing candidate SIF: $TARGET"
  echo "Inspect it first; this script will never overwrite it."
  exit 1
fi
command -v sbatch >/dev/null || { echo 'ERROR: sbatch not found'; exit 1; }
command -v singularity >/dev/null || { echo 'ERROR: singularity not found'; exit 1; }
SCRIPT="${BASE}/ompi507-pull-and-smoke.sbatch"
if [[ -e "$SCRIPT" ]]; then
  echo "STOP: batch script already exists: $SCRIPT"
  exit 1
fi
cat > "$SCRIPT" <<'SBATCH'
#!/usr/bin/env bash
set -euo pipefail
TARGET="$HOME/seagrass-fsi-ompi507-candidate.sif"
ORIGINAL="$HOME/seagrass-fsi.sif"
IMAGE="docker://ghcr.io/merlin959595/seagrass-fsi-hpcc:ompi5.0.7-candidate"
TEMP="$HOME/seagrass-fsi-ompi507-candidate.partial.sif"
test -s "$ORIGINAL" || { echo "STOP: original rollback SIF missing"; exit 1; }
test ! -e "$TARGET" || { echo "STOP: candidate exists"; exit 1; }
test ! -e "$TEMP" || { echo "STOP: temporary file already exists"; exit 1; }
trap 'rm -f "$TEMP"' EXIT
echo "===== HOST ====="
hostname
date -Is
echo "===== PULL TO TEMP SIF ====="
singularity pull "$TEMP" "$IMAGE"
singularity sif list "$TEMP" >/dev/null
mv -n "$TEMP" "$TARGET"
test -s "$TARGET" || { echo "ERROR: candidate SIF not created"; exit 1; }
echo "===== IMAGE FILES ====="
ls -lh "$ORIGINAL" "$TARGET"
sha256sum "$TARGET"
echo "===== CONTAINER MPI, FSI STACK AND LINK CHECK ====="
singularity exec --cleanenv "$TARGET" bash -lc '
set -euo pipefail
export WM_MPLIB=SYSTEMOPENMPI
source /usr/lib/openfoam/openfoam2512/etc/bashrc
export PATH="/opt/openmpi-5.0.7/bin:$PATH"
export LD_LIBRARY_PATH="/opt/openmpi-5.0.7/lib:/opt/openmpi-5.0.7/lib64:${LD_LIBRARY_PATH:-}"
echo "MPI:"
mpirun --version | head -n 1
command -v mpirun
test "$(command -v mpirun)" = /opt/openmpi-5.0.7/bin/mpirun
mpirun --version | head -n 1 | grep -F "5.0.7"
echo "preCICE:"
precice-version
pkg-config --modversion libprecice | grep -F "3.4.1"
echo "OpenFOAM:"
echo "$WM_PROJECT_VERSION"
test "$WM_PROJECT_VERSION" = v2512
command -v pimpleFoam
echo "CalculiX:"
command -v ccx_preCICE
echo "MPI two-rank real Init/Finalize:"
mpirun --oversubscribe --bind-to none -np 2 /usr/local/bin/ompi5-smoke | sort
echo "Check links for existing binaries:"
for f in "$(command -v pimpleFoam)" "$(command -v ccx_preCICE)" "$FOAM_LIBBIN/libpreciceAdapterFunctionObject.so"; do
  echo "Checking $f"
  test -s "$f"
  ldd -r "$f" > /tmp/check-links.txt 2>&1
  if grep -E "not found|undefined symbol" /tmp/check-links.txt; then
    echo "FAILED: unresolved dynamic links in $f"
    exit 12
  fi
done
ldd "$(command -v pimpleFoam)" | grep -F "/opt/openmpi-5.0.7/lib/libmpi.so"
echo "OMPI507_CONTAINER_SMOKE_PASS"
'
echo "===== RESULT ====="
echo "CONTAINER_PULL_AND_BASIC_SMOKE_PASS"
echo "NOTE: FSI and custom CalculiX/mesh guard compatibility NOT YET VERIFIED."
SBATCH
echo "Submitting NEW candidate container pull; original SIF is untouched."
sbatch --parsable -p cpu -N 1 -n 1 -c 4 --mem=8G -t 02:00:00 \
  -J fsi-ompi507 \
  --output="${LOGS}/ompi507-%j.out" --error="${LOGS}/ompi507-%j.err" \
  "$SCRIPT"
echo "Check: squeue -u \"$USER\""
echo "Logs: $LOGS/ompi507-<JOBID>.out"
