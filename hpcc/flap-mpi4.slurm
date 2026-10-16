#!/usr/bin/env bash
#SBATCH --job-name=flap-mpi4
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=5
#SBATCH --mem=8G
#SBATCH --time=00:40:00

# Isolated one-node 4-MPI-rank OpenFOAM + 1 CalculiX coupled smoke test.
# Run: sbatch -o "$HOME/hpcc-fsi/logs/flap-mpi4-%j.out" -e "$HOME/hpcc-fsi/logs/flap-mpi4-%j.err" flap-mpi4.slurm
set -Eeuo pipefail
SOURCE_ROOT="$HOME/hpcc-fsi/validation"
SOURCE_CASE="$SOURCE_ROOT/perpendicular-flap"
SIF="$HOME/seagrass-fsi.sif"
RUN_ROOT="$SOURCE_ROOT/runs"
RUN_DIR="$RUN_ROOT/flap-mpi4-${SLURM_JOB_ID:?SLURM_JOB_ID is required}"
mkdir -p "$RUN_DIR"
test -s "$SIF"
test -f "$SOURCE_CASE/precice-config.xml"
test -f "$SOURCE_ROOT/tools/run-openfoam.sh"
test -f "$SOURCE_CASE/solid-calculix/flap.inp"
cp -a "$SOURCE_CASE" "$RUN_DIR/perpendicular-flap"
cp -a "$SOURCE_ROOT/tools" "$RUN_DIR/tools"

# Modify only the isolated copy: 0.05 s / five coupling windows.
XML="$RUN_DIR/perpendicular-flap/precice-config.xml"
grep -Fq '<max-time value="5" />' "$XML" || { echo "UNEXPECTED_TUTORIAL_CONFIG"; exit 2; }
sed -i 's#<max-time value="5" />#<max-time value="0.05" />#' "$XML"
grep -Fq '<max-time value="0.05" />' "$XML" || exit 2
echo "RUN_DIR=$RUN_DIR"
echo "IMAGE=$SIF"
echo "COUPLING_MAX_TIME=0.05"
echo "FLUID_MPI_RANKS_REQUESTED=4"
check="$RUN_DIR/perpendicular-flap/fluid-openfoam/system/decomposeParDict"
grep -Eq "numberOfSubdomains[[:space:]]+4;" "$check" || { echo "UNEXPECTED_DECOMPOSITION"; exit 2; }

# Share one filesystem and one compute node for both preCICE participants.
singularity exec --cleanenv --bind "$RUN_DIR:/validation" "$SIF" bash -c 'source /usr/lib/openfoam/openfoam2512/etc/bashrc; cd /validation/perpendicular-flap/fluid-openfoam; exec ./run.sh -parallel' >"$RUN_DIR/fluid.stdout" 2>&1 &
FLUID_PID=$!
singularity exec --cleanenv --bind "$RUN_DIR:/validation" "$SIF" bash -c 'source /usr/lib/openfoam/openfoam2512/etc/bashrc; cd /validation/perpendicular-flap/solid-calculix; exec ./run.sh' >"$RUN_DIR/solid.stdout" 2>&1 &
SOLID_PID=$!

cleanup() {
  kill "$FLUID_PID" "$SOLID_PID" 2>/dev/null || true
}
trap cleanup INT TERM

# As soon as one participant fails, terminate the other rather than waiting for the time limit.
set +e
wait -n -p FIRST_DONE "$FLUID_PID" "$SOLID_PID"
FIRST_RC=$?
set -e
if [ "$FIRST_RC" -ne 0 ]; then
  echo "FIRST_PARTICIPANT_FAILED exit=$FIRST_RC pid=${FIRST_DONE:-unknown}"
  cleanup
  wait "$FLUID_PID" 2>/dev/null || true
  wait "$SOLID_PID" 2>/dev/null || true
  echo "---- FLUID LOG TAIL ----"
  tail -n 35 "$RUN_DIR/fluid.stdout"
  echo "---- SOLID LOG TAIL ----"
  tail -n 35 "$RUN_DIR/solid.stdout"
  exit 1
fi
if [ "${FIRST_DONE:-}" = "$FLUID_PID" ]; then
  wait "$SOLID_PID"
else
  wait "$FLUID_PID"
fi
echo "BOTH_PARTICIPANTS_EXIT_ZERO"
echo "---- FLUID LOG TAIL ----"
tail -n 25 "$RUN_DIR/fluid.stdout"
echo "---- SOLID LOG TAIL ----"
tail -n 25 "$RUN_DIR/solid.stdout"
if ! grep -Fq 'Reached end at: final time-window: 5, final time: 0.05' "$RUN_DIR/solid.stdout"; then echo "FSI_FINAL_TIME_NOT_CONFIRMED"; exit 3; fi
WINDOWS=$(grep -c 'Time window completed' "$RUN_DIR/solid.stdout" || true)
echo "COMPLETED_WINDOWS=$WINDOWS"
test "$WINDOWS" -eq 5 || { echo "EXPECTED_FIVE_WINDOWS"; exit 4; }
PROC_COUNT=$(find "$RUN_DIR/perpendicular-flap/fluid-openfoam" -maxdepth 1 -type d -name 'processor[0-9]*' | wc -l)
echo "PROCESSOR_DIRS=$PROC_COUNT"
test "$PROC_COUNT" -eq 4 || { echo "EXPECTED_FOUR_MPI_PROCESSORS"; exit 5; }
echo "MPI4_FSI_OK"
