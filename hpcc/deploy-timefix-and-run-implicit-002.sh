#!/usr/bin/env bash
# One compute-node Slurm job: pull Scotch-fixed SIF and run isolated 0.02s implicit FSI.
# Does not overwrite the verified fullstack SIF, old SIF, or failed job 87098 records.
set -euo pipefail
ROOT="$HOME/hpcc-fsi/seagrass-implicit-20261111"
BASE="$HOME/hpcc-fsi"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
PILOT="$BASE/implicit-pilot-002-8mpi-timefix-20261111"
LOGS="$BASE/logs"
BATCH="$BASE/ompi507-timefix-fsi-002.sbatch"
test -s "$ROOT/hpcc/implicit-002-driver.py" || { echo "STOP missing pilot driver"; exit 1; }
test -s "$ROOT/fsi-implicit-production/run_production.py" || { echo "STOP missing input controller"; exit 1; }
test -s "$ROOT/scripts/native/bin/ccx_preCICE_persistent_v2" || { echo "STOP missing custom CCX"; exit 1; }
test -s "$HOME/seagrass-fsi-ompi507-fullstack.sif" || { echo "STOP missing former SIF"; exit 1; }
test ! -e "$SIF" || { echo "STOP candidate SIF already exists; inspect before reuse: $SIF"; exit 1; }
test ! -e "$SIF.partial.sif" || { echo "STOP incomplete prior pull"; exit 1; }
test ! -e "$PILOT" || { echo "STOP pilot already exists; will not overwrite: $PILOT"; exit 1; }
mkdir -p "$LOGS"
cat > "$BATCH" <<'SBATCH'
#!/usr/bin/env bash
set -euo pipefail
ROOT="$HOME/hpcc-fsi/seagrass-implicit-20261111"
BASE="$HOME/hpcc-fsi"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
TEMP="$SIF.partial.sif"
PILOT="$BASE/implicit-pilot-002-8mpi-timefix-20261111"
IMAGE="docker://ghcr.io/merlin959595/seagrass-fsi-hpcc:ompi5.0.7-precice3.4.1-scotch-time-candidate"
diagnose() {
  rc=$?
  if [[ $rc -ne 0 ]]; then
    echo "PILOT_FAILED_EXIT=$rc" >&2
    for f in "$PILOT/preflight/STATE.json" "$PILOT/production/STATE.json"; do
      [[ ! -f "$f" ]] || { echo "STATE $f"; tail -n 40 "$f"; } >&2
    done
    for f in "$PILOT/preflight/runs/hpcc-implicit-002/decompose.log" \
             "$PILOT/production/runs/hpcc-implicit-002/decompose.log" \
             "$PILOT/production/runs/hpcc-implicit-002/fluid.log" \
             "$PILOT/production/runs/hpcc-implicit-002/solid.log"; do
      [[ ! -f "$f" ]] || { echo "LOG $f"; tail -n 50 "$f"; } >&2
    done
  fi
}
trap diagnose EXIT
test ! -e "$SIF" && test ! -e "$TEMP" && test ! -e "$PILOT"
echo "===== ALLOCATED NODE ====="
hostname; date -Is
echo "JOB=$SLURM_JOB_ID CPU_PER_TASK=$SLURM_CPUS_PER_TASK"
echo "===== DOWNLOAD AND VERIFY NEW SCOTCH SIF ====="
singularity pull "$TEMP" "$IMAGE"
singularity sif list "$TEMP"
mv "$TEMP" "$SIF"
sha256sum "$SIF" | tee "$SIF.sha256"
echo "===== OPENFOAM DEPENDENCY, MESH PREFLIGHT, AND REAL FSI ====="
singularity exec --cleanenv "$SIF" bash -c '
set +eu
export WM_MPLIB=SYSTEMOPENMPI
source /usr/lib/openfoam/openfoam2512/etc/bashrc
export PATH="/opt/precice-3.4.1-ompi5/bin:/opt/openmpi-5.0.7/bin:$PATH"
export LD_LIBRARY_PATH="/opt/scotch-compat/lib:/opt/precice-3.4.1-ompi5/lib:/opt/precice-3.4.1-ompi5/lib64:/opt/openmpi-5.0.7/lib:/opt/openmpi-5.0.7/lib64:${LD_LIBRARY_PATH:-}"
export PKG_CONFIG_PATH="/opt/precice-3.4.1-ompi5/lib/pkgconfig:/opt/precice-3.4.1-ompi5/lib64/pkgconfig:${PKG_CONFIG_PATH:-}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
ROOT="$HOME/hpcc-fsi/seagrass-implicit-20261111"
export LD_LIBRARY_PATH="$ROOT/scripts/native/lib:$ROOT/fsi-explicit-test/mesh-guard/lib:$LD_LIBRARY_PATH"
set -eo pipefail
test "$WM_PROJECT_VERSION" = "v2512"
test "$(command -v mpirun)" = "/opt/openmpi-5.0.7/bin/mpirun"
mpirun --version | head -n 1
precice-version
report="$(ldd -r "$(command -v decomposePar)" 2>&1)" || { printf "%s\n" "$report"; exit 10; }
printf "%s\n" "$report" | grep -E "libscotch|libmpi" || true
if printf "%s\n" "$report" | grep -E "not found|undefined symbol|libmpi_cxx"; then
  echo "DECOMPOSEPAR_ABI_FAIL"; exit 11
fi
echo "DECOMPOSEPAR_ABI_PASS"
test -x /usr/bin/time || { echo "GNU_TIME_MISSING"; exit 13; }
/usr/bin/time -v /bin/true 2>&1 | grep -F "Command being timed"
echo "GNU_TIME_RUNTIME_PASS"
echo "===== FROZEN MESH, XML, AND 8 MPI PREFLIGHT ====="
python3 "$ROOT/hpcc/implicit-002-driver.py" \
 --root "$ROOT" --work "$HOME/hpcc-fsi/implicit-pilot-002-8mpi-timefix-20261111/preflight" \
 --mode preflight --ranks 8
echo "===== REAL 0.02s IMPLICIT TWO-WAY FSI ====="
python3 "$ROOT/hpcc/implicit-002-driver.py" \
 --root "$ROOT" --work "$HOME/hpcc-fsi/implicit-pilot-002-8mpi-timefix-20261111/production" \
 --mode run --ranks 8
echo "HPCC_IMPLICIT_0P02_ACCEPTED_160_WINDOWS_PASS"
'
echo "===== NEW TIME-FIXED PILOT PASSED ====="
SBATCH
echo "Submitting GNU-time-fixed 8-MPI + 2 CCX thread real 0.02s pilot."
JOBID="$(sbatch --parsable -p cpu -N 1 -n 1 -c 12 --mem=24G -t 12:00:00 \
  -J fsi-timefix-002 \
  -o "$LOGS/fsi-timefix-002-%j.out" -e "$LOGS/fsi-timefix-002-%j.err" "$BATCH")"
echo "JOBID=$JOBID"
echo "OUT=$LOGS/fsi-timefix-002-$JOBID.out"
echo "ERR=$LOGS/fsi-timefix-002-$JOBID.err"
echo "STATE=$PILOT/production/STATE.json"
