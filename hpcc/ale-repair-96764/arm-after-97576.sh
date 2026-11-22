#!/usr/bin/env bash
# One-time, non-destructive Slurm AFTERANY arm for job 97576.
# It does NOT cancel or restart the active job; the guarded fallback runs only
# after 97576 exits without a verified FSI success or existing production.
set -Eeuo pipefail
: "${USER:?}"
P="/data/icto/$USER/seagrass-fsi558-runs.sNIpi9"
R="$P/repair-96764-github-20261122-v3"
G="$R/guardian-after97576"

[[ -d "$R/backups/trial-96763" && -s "$R/backups/trial-96763.manifest.json" ]] || {
    echo "MISSING_FULL_96763_BACKUP; NOT_ARMING" >&2; exit 20;
}
[[ -d "$R/backups/trial-96764" && -s "$R/backups/trial-96764.manifest.json" ]] || {
    echo "MISSING_FULL_96764_BACKUP; NOT_ARMING" >&2; exit 20;
}
ACTIVE="$(squeue -h -j 97576 -o "%i %T")" || exit 21
DEPENDENCY=""
if [[ "$ACTIVE" =~ 97576[[:space:]]+(RUNNING|PENDING|CONFIGURING|COMPLETING) ]]; then
    DEPENDENCY="--dependency=afterany:97576"
else
    STATE="$(sacct -j 97576 -X -n -o State 2>/dev/null | head -1 | xargs || true)"
    case "$STATE" in
        COMPLETED|FAILED|CANCELLED*|TIMEOUT|NODE_FAIL|OUT_OF_MEMORY|PREEMPTED|DEADLINE)
            echo "PARENT_TERMINAL_$STATE; GUARDIAN_WILL_CHECK_IMMEDIATELY"
            ;;
        *)
            echo "PARENT_STATUS_UNVERIFIED active=$ACTIVE accounting=$STATE" >&2
            exit 21
            ;;
    esac
fi
if ! mkdir "$G" 2>/dev/null; then
    echo "GUARDIAN_DIRECTORY_ALREADY_EXISTS; REFUSE_DUPLICATE_SUBMISSION: $G" >&2
    exit 22
fi
get_checked() {
    local url="$1" expected="$2" dest="$3" tmp
    tmp="$(mktemp "$G/.download.XXXXXXXX")"
    curl -fLsS --retry 5 --retry-all-errors --connect-timeout 15 --max-time 90 \
         "$url" -o "$tmp"
    local actual
    actual="$(python3 - "$tmp" <<'PY'
import hashlib,sys
raw=open(sys.argv[1],"rb").read()
print(hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest())
PY
)"
    if [[ "$actual" != "$expected" ]]; then
        echo "GITHUB_BLOB_MISMATCH: $dest expected=$expected actual=$actual" >&2
        exit 23
    fi
    mv "$tmp" "$dest"
    chmod a-w "$dest"
}
get_checked \
 "https://raw.githubusercontent.com/merlin959595/seagrass-fsi-hpcc/e308e76ddd2d8dfa8e0879477bea61fc68624b32/hpcc/ale-repair-96764/watch-after-97576.sh" \
 "e627cf5b3acf44d458d627be234d9d613314a801" "$G/watch-after-97576.sh"
get_checked \
 "https://raw.githubusercontent.com/merlin959595/seagrass-fsi-hpcc/d78803a0ac6d93ce51c95640adc21daa357a2e12/hpcc/ale-repair-96764/bootstrap-96764-v5.sh" \
 "4ad452c18f82417e75c4d5ef585ce78fe6b92c67" "$G/bootstrap-96764-v5.sh"

bash -n "$G/watch-after-97576.sh"
bash -n "$G/bootstrap-96764-v5.sh"
# Download/validate the future fallback now on login; no Slurm FSI submission.
bash "$G/bootstrap-96764-v5.sh" --preflight >"$G/V5_PREFLIGHT.log" 2>&1 || {
    tail -60 "$G/V5_PREFLIGHT.log" >&2
    echo "V5_PRECHECK_FAILED; DO_NOT_ARM" >&2
    exit 24
}
printf 'armed_from=%s\nparent=97576\nbootstrap_sha=4ad452c18f82417e75c4d5ef585ce78fe6b92c67\n' \
    "$(date -u +%FT%TZ)" >"$G/ARMED_GUARDIAN.txt"

BATCH="$G/guardian.sbatch"
cat > "$BATCH" <<EOF
#!/bin/bash
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=02:00:00
#SBATCH --job-name=ale96764watch
#SBATCH --output=$G/guardian-%j.out
#SBATCH --error=$G/guardian-%j.err
set -Eeuo pipefail
bash "$G/watch-after-97576.sh"
EOF
chmod a-w "$BATCH"
if [[ -n "$DEPENDENCY" ]]; then
    RESULT="$(sbatch --parsable "$DEPENDENCY" "$BATCH")"
else
    RESULT="$(sbatch --parsable "$BATCH")"
fi
ID="${RESULT%%;*}"
[[ "$ID" =~ ^[0-9]+$ ]] || {
    echo "SLURM_SUBMIT_RETURNED_UNEXPECTED_RESULT: $RESULT" >&2; exit 25;
}
printf '%s\n' "$ID" > "$G/guardian-job-id.txt"
echo "FALLBACK_GUARDIAN_SUBMITTED $ID dependency=${DEPENDENCY:-immediate-after-terminal}"
echo "NO_FSI_JOB_NOW; ONLY_GUARDIAN_SUBMITTED"
