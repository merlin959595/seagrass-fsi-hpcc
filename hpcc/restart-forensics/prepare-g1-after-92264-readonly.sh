#!/usr/bin/env bash
# Single entry point to check 92264, freeze next code, run read-only G1 preflight.
# Never calls sbatch or modifies 91006/91543 or numerical checkpoint files.
set -euo pipefail
BASE="$HOME/hpcc-fsi"
WORK="$BASE/crossjob-fix-20261116/delta-2window/trial-92264"
REV="a0681df79291f7f1e71b1e408891386b8c644ce0"
CODE="$BASE/crossjob-fix-20261116/delta-next-$REV"
RAW="https://raw.githubusercontent.com/merlin959595/seagrass-fsi-hpcc/$REV"
echo "======= 92264 scheduler ======="
squeue -j 92264 -o "%.12i %.12T %.12M" || true
sacct -j 92264 --format=JobID,State,ExitCode,Elapsed -P 2>/dev/null || true
echo "======= 92264 native acceptance ======="
R="$WORK/INCREMENTAL_DISPLACEMENT_RESULT.json"
if [[ ! -s "$R" ]];then
  echo "G0_BLOCKED: still running or final 2-window report missing; NO next stage"
  exit 0
fi
python3 - "$R" <<'PY'
import json,sys
r=json.load(open(sys.argv[1]))
print("G0_REPORTED_STATUS:",r.get("status"))
print("NATIVE_STATUS:",(r.get("actual_native_result") or {}).get("status"))
print("MATCHED_WINDOWS:",r.get("accepted_vs_continuous"))
if r.get("status")!="INCREMENTAL_DISPLACEMENT_TWO_WINDOW_PASS":
    raise SystemExit("G0_BLOCKED: no verified PASS; no G1 stage")
PY
echo "======= Download same-commit frozen next-stage scripts ======="
mkdir -p "$CODE"
for spec in \
  "hpcc/restart-forensics/delta-continuation.py:delta-continuation.py" \
  "hpcc/restart-forensics/run-delta-continuation-container.sh:run-delta-continuation-container.sh" \
  "hpcc/restart-forensics/submit-delta-continuation-short.sh:submit-delta-continuation-short.sh" \
  "hpcc/clean-production/segment.py:segment.py"; do
  from="$(echo "$spec"|cut -d: -f1)"
  name="$(echo "$spec"|cut -d: -f2)"
  curl -fLsS "$RAW/$from" -o "$CODE/$name"
done
echo "======= Read-only scientific and checkpoint G1 preflight ======="
export FSI_DELTA_SCRIPT="$CODE/delta-continuation.py"
export FSI_DELTA_CORE="$CODE/segment.py"
export FSI_DELTA_RUNNER="$CODE/run-delta-continuation-container.sh"
bash "$CODE/submit-delta-continuation-short.sh" --preflight
echo "G1_PREFLIGHT_PASSED_NOT_SUBMITTED"
echo "Frozen source code: $CODE"
echo "To submit requires explicit subsequent --submit; no automatic jobs."
