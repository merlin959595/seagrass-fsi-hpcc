#!/usr/bin/env bash
# G1 scientific 1% FAIL is preserved. This permits only a bounded two-window
# G2 diagnostic if native completion + raw 20-window independent review pass.
# Source 92479 and comparator 91543 are never modified.
set -euo pipefail
ACTION="${1:---preflight}"
if [[ "$#" -gt 1 || ( "$ACTION" != "--preflight" && "$ACTION" != "--submit" ) ]];then
  echo "Usage: bash prepare-and-submit-g2-92479.sh [--preflight|--submit]" >&2
  exit 2
fi
BASE="$HOME/hpcc-fsi"
ROOT="$BASE/crossjob-fix-20261116"
REV="3b65bd314528aa14a6e8aae545b1c7d670c2bb2a"
CODE="$ROOT/g2-diagnostic-$REV"
RAW="https://raw.githubusercontent.com/merlin959595/seagrass-fsi-hpcc/$REV"
PARENT="$ROOT/delta-continuation/trial-92479"
if [[ ! -s "$PARENT/DELTA_CONTINUATION_RESULT.json" ]];then
  echo "BLOCKED: G1 92479 final result not available" >&2
  exit 3
fi
mkdir -p "$CODE"
for spec in \
 "hpcc/restart-forensics/delta-continuation.py:delta-continuation.py" \
 "hpcc/restart-forensics/audit-g1-92479-for-g2.py:audit-g1-92479-for-g2.py" \
 "hpcc/restart-forensics/run-delta-continuation-container.sh:run-delta-continuation-container.sh" \
 "hpcc/restart-forensics/submit-delta-continuation-short.sh:submit-delta-continuation-short.sh" \
 "hpcc/clean-production/segment.py:segment.py"; do
  remote="${spec%%:*}"
  name="${spec##*:}"
  temp="$(mktemp "$CODE/download.XXXXXXXX")"
  trap 'rm -f "$temp"' EXIT
  curl -fLsS "$RAW/$remote" -o "$temp"
  if [[ -f "$CODE/$name" ]];then
    cmp -s "$CODE/$name" "$temp" || {
      echo "BLOCKED: refusing to overwrite pinned code $CODE/$name" >&2
      exit 4
    }
  else
    mv "$temp" "$CODE/$name"
  fi
  rm -f "$temp"
done
trap - EXIT
export FSI_DELTA_SCRIPT="$CODE/delta-continuation.py"
export FSI_DELTA_CORE="$CODE/segment.py"
export FSI_DELTA_RUNNER="$CODE/run-delta-continuation-container.sh"
export FSI_G1_AUDITOR="$CODE/audit-g1-92479-for-g2.py"
export FSI_DELTA_SOURCE_WORK="$PARENT"
export FSI_DELTA_WINDOWS=2
export FSI_DELTA_DIAGNOSTIC_G2=1
echo "===== Independent G1 native and scientific audit ====="
python3 "$FSI_G1_AUDITOR" --base "$BASE" \
  --driver "$FSI_DELTA_SCRIPT" --core "$FSI_DELTA_CORE" \
  --require-g2-eligible
echo "===== Checkpoints, dynamic history, protocol and step ====="
bash "$CODE/submit-delta-continuation-short.sh" --preflight
if [[ "$ACTION" == "--preflight" ]];then
  echo "G2_READONLY_PREFLIGHT_PASSED_NO_JOB_SUBMITTED"
  exit 0
fi
echo "===== Submit one isolated 2-window diagnostic only ====="
bash "$CODE/submit-delta-continuation-short.sh" --submit
echo "ORIGINAL_G1_SCIENTIFIC_FAIL_NOT_OVERWRITTEN"
echo "NO_LONG_PRODUCTION_NO_AUTO_CHAIN"
