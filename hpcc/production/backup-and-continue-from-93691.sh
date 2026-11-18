#!/usr/bin/env bash
# One command: FULL backup of three-hour original 91006 and all G0-G3
# checkpoints, THEN dependent Slurm 3h production continuation from 93691.
# Default preflight is READ-ONLY; --submit opt-in queues backup + afterok chain.
set -euo pipefail
ACTION="${1:---preflight}"
if [[ "$#" -gt 1 || ( "$ACTION" != "--preflight" && "$ACTION" != "--submit" ) ]];then
  echo "Usage: bash backup-and-continue-from-93691.sh [--preflight|--submit]" >&2
  exit 2
fi
REV="4c28892b70eeef618ea1bfbd2a3ae31537d81dfd"
REPO="merlin959595/seagrass-fsi-hpcc"
ROOT="$HOME/hpcc-fsi"
CODE="$ROOT/production-code-$REV"
RAW="https://raw.githubusercontent.com/$REPO/$REV"
mkdir -p "$CODE"
git_blob_sha1() {
  python3 - "$1" <<'PY'
import hashlib,sys
from pathlib import Path
b=Path(sys.argv[1]).read_bytes()
print(hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest())
PY
}
for spec in \
 "hpcc/production/delta-production-3h.py:delta-production-3h.py:d1828c34f3564fd0316d13e15819066e1e907306" \
 "hpcc/production/backup-before-3h.py:backup-before-3h.py:a6683c3bd0897f3f7ddbf397a9128a3e4881c966" \
 "hpcc/production/run-production-3h-container.sh:run-production-3h-container.sh:251831a36e042ec8a74b0eb13563047be8d06615" \
 "hpcc/production/submit-3h-continuation.py:submit-3h-continuation.py:2da3d00167fd592269c46f2a40de23d645aa07d5" \
 "hpcc/clean-production/segment.py:segment.py:15a219c75a7e417d707549c2a0e46bbebd761d19";do
  IFS=: read -r remote name expected <<< "$spec"
  dest="$CODE/$name"
  if [[ -f "$dest" ]];then
    test "$(git_blob_sha1 "$dest")" = "$expected" || {
      echo "BLOCKED: cached file hash mismatch $name" >&2;exit 5;
    }
    echo "CACHED_PINNED_VERIFIED $name"
    continue
  fi
  temp="$(mktemp "$CODE/download.XXXXXXXX")"
  trap 'rm -f "$temp"' EXIT
  if ! curl -fLsS --retry 5 --retry-all-errors --retry-delay 2 \
      --connect-timeout 15 --max-time 45 "$RAW/$remote" -o "$temp";then
    curl -fLsS --retry 5 --retry-all-errors --retry-delay 2 \
      --connect-timeout 15 --max-time 45 \
      "https://github.com/$REPO/raw/$REV/$remote" -o "$temp" || {
      echo "BLOCKED: download unavailable; no backup or FSI submitted" >&2;exit 6;
    }
  fi
  test "$(git_blob_sha1 "$temp")" = "$expected" || {
     echo "BLOCKED: downloaded source hash mismatch $name" >&2;exit 7;
  }
  mv "$temp" "$dest"
  chmod a-w "$dest"
  trap - EXIT
  echo "DOWNLOADED_PINNED_VERIFIED $name"
done
python3 -m py_compile "$CODE/delta-production-3h.py" \
    "$CODE/backup-before-3h.py" "$CODE/submit-3h-continuation.py" "$CODE/segment.py"
bash -n "$CODE/run-production-3h-container.sh"
python3 "$CODE/delta-production-3h.py" --self-test
TARGET="${FSI_TARGET_PHYSICAL_S:-0.1625}"
BACKUP_ROOT="${FSI_BACKUP_ROOT:-$HOME/hpcc-fsi-backups}"
ARGS=()
if [[ "$ACTION" == "--submit" ]];then ARGS+=(--submit);fi
python3 "$CODE/submit-3h-continuation.py" \
  --base "$ROOT" \
  --driver "$CODE/delta-production-3h.py" \
  --core "$CODE/segment.py" \
  --runner "$CODE/run-production-3h-container.sh" \
  --backup-script "$CODE/backup-before-3h.py" \
  --backup-root "$BACKUP_ROOT" \
  --target "$TARGET" "${ARGS[@]}"
