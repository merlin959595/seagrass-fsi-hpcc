#!/usr/bin/env bash
# Submit isolated, real 0.02 s implicit FSI (8 fluid MPI + 2 CCX threads)
# from the verified transfer and MPI5 fullstack SIF.
# Never overwrite a previous run. This job does not claim persistent restart.
set -euo pipefail

ROOT="$HOME/hpcc-fsi/seagrass-implicit-20261111"
SIF="$HOME/seagrass-fsi-ompi507-fullstack.sif"
SCRIPT="$ROOT/hpcc/implicit-002-driver.py"
OUT="$HOME/hpcc-fsi/implicit-pilot-002-8mpi-20261111"
LOGS="$HOME/hpcc-fsi/logs"
BATCH="$HOME/hpcc-fsi/implicit-pilot-002-8mpi.sbatch"

test -s "$SCRIPT" || { echo "ERROR: upload driver to $SCRIPT first"; exit 1; }
test -s "$SIF" || { echo "ERROR: candidate SIF not present"; exit 1; }
test -s "$ROOT/fsi-implicit-production/run_production.py"
test -s "$ROOT/fsi-explicit-test/inputs/SOURCE_BINDING.json"
test -s "$ROOT/scripts/native/bin/ccx_preCICE_persistent_v2"
test ! -e "$OUT" || { echo "STOP: work directory already exists: $OUT"; exit 1; }
mkdir -p "$LOGS"
cat > "$BATCH" <<'SBATCH'
#!/usr/bin/env bash
set -euo pipefail
ROOT="$HOME/hpcc-fsi/seagrass-implicit-20261111"
SIF="$HOME/seagrass-fsi-ompi507-fullstack.sif"
PILOT="$HOME/hpcc-fsi/implicit-pilot-002-8mpi-20261111"
export OMPI_MCA_btl_vader_single_copy_mechanism=none
echo "==== ALLOCATED COMPUTE NODE ===="
hostname; date -Is
echo "SLURM_JOB_ID=$SLURM_JOB_ID SLURM_CPUS_PER_TASK=$SLURM_CPUS_PER_TASK"
echo "==== IMMUTABLE FSI PREFLIGHT ===="
singularity exec --cleanenv "$SIF" bash -c '
set +eu
export WM_MPLIB=SYSTEMOPENMPI
source /usr/lib/openfoam/openfoam2512/etc/bashrc
export PATH="/opt/precice-3.4.1-ompi5/bin:/opt/openmpi-5.0.7/bin:$PATH"
export LD_LIBRARY_PATH="/opt/precice-3.4.1-ompi5/lib:/opt/precice-3.4.1-ompi5/lib64:/opt/openmpi-5.0.7/lib:/opt/openmpi-5.0.7/lib64:${LD_LIBRARY_PATH:-}"
export PKG_CONFIG_PATH="/opt/precice-3.4.1-ompi5/lib/pkgconfig:/opt/precice-3.4.1-ompi5/lib64/pkgconfig:${PKG_CONFIG_PATH:-}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export LD_LIBRARY_PATH="$HOME/hpcc-fsi/seagrass-implicit-20261111/scripts/native/lib:$HOME/hpcc-fsi/seagrass-implicit-20261111/fsi-explicit-test/mesh-guard/lib:$LD_LIBRARY_PATH"
set -eo pipefail
ROOT="$HOME/hpcc-fsi/seagrass-implicit-20261111"
BASE="$HOME/hpcc-fsi/implicit-pilot-002-8mpi-20261111"
echo "MPI $(mpirun --version | head -n1)"
echo "preCICE $(precice-version)"
python3 "$ROOT/hpcc/implicit-002-driver.py" --root "$ROOT" --work "$BASE/preflight" --mode preflight --ranks 8
echo "==== REAL 0.02 s COUPLING ===="
python3 "$ROOT/hpcc/implicit-002-driver.py" --root "$ROOT" --work "$BASE/production" --mode run --ranks 8
echo "HPCC_IMPLICIT_0P02_ACCEPTED_160_WINDOWS_PASS"
'
SBATCH
mkdir -p "$ROOT/hpcc"
echo "Submitting real FSI pilot; 8 fluid MPI ranks, 2 CCX threads, 0.02 s, dt=0.000125."
JOBID="$(sbatch --parsable -p cpu -N 1 -n 1 -c 12 --mem=24G -t 12:00:00 \
    -J fsi-implicit-002 \
    -o "$LOGS/fsi-implicit-002-%j.out" -e "$LOGS/fsi-implicit-002-%j.err" \
    "$BATCH")"
echo "JOBID=$JOBID"
echo "Output=$LOGS/fsi-implicit-002-$JOBID.out"
echo "Error=$LOGS/fsi-implicit-002-$JOBID.err"
echo "State=$OUT/production/STATE.json"
