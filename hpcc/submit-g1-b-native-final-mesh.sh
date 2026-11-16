#!/usr/bin/env bash
# Only native checkMesh (NO FSI). Original 90873/90739 case data stay untouched.
set -euo pipefail
BASE="$HOME/hpcc-fsi"
SRC="$BASE/g1-b-native-final-mesh.py"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
mkdir -p "$BASE/logs"
test -s "$SRC"
test -s "$SIF"
python3 -m py_compile "$SRC"
python3 "$SRC" --self-test
python3 "$SRC" --base "$BASE" --preflight-only
if ! ACTIVE="$(squeue -h -u "$USER" -n fsi-g1-native-mesh -o '%i %T')"; then
  echo "STOP: cannot query Slurm queue" >&2
  exit 42
fi
if [[ -n "$ACTIVE" ]]; then
  echo "STOP: duplicate native mesh check: $ACTIVE" >&2
  exit 43
fi
SHA="$(sha256sum "$SRC" | awk '{print $1}')"
COPY="$BASE/g1-b-native-final-mesh-$(printf %.16s "$SHA").py"
if [[ -e "$COPY" ]]; then
  cmp -s "$SRC" "$COPY" || { echo "STOP: frozen source collision"; exit 44; }
else
  cp "$SRC" "$COPY"
  chmod a-w "$COPY"
fi
BATCH="$(mktemp "$BASE/g1-native.XXXXXXXX.sbatch")"
cat > "$BATCH" <<'SBATCH'
#!/usr/bin/env bash
set -euo pipefail
BASE="$HOME/hpcc-fsi"
SIF="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
OUT="$BASE/g1-b-native-final-job-$SLURM_JOB_ID"
test ! -e "$OUT"
test "$(sha256sum "$G1_NATIVE_SOURCE" | awk '{print $1}')" = "$G1_NATIVE_SHA"
echo "G1_B_NATIVE_START job=$SLURM_JOB_ID time=$(date -Is)"
singularity exec --cleanenv "$SIF" bash -c '
set +eu
export WM_MPLIB=SYSTEMOPENMPI
source /usr/lib/openfoam/openfoam2512/etc/bashrc
export PATH="/opt/openmpi-5.0.7/bin:$PATH"
export LD_LIBRARY_PATH="/opt/scotch-compat/lib:/opt/openmpi-5.0.7/lib:/opt/openmpi-5.0.7/lib64:${LD_LIBRARY_PATH:-}"
set -euo pipefail
test "$WM_PROJECT_VERSION" = "v2512"
test "$(command -v mpirun)" = "/opt/openmpi-5.0.7/bin/mpirun"
export SLURM_JOB_ID="$3"
python3 "$1" --base "$HOME/hpcc-fsi" --out-dir "$2" --run
' bash "$G1_NATIVE_SOURCE" "$OUT" "$SLURM_JOB_ID"
echo "G1_B_NATIVE_SLURM_EXIT=0"
SBATCH
JOB="$(sbatch --parsable -p cpu -N 1 -n 1 -c 8 --mem=16G -t 00:30:00 \
  --export="ALL,G1_NATIVE_SOURCE=$COPY,G1_NATIVE_SHA=$SHA" \
  -J fsi-g1-native-mesh \
  -o "$BASE/logs/fsi-g1-native-mesh-%j.out" \
  -e "$BASE/logs/fsi-g1-native-mesh-%j.err" \
  "$BATCH")"
echo "G1_B_NATIVE_SUBMITTED_JOB_ID=$JOB"
echo "EVIDENCE=$BASE/g1-b-native-final-job-$JOB/G1_B_NATIVE_FINAL_EVIDENCE.json"
echo "STDOUT=$BASE/logs/fsi-g1-native-mesh-$JOB.out"
echo "STDERR=$BASE/logs/fsi-g1-native-mesh-$JOB.err"
