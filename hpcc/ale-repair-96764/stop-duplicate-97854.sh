#!/usr/bin/env bash
# Non-destructive cancellation of ONLY duplicated Slurm job 97854.
# Fail closed unless V5 C1/C2 replicate V3 native ALE concavity failures.
# Never touches trial data, source checkpoints, backups or pending chains.
set -Eeuo pipefail
USER_ID="${USER:?}"
P="/data/icto/$USER_ID/seagrass-fsi558-runs.sNIpi9"
R="$P/repair-96764-github-20261122-v3"
A="$P/trial-97854-repair96764-c1-stage1/fluid.log"
B="$P/trial-97854-repair96764-c2-stage1/fluid.log"
OLD="$R/RESULT-97576.json"
[[ -s "$OLD" && -s "$A" && -s "$B" ]] || {
  echo "STOP_GUARD_MISSING_EVIDENCE: no action"; exit 40;
}
python3 - "$OLD" <<'PY'
import json,sys
x=json.load(open(sys.argv[1]))
assert x.get("job")==97576 and x.get("status")=="REPAIR_NOT_YET_VALIDATED"
assert x.get("next_production_submission_permitted") is False
v=x.get("experiments",[])
assert len(v)==3 and all(e.get("stage")==1 and e.get("pass") is False for e in v)
assert [(e.get("gain"),e.get("rings")) for e in v]==[(1.2,8),(0.85,8),(1.35,12)]
PY
grep -aqE 'SEAGRASS_MESH_GUARD time=0\.563625[^[:cntrl:]]*concave=1' "$A" || {
  echo "STOP_GUARD_V5_C1_NOT_IDENTICAL_FAILURE: no action"; exit 41;
}
grep -aqE 'SEAGRASS_MESH_GUARD time=0\.580750[^[:cntrl:]]*concave=1' "$B" || {
  echo "STOP_GUARD_V5_C2_NOT_IDENTICAL_FAILURE: no action"; exit 41;
}
for case in trial-96763 trial-96764; do
  [[ -d "$R/backups/$case" && -s "$R/backups/$case.manifest.json" ]] || {
    echo "STOP_GUARD_FULL_BACKUP_MISSING $case: no action"; exit 42;
  }
done
J="$(squeue -h -j 97854 -o '%i|%j|%T')" || {
  echo "STOP_GUARD_SQUEUE_UNAVAILABLE: no action"; exit 43;
}
if [[ -z "$J" ]]; then
  echo "REPEAT_JOB_ALREADY_TERMINAL_OR_NOT_QUEUED; no action"
  exit 0
fi
if [[ "$J" != "97854|ale96764repair|RUNNING" && "$J" != "97854|ale96764repair|PENDING" ]]; then
  echo "STOP_GUARD_JOB_ID_NAME_STATE_MISMATCH $J: no action"; exit 44
fi
echo "VERIFIED_DUPLICATE_NATIVE_ALE_FAILURE $J"
echo "ABOUT_TO_CANCEL_ONLY_SLURM_JOB_97854"
scancel 97854
echo "SCANCEL_REQUEST_SENT_97854"
squeue -j 97854 -o "%.12i %.14j %.14T %.12M %.25R" || true
