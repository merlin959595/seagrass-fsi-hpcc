#!/usr/bin/env bash
# One short-stage opt-in. --preflight is default and never submits Slurm.
set -euo pipefail
BASE="$HOME/hpcc-fsi"
CODE="$BASE/crossjob-fix-20261116"
OUTROOT="$CODE/delta-continuation"
SCRIPT="$CODE/delta-continuation.py"
CORE="$CODE/segment.py"
RUNNER="$CODE/run-delta-continuation-container.sh"
PARENT="${FSI_DELTA_SOURCE_WORK:-$CODE/delta-2window/trial-92264}"
WINDOWS="${FSI_DELTA_WINDOWS:-20}"
ACTION="${1:---preflight}"
if [[ "$#" -gt 1 || ( "$ACTION" != "--preflight" && "$ACTION" != "--submit" ) ]];then
  echo "Usage: bash submit-delta-continuation-short.sh [--preflight|--submit]" >&2
  exit 2
fi
if [[ "$WINDOWS" != 2 && "$WINDOWS" != 20 ]];then
  echo "Only 2 or 20 windows before long production qualification" >&2
  exit 3
fi
PARENT="$(realpath "$PARENT")"
if [[ "$PARENT" != "$BASE/"* || ! "$PARENT" =~ /trial-([0-9]+)$ ]];then
  echo "Parent must be a trial-number work folder under hpcc-fsi" >&2
  exit 4
fi
PREV="${BASH_REMATCH[1]}"
for f in "$SCRIPT" "$CORE" "$RUNNER" "$PARENT/FSI_SEGMENT_RESULT.json";do
  test -s "$f" || { echo "MISSING $f" >&2;exit 5; }
done
python3 -m py_compile "$SCRIPT" "$CORE"
bash -n "$RUNNER"
python3 "$SCRIPT" --self-test
python3 "$SCRIPT" --base "$BASE" --core "$CORE" \
 --source-work "$PARENT" --source-job "$PREV" --windows "$WINDOWS" --preflight
if [[ "$ACTION" = "--preflight" ]];then
  echo "SOURCE_CHECKPOINT_APPROVED_NO_SBATCH"
  exit 0
fi
test -s "$HOME/seagrass-fsi-ompi507-scotch-time.sif"
ACTIVE="$(squeue -h -u "$USER" -n fsi-delta20,fsi-delta2b -o '%j:%T')"
if [[ -n "$ACTIVE" ]];then
  echo "Another delta stage queued or running: $ACTIVE" >&2; exit 6
fi
if [[ -n "$(squeue -h -j "$PREV" -o '%T')" ]];then
  echo "Parent job $PREV still active" >&2;exit 7
fi
mkdir -p "$OUTROOT"
hashfile() { sha256sum "$1"|awk '{print $1}'; }
pin() {
  local src="$1" name="$2" hash result
  hash="$(hashfile "$src")"
  result="$OUTROOT/$name-$(echo "$hash"|cut -c1-16).${src##*.}"
  if [[ -f "$result" ]];then cmp -s "$src" "$result" || exit 8
  else cp "$src" "$result";chmod a-w "$result";fi
  printf '%s\n' "$result"
}
PSCRIPT="$(pin "$SCRIPT" driver.py)"
PCORE="$(pin "$CORE" core.py)"
PRUNNER="$(pin "$RUNNER" runner.sh)"
HS="$(hashfile "$PSCRIPT")";HC="$(hashfile "$PCORE")";HR="$(hashfile "$PRUNNER")"
BATCH="$OUTROOT/short-$WINDOWS-from-$PREV-$(echo "$HS"|cut -c1-12).sbatch"
test ! -e "$BATCH" || { echo "Prevent identical duplicate submission" >&2;exit 9; }
cat > "$BATCH" <<'SBATCH'
#!/usr/bin/env bash
set -euo pipefail
BASE="$HOME/hpcc-fsi"
WORK="$BASE/crossjob-fix-20261116/delta-continuation/trial-$SLURM_JOB_ID"
test ! -e "$WORK"
test "$(sha256sum "$FSI_SCRIPT"|awk '{print $1}')" = "$FSI_SCRIPT_HASH"
test "$(sha256sum "$FSI_CORE"|awk '{print $1}')" = "$FSI_CORE_HASH"
test "$(sha256sum "$FSI_RUNNER"|awk '{print $1}')" = "$FSI_RUNNER_HASH"
env -u BASH_ENV -u ENV singularity exec --cleanenv \
 "$HOME/seagrass-fsi-ompi507-scotch-time.sif" \
 /usr/bin/env -u BASH_ENV -u ENV /bin/bash --noprofile --norc \
 "$FSI_RUNNER" "$FSI_SCRIPT" "$FSI_CORE" "$FSI_PARENT" \
 "$SLURM_JOB_ID" "$WORK" "$FSI_WINDOWS" "$FSI_PREV"
SBATCH
bash -n "$BATCH"
EXCLUDE=()
LIVE="$(squeue -h -j 91543 -o '%T %N')"
if [[ "$LIVE" == RUNNING\ * ]];then
  NODE="$(echo "$LIVE"|awk '{print $2}')"
  if [[ -z "$NODE" || "$NODE" == "(null)" || "$NODE" == "None" ]];then
    echo "Could not safely exclude 91543 node" >&2;exit 10
  fi
  EXCLUDE=(--exclude="$NODE")
fi
NAME=fsi-delta20
if [[ "$WINDOWS" = 2 ]];then NAME=fsi-delta2b;fi
JOB="$(sbatch --parsable --partition=cpu --nodes=1 --ntasks=1 \
 --cpus-per-task=12 --mem=24G --time=03:00:00 "${EXCLUDE[@]}" \
 --job-name="$NAME" \
 --export="ALL,BASH_ENV=,ENV=,FSI_SCRIPT=$PSCRIPT,FSI_SCRIPT_HASH=$HS,FSI_CORE=$PCORE,FSI_CORE_HASH=$HC,FSI_RUNNER=$PRUNNER,FSI_RUNNER_HASH=$HR,FSI_PARENT=$PARENT,FSI_PREV=$PREV,FSI_WINDOWS=$WINDOWS" \
 --output="$OUTROOT/slurm-%j.out" --error="$OUTROOT/slurm-%j.err" "$BATCH")"
echo "SUBMITTED_SINGLE_SHORT_DELTA_JOB=$JOB"
echo "REPORT=$OUTROOT/trial-$JOB/DELTA_CONTINUATION_RESULT.json"
echo "NO_AUTO_CHAIN_NO_LONG_PRODUCTION"
