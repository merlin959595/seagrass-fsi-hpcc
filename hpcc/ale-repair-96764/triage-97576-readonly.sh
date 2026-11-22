#!/usr/bin/env bash
# Read-only live triage of repair Slurm 97576, with candidate-specific
# OpenFOAM/CalculiX causes. Never runs CFD, sbatch, scancel, cp or rm.
set -u
P="/data/icto/$USER/seagrass-fsi558-runs.sNIpi9"
R="$P/repair-96764-github-20261122-v3"
echo "========== SLURM STATE =========="
squeue -j 97576,97586 -o "%.12i %.14T %.12M %.36R" 2>&1 || true
echo "========== MAIN JOB EVENTS =========="
grep -E 'BACKUP_FULL_TRIAL|CANDIDATE_96764|FSI_LONG_SEGMENT|FINAL_REPAIR96764|PRODUCTION_AFTEROK|WATCHDOG|Traceback' "$R/logs-97576.out" 2>/dev/null | tail -18 || true
echo "========== RESTORED SOURCE =========="
for c in trial-96763 trial-96764;do
    if test -s "$R/backups/$c.manifest.json";then
        echo "BACKUP_MANIFEST_PRESENT $c"
    else
        echo "BACKUP_MANIFEST_NOT_PRESENT $c"
    fi
done
echo "========== CANDIDATE ACTUAL LOGS =========="
for k in 1 2 3;do
 for stage in 1 2;do
  W="$P/trial-97576-repair96764-c$k-stage$stage"
  test -d "$W" || continue
  echo
  echo "===== CANDIDATE $k / STAGE $stage: $W ====="
  for f in STATE.json DELTA_CONTINUATION_RESULT.json FSI_SEGMENT_RESULT.json LOCAL_ALE_REPAIR96764.json;do
     test -f "$W/$f" || continue
     echo "--- $f ---"
     # Summary only; if file is malformed or incomplete, preserve as-is.
     python3 - "$W/$f" <<'PY'
import json,sys
from pathlib import Path
p=Path(sys.argv[1])
try:
 d=json.loads(p.read_text(errors='replace'))
 if not isinstance(d,dict): raise ValueError('NOT_OBJECT')
 for k in ('status','failure','exception','start_t','end_t','parent_time_s','final_time_s','accepted_time_s','accepted_windows','participant_exit_codes','native_terminal_mesh'):
  if k in d: print(k,repr(d[k])[:900])
except Exception as e: print('JSON_INCOMPLETE_OR_INVALID',str(e))
PY
  done
  for log in fluid.log solid.log;do
     F="$W/$log"
     test -f "$F" || { echo "MISSING_$log"; continue; }
     echo "---- $log size=$(stat -c %s "$F" 2>/dev/null || echo unknown) ----"
     echo "MOST RECENT PHYSICAL TIME MARKERS"
     if [[ "$log" == "fluid.log" ]];then
        grep -E '^[[:space:]]*Time[[:space:]]*=' "$F" 2>/dev/null | tail -5 || true
     else
        grep -Ei 'time window|advance|iteration' "$F" 2>/dev/null | tail -5 || true
     fi
     echo "FATAL/QUALITY INDICATORS"
     grep -Eia 'FOAM FATAL|fatal error|segmentation fault|SIGSEGV|SIGABRT|SIGFPE|floating point exception|invalid mesh|concave|non.?ortho|negative volume|face.?tet|mesh.?guard|mesh.*fail|exceeded|not converg|aborted|ERROR|connection lost|failed' "$F" 2>/dev/null | tail -18 || true
     echo "LOG END"
     tail -45 "$F"
  done
 done
done
echo
echo "========== GUARDIAN STATE =========="
G="$R/guardian-after97576"
if [[ -f "$G/guardian-97586.out" ]];then tail -20 "$G/guardian-97586.out";fi
if [[ -f "$G/guardian-97586.err" ]];then tail -15 "$G/guardian-97586.err";fi
echo "========== END READ-ONLY TRIAGE =========="
