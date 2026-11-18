#!/usr/bin/env bash
# ONE entry for REAL uninterrupted THREE-DAY job 91543, not 91006 or 93691.
# --inspect default: only read 91543 endpoint, G0-proven delta source files,
# checkpoint and proposed Slurm jobs. --submit: queue FULL verified SHA256
# backup first, then afterok-linked THREE-DAY FSI production segments.
set -euo pipefail
ACTION="${1:---inspect}"
if [[ "$#" -gt 1 || ( "$ACTION" != "--inspect" && "$ACTION" != "--submit" ) ]];then
  echo "Usage: bash backup-and-continue-91543.sh [--inspect|--submit]" >&2
  exit 2
fi
REV="4d332b9c69ddbe8f7670ab9b4f55236664980cb5"
REPO="merlin959595/seagrass-fsi-hpcc"
BASE="$HOME/hpcc-fsi"
CODE="$BASE/three-day-91543-code-$REV"
RAW="https://raw.githubusercontent.com/$REPO/$REV"
mkdir -p "$CODE"

git_blob_sha1() {
  python3 - "$1" <<'PY_HASH'
import hashlib,sys
from pathlib import Path
b=Path(sys.argv[1]).read_bytes()
print(hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest())
PY_HASH
}
for spec in \
  "hpcc/three-day-resume/inspect-91543.py:inspect-91543.py:9d13c7875a13de36f4dc43181078e3c3b40675db" \
  "hpcc/three-day-resume/backup-91543-full.py:backup-91543-full.py:21e8824c433f964d8db6b11e39a0136802cfaea3" \
  "hpcc/three-day-resume/resume-91543-delta.py:resume-91543-delta.py:1c268d3d8f64863afe2aa0d950f26ac64f74d6b6" \
  "hpcc/three-day-resume/run-91543-continuation-container.sh:run-91543-continuation-container.sh:93f7243ef47fbb05a7031862c641707d714a5bf2" \
  "hpcc/three-day-resume/submit-91543-continuation.py:submit-91543-continuation.py:36dcade7a7a617d54d63b1f073515856e55b97ae" \
  "hpcc/restart-forensics/try-incremental-displacement-restart.py:try-incremental-displacement-restart.py:07b24dbcba98b936942129057630754e65179b20" \
  "hpcc/clean-production/segment.py:segment.py:15a219c75a7e417d707549c2a0e46bbebd761d19";do
  IFS=: read -r remote name expected <<< "$spec"
  dest="$CODE/$name"
  if [[ -e "$dest" ]];then
    if [[ ! -f "$dest" || "$(git_blob_sha1 "$dest")" != "$expected" ]];then
      echo "BLOCKED_BAD_CACHED_CODE_HASH $dest" >&2
      exit 6
    fi
    echo "PINNED_CACHED_VERIFIED $name"
    continue
  fi
  tmp="$(mktemp "$CODE/download.XXXXXXXX")"
  trap 'rm -f "$tmp"' EXIT
  if ! curl -fLsS --retry 5 --retry-all-errors --retry-delay 2 \
        --connect-timeout 15 --max-time 45 "$RAW/$remote" -o "$tmp";then
    curl -fLsS --retry 5 --retry-all-errors --retry-delay 2 \
       --connect-timeout 15 --max-time 45 \
       "https://github.com/$REPO/raw/$REV/$remote" -o "$tmp" || {
      echo "DOWNLOAD_FAILED_NO_BACKUP_OR_FSI_JOB_SUBMITTED $name" >&2
      exit 7
    }
  fi
  if [[ "$(git_blob_sha1 "$tmp")" != "$expected" ]];then
    echo "FROZEN_SOURCE_HASH_VERIFICATION_FAILED $name" >&2
    exit 8
  fi
  mv "$tmp" "$dest"
  chmod a-w "$dest"
  trap - EXIT
  echo "DOWNLOADED_AND_PINNED_VERIFIED $name"
done
python3 -m py_compile "$CODE/inspect-91543.py" "$CODE/backup-91543-full.py" \
  "$CODE/resume-91543-delta.py" "$CODE/submit-91543-continuation.py" \
  "$CODE/try-incremental-displacement-restart.py" "$CODE/segment.py"
bash -n "$CODE/run-91543-continuation-container.sh"
python3 "$CODE/resume-91543-delta.py" --self-test
echo "===== Read real 91543 checkpoint and Slurm status, NOT 91006 ====="
ARGS=()
if [[ "$ACTION" == "--submit" ]];then ARGS=(--submit);fi
BACKUP_ROOT="${FSI_91543_BACKUP_ROOT:-$HOME/hpcc-fsi-backups}"
EXTENSION="${FSI_91543_CONTINUE_SECONDS:-0.1}"
python3 "$CODE/submit-91543-continuation.py" \
  --base "$BASE" \
  --driver "$CODE/resume-91543-delta.py" \
  --core "$CODE/segment.py" \
  --runner "$CODE/run-91543-continuation-container.sh" \
  --inspector "$CODE/inspect-91543.py" \
  --patcher "$CODE/try-incremental-displacement-restart.py" \
  --backup-script "$CODE/backup-91543-full.py" \
  --backup-root "$BACKUP_ROOT" \
  --extend "$EXTENSION" "${ARGS[@]}"
