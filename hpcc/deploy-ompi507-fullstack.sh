#!/usr/bin/env bash
# Pull and validate the source-rebuilt Open MPI 5 / preCICE 3.4.1 image.
# Execute once on UM HPCC login node. Slurm runs all heavy work on a compute node.
set -euo pipefail
BASE="$HOME/hpcc-fsi"
LOGDIR="$BASE/logs"
SIF="$HOME/seagrass-fsi-ompi507-fullstack.sif"
OLD="$HOME/seagrass-fsi.sif"
JOBFILE="$BASE/ompi507-fullstack.sbatch"
mkdir -p "$LOGDIR"
test -s "$OLD" || { echo "ERROR: old recovery SIF missing: $OLD"; exit 1; }
if [ -e "$SIF" ]; then
  echo "STOP: new SIF already exists ($SIF); do not overwrite without audit."
  exit 1
fi
cat > "$JOBFILE" <<'BATCH'
#!/usr/bin/env bash
set -euo pipefail
TARGET="$HOME/seagrass-fsi-ompi507-fullstack.sif"
TEMP="$HOME/seagrass-fsi-ompi507-fullstack.partial.sif"
IMAGE="docker://ghcr.io/merlin959595/seagrass-fsi-hpcc:ompi5.0.7-precice3.4.1-abi-candidate"
test ! -e "$TARGET" || { echo "STOP: target exists"; exit 1; }
test ! -e "$TEMP" || { echo "STOP: leftover temp SIF"; exit 1; }
test -s "$HOME/seagrass-fsi.sif" || { echo "STOP: recovery SIF missing"; exit 1; }
trap 'rm -f "$TEMP"' EXIT
echo "==== COMPUTE NODE ===="
hostname; date -Is
echo "==== PULL NEW FULLSTACK IMAGE ===="
singularity pull "$TEMP" "$IMAGE"
singularity sif list "$TEMP"
mv "$TEMP" "$TARGET"
sha256sum "$TARGET"
echo "==== VERIFY NEW FSI STACK ===="
singularity exec --cleanenv "$TARGET" bash -c '
  # The vendor OpenFOAM bashrc needs unset variables to be allowed.
  set +eu
  export WM_MPLIB=SYSTEMOPENMPI
  source /usr/lib/openfoam/openfoam2512/etc/bashrc
  export PATH="/opt/precice-3.4.1-ompi5/bin:/opt/openmpi-5.0.7/bin:$PATH"
  export LD_LIBRARY_PATH="/opt/precice-3.4.1-ompi5/lib:/opt/precice-3.4.1-ompi5/lib64:/opt/openmpi-5.0.7/lib:/opt/openmpi-5.0.7/lib64:${LD_LIBRARY_PATH:-}"
  export PKG_CONFIG_PATH="/opt/precice-3.4.1-ompi5/lib/pkgconfig:/opt/precice-3.4.1-ompi5/lib64/pkgconfig:${PKG_CONFIG_PATH:-}"
  set -eo pipefail

  echo "==== MPI/OF/PRECICE ===="
  mpirun --version | head -n 1
  test "$(command -v mpirun)" = "/opt/openmpi-5.0.7/bin/mpirun"
  test "${WM_PROJECT_VERSION:-}" = "v2512"
  test "$(command -v precice-version)" = "/opt/precice-3.4.1-ompi5/bin/precice-version"
  precice-version
  pkg-config --modversion libprecice | grep -Fx "3.4.1"
  command -v pimpleFoam
  command -v ccx_preCICE
  test -s "$FOAM_LIBBIN/libpreciceAdapterFunctionObject.so"

  echo "==== REAL 2-RANK MPI TEST ===="
  output="$(mpirun --oversubscribe --bind-to none -np 2 /usr/local/bin/ompi5-smoke)"
  printf "%s\n" "$output" | sort
  grep -Fq "FSI_MPI_SMOKE_RANK=0/2" <<< "$output"
  grep -Fq "FSI_MPI_SMOKE_RANK=1/2" <<< "$output"

  echo "==== ABI RESOLUTION ===="
  LIBPRECICE="$(find /opt/precice-3.4.1-ompi5 -name libprecice.so.3 -print -quit)"
  test -s "$LIBPRECICE"
  for f in "$LIBPRECICE" "$(command -v precice-version)" "$(command -v ccx_preCICE)" "$(command -v pimpleFoam)" "$FOAM_LIBBIN/libpreciceAdapterFunctionObject.so"; do
    echo "Checking: $f"
    report="$(ldd -r "$f" 2>&1)" || { echo "$report"; exit 11; }
    if echo "$report" | grep -E "undefined symbol|not found|libmpi_cxx|libpetsc_real|libtrilinos"; then
      echo "FAIL: legacy MPI/PETSc dependency or unresolved symbols"
      exit 12
    fi
  done
  echo "NEW_FULLSTACK_LIBRARY_AND_MPI_SMOKE_PASS"
'
echo "==== COMPLETED ===="
echo "FULLSTACK_DEPLOY_VALIDATION_PASS"
echo "Further gates: custom CalculiX, ALE guard, real implicit FSI coupling."
BATCH
echo "Submitting fresh SIF pull + ABI audit; original SIF is unchanged."
JOBID="$(sbatch --parsable -p cpu -N 1 -n 1 -c 4 --mem=8G -t 02:00:00 \
  -J ompi507-fullstack \
  -o "$LOGDIR/ompi507-fullstack-%j.out" \
  -e "$LOGDIR/ompi507-fullstack-%j.err" \
  "$JOBFILE")"
echo "Submitted JOBID: $JOBID"
echo "Outputs: $LOGDIR/ompi507-fullstack-$JOBID.out"
echo "Errors:  $LOGDIR/ompi507-fullstack-$JOBID.err"
