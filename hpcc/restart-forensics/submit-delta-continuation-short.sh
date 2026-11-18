#!/usr/bin/env bash
# One short-stage opt-in. --preflight is default and never submits Slurm.
set -euo pipefail
BASE="$HOME/hpcc-fsi"
CODE="$BASE/crossjob-fix-20261116"
OUTROOT="$CODE/delta-continuation"
SCRIPT="${FSI_DELTA_SCRIPT:-$CODE/delta-continuation.py}"
CORE="${FSI_DELTA_CORE:-$CODE/segment.py}"
RUNNER="${FSI_DELTA_RUNNER:-$CODE/run-delta-continuation-container.sh}"
AUDITOR="${FSI_G1_AUDITOR:-$CODE/audit-g1-92479-for-g2.py}"
G2MODE="${FSI_DELTA_DIAGNOSTIC_G2:-0}"
G3MODE="${FSI_DELTA_G3_PILOT:-0}"
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
if [[ "$G2MODE" != "0" && "$G2MODE" != "1" || "$G3MODE" != "0" && "$G3MODE" != "1" ]];then
  echo "Invalid G2/G3 MODE; only 0/1" >&2;exit 4
fi
if [[ "$PREV" == "93674" || "$G3MODE" == "1" ]];then
  if [[ "$PREV" != "93674" || "$WINDOWS" != "20" || "$G3MODE" != "1" || "$G2MODE" != "0" || "$PARENT" != "$CODE/delta-continuation/trial-93674" ]];then
    echo "G3 pilot can only continue 20 windows from completed G2 job 93674; no production" >&2;exit 4
  fi
fi
if [[ "$G2MODE" == "1" ]];then
  if [[ "$PREV" != "92479" || "$WINDOWS" != "2" || "$PARENT" != "$CODE/delta-continuation/trial-92479" ]];then
    echo "Diagnostic route allowed only G1 92479 -> 2 windows" >&2;exit 4
  fi
  test -s "$AUDITOR" || { echo "Missing independent auditor" >&2;exit 4; }
fi
for f in "$SCRIPT" "$CORE" "$RUNNER" "$PARENT/FSI_SEGMENT_RESULT.json";do
  test -s "$f" || { echo "MISSING $f" >&2;exit 5; }
done
python3 -m py_compile "$SCRIPT" "$CORE"
bash -n "$RUNNER"
python3 "$SCRIPT" --self-test
ARGS=()
if [[ "$G2MODE" == "1" ]];then
  python3 -m py_compile "$AUDITOR"
  python3 "$AUDITOR" --self-test
  python3 "$AUDITOR" --base "$BASE" --driver "$SCRIPT" --core "$CORE" --require-g2-eligible
  ARGS=(--diagnostic-g2)
fi
FSI_G1_AUDITOR="$AUDITOR" FSI_DELTA_CORE_PATH="$CORE" \
python3 "$SCRIPT" --base "$BASE" --core "$CORE" \
 --source-work "$PARENT" --source-job "$PREV" --windows "$WINDOWS" "${ARGS[@]}" --preflight
if [[ "$ACTION" = "--preflight" ]];then
  echo "SOURCE_CHECKPOINT_APPROVED_NO_SBATCH"
  exit 0
fi
test -s "$HOME/seagrass-fsi-ompi507-scotch-time.sif"
ACTIVE="$(squeue -h -u "$USER" -n fsi-delta20,fsi-delta2b -o '%j:%T')"
if [[ -n "$ACTIVE" ]];then
  echo "Another delta stage queued or running: $ACTIVE" >&2; exit 6
fi
PARENT_QUEUE="$(squeue -h -j "$PREV" -o '%T' 2>/dev/null || true)"
if [[ -n "$PARENT_QUEUE" ]];then
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
PAUDITOR=""
HAUDITOR=""
if [[ "$G2MODE" == "1" ]];then
  PAUDITOR="$(pin "$AUDITOR" g1-audit.py)"
  HAUDITOR="$(hashfile "$PAUDITOR")"
fi
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
if [[ "$FSI_G2_DIAGNOSTIC" == "1" ]];then
  test "$(sha256sum "$FSI_AUDITOR"|awk '{print $1}')" = "$FSI_AUDITOR_HASH"
fi
env -u BASH_ENV -u ENV singularity exec --cleanenv \
 "$HOME/seagrass-fsi-ompi507-scotch-time.sif" \
 /usr/bin/env -u BASH_ENV -u ENV /bin/bash --noprofile --norc \
 "$FSI_RUNNER" "$FSI_SCRIPT" "$FSI_CORE" "$FSI_PARENT" \
 "$SLURM_JOB_ID" "$WORK" "$FSI_WINDOWS" "$FSI_PREV" \
 "$FSI_G2_DIAGNOSTIC" "$FSI_AUDITOR"
SBATCH
bash -n "$BATCH"
EXCLUDE=()
LIVE="$(squeue -h -j 91543 -o '%T %N' 2>/dev/null || true)"
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
 --export="ALL,BASH_ENV=,ENV=,FSI_SCRIPT=$PSCRIPT,FSI_SCRIPT_HASH=$HS,FSI_CORE=$PCORE,FSI_CORE_HASH=$HC,FSI_RUNNER=$PRUNNER,FSI_RUNNER_HASH=$HR,FSI_PARENT=$PARENT,FSI_PREV=$PREV,FSI_WINDOWS=$WINDOWS,FSI_G2_DIAGNOSTIC=$G2MODE,FSI_AUDITOR=$PAUDITOR,FSI_AUDITOR_HASH=$HAUDITOR" \
 --output="$OUTROOT/slurm-%j.out" --error="$OUTROOT/slurm-%j.err" "$BATCH")"
echo "SUBMITTED_SINGLE_SHORT_DELTA_JOB=$JOB"
echo "REPORT=$OUTROOT/trial-$JOB/DELTA_CONTINUATION_RESULT.json"
echo "G2_DIAGNOSTIC_ONLY=$G2MODE"
echo "G3_20_WINDOW_PILOT_ONLY=$G3MODE"
echo "NO_AUTO_CHAIN_NO_LONG_PRODUCTION"
