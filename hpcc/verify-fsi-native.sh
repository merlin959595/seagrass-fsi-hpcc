#!/usr/bin/env bash
# Verify transferred native binaries against the full-stack SIF on a compute node.
# No data mutation, no solver launch, no container download.
set -euo pipefail
BASE="$HOME/hpcc-fsi/seagrass-implicit-20261111"
IMAGE="$HOME/seagrass-fsi-ompi507-fullstack.sif"
LOGS="$HOME/hpcc-fsi/logs"
test -s "$IMAGE" || { echo "ERROR: no SIF at $IMAGE"; exit 1; }
test -s "$BASE/scripts/native/bin/ccx_preCICE_persistent_v2" || { echo "ERROR: custom CCX missing"; exit 1; }
test -s "$BASE/fsi-explicit-test/mesh-guard/lib/libseagrassExplicitMeshGuard.so" || { echo "ERROR: mesh guard missing"; exit 1; }
mkdir -p "$LOGS"
JOB="$HOME/hpcc-fsi/verify-fsi-native.sbatch"
cat > "$JOB" <<'SBATCH'
#!/usr/bin/env bash
set -euo pipefail
IMAGE="$HOME/seagrass-fsi-ompi507-fullstack.sif"
singularity exec --cleanenv "$IMAGE" bash -c '
  # OpenFOAM vendor environment cannot be sourced with nounset.
  set +eu
  export WM_MPLIB=SYSTEMOPENMPI
  source /usr/lib/openfoam/openfoam2512/etc/bashrc
  export PATH="/opt/precice-3.4.1-ompi5/bin:/opt/openmpi-5.0.7/bin:$PATH"
  export LD_LIBRARY_PATH="/opt/precice-3.4.1-ompi5/lib:/opt/precice-3.4.1-ompi5/lib64:/opt/openmpi-5.0.7/lib:/opt/openmpi-5.0.7/lib64:${LD_LIBRARY_PATH:-}"
  set -eo pipefail
  ROOT="$HOME/hpcc-fsi/seagrass-implicit-20261111"
  echo "===== VERSIONS ====="
  echo "OpenFOAM=$WM_PROJECT_VERSION"
  test "$WM_PROJECT_VERSION" = v2512
  mpirun --version | head -n 1
  precice-version
  echo "FOAM_LIBBIN=$FOAM_LIBBIN"
  echo "===== COMPLETE NATIVE DEPENDENCY AUDIT ====="
  files=(
    "$ROOT/scripts/native/bin/ccx_preCICE_persistent_v2"
    "$ROOT/scripts/native/lib/libseagrassReferenceRestart.so"
    "$ROOT/fsi-explicit-test/mesh-guard/lib/libseagrassExplicitMeshGuard.so"
  )
  for f in "${files[@]}"; do
    echo "CHECK $f"
    report="$(ldd -r "$f" 2>&1)" || { printf "%s\n" "$report"; echo "ABI_CHECK_FAILED"; exit 11; }
    printf "%s\n" "$report" | grep -E "lib(OpenFOAM|finiteVolume|meshTools|dynamicMesh|Pstream|precice|mpi)[.]so" || true
    if printf "%s\n" "$report" | grep -E "not found|undefined symbol"; then
      echo "ABI_CHECK_FAILED"; exit 12
    fi
  done
  echo "NATIVE_BINARY_ABI_PASS"
  echo "NOTE: FSI numerics, preCICE handshake and restart are not yet validated."
'
SBATCH
JOBID="$(sbatch --parsable -p cpu -N 1 -n 1 -c 2 --mem=4G -t 00:10:00 \
  -J fsi-native-abi \
  -o "$LOGS/fsi-native-abi-%j.out" -e "$LOGS/fsi-native-abi-%j.err" "$JOB")"
echo "JOBID=$JOBID"
echo "LOG=$LOGS/fsi-native-abi-$JOBID.out"
echo "ERR=$LOGS/fsi-native-abi-$JOBID.err"
