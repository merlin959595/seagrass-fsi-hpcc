#!/usr/bin/env bash
# Slurm afterany watchdog. No FSI resource use beyond launching the V5
# already validated bootstrap after and ONLY if job 97576 has ended without
# a verified pass/production chain. Never cancels, overwrites or cleans data.
set -Eeuo pipefail
: "${USER:?}"
P="/data/icto/$USER/seagrass-fsi558-runs.sNIpi9"
R="$P/repair-96764-github-20261122-v3"
G="$R/guardian-after97576"
BOOT="$G/bootstrap-96764-v5.sh"
[[ -n "${SLURM_JOB_ID:-}" ]] || { echo "WATCHDOG_REQUIRES_SLURM_ALLOCATION" >&2; exit 20; }
[[ -s "$BOOT" ]] || { echo "PINNED_FALLBACK_BOOTSTRAP_MISSING" >&2; exit 21; }
[[ -s "$G/ARMED_GUARDIAN.txt" ]] || { echo "WATCHDOG_NOT_ARMED" >&2; exit 21; }

if squeue -h -j 97576 -o "%i %T" | grep -Eq '97576[[:space:]]+(RUNNING|PENDING|CONFIGURING|COMPLETING)'; then
   echo "BLOCKED_PARENT_97576_STILL_ACTIVE"
   exit 25
fi

if [[ -s "$R/CHAIN-97576.json" ]]; then
    echo "PARENT_HAS_EXISTING_CHAIN_NO_FALLBACK"
    exit 0
fi
if [[ -s "$R/RESULT-97576.json" ]]; then
    if python3 - "$R/RESULT-97576.json" <<'PY'
import json,sys
try:
    a=json.load(open(sys.argv[1]))
    ok=a.get("status")=="REAL_FSI_REPLAY_TO_0P6035_PASS" and a.get("next_production_submission_permitted") is True
except (OSError,ValueError,TypeError):
    ok=False
sys.exit(0 if ok else 1)
PY
    then
       echo "PARENT_FSI_PASS_BUT_CHAIN_MISSING_DO_NOT_DUPLICATE_REQUIRES_RECONCILIATION" >&2
       exit 26
    fi
fi
ACTIVE="$(squeue -h -u "$USER" -n ale96764repair,ale96764go -o '%i %T')" || exit 27
if [[ -n "$ACTIVE" ]]; then
    echo "EXISTING_REPAIR_OR_PRODUCTION_JOB_NO_FALLBACK $ACTIVE"
    exit 28
fi
for case in trial-96763 trial-96764; do
    [[ -d "$R/backups/$case" && -s "$R/backups/$case.manifest.json" ]] || {
        echo "REQUIRED_PRIOR_FULL_BACKUP_MISSING $case" >&2
        exit 29
    }
done
# Backup SHA256 re-verification and library/source checks occur inside V5.
# Do not delete or reuse partially written trial directories.
echo "WATCHDOG_PARENT_DONE_NO_PASS; STARTING_PINNED_V5_FALLBACK"
bash "$BOOT" --submit
echo "WATCHDOG_V5_SUBMIT_RETURNED_SUCCESS"
