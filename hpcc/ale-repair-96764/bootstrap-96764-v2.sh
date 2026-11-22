#!/usr/bin/env bash
# One-command HPCC bootstrap for experiment 96764; never edit production cases.
# Usage: bash bootstrap-96764.sh [--submit|--preflight|--status]
set -euo pipefail
ACTION="--submit"
if [[ "$#" -gt 0 ]]; then ACTION="$1"; fi
if [[ "$#" -gt 1 || "$ACTION" != "--submit" && "$ACTION" != "--preflight" && "$ACTION" != "--status" ]]; then
  echo "Usage: bash bootstrap-96764.sh [--submit|--preflight|--status]" >&2
  exit 2
fi
P="/data/icto/$USER/seagrass-fsi558-runs.sNIpi9"
CODE="$P/repair-96764-github-20261122/code-v2"
mkdir -p "$CODE"

blob_sha() {
  python3 - "$1" <<'PY'
import hashlib,sys
b=open(sys.argv[1],"rb").read()
print(hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest())
PY
}

fetch_verified() {
  local path="$1" commit="$2" blob="$3" localname="$4"
  local dst="$CODE/$localname"
  if [[ -f "$dst" ]]; then
    [[ "$(blob_sha "$dst")" == "$blob" ]] || {
      echo "BLOCKED_UNEXPECTED_CACHED_SOURCE: $dst" >&2
      exit 7
    }
    echo "REUSED_VERIFIED $dst"
    return
  fi
  [[ ! -e "$dst" ]] || { echo "BLOCKED_PATH_EXISTS: $dst" >&2; exit 7; }
  local tmp
  tmp="$(mktemp "$CODE/download.XXXXXXXX")"
  trap 'rm -f "$tmp"' EXIT
  local url="https://raw.githubusercontent.com/merlin959595/seagrass-fsi-hpcc/$commit/$path"
  curl -fLsS --retry 5 --retry-all-errors --connect-timeout 15 --max-time 90 "$url" -o "$tmp"
  [[ "$(blob_sha "$tmp")" == "$blob" ]] || {
    echo "GITHUB_BLOB_HASH_MISMATCH: $path" >&2; exit 8;
  }
  mv "$tmp" "$dst"
  chmod a-w "$dst"
  trap - EXIT
  echo "DOWNLOADED_PINNED $dst"
}

# Pin precisely the reviewed repair controller and frozen, proven FSI core.
fetch_verified "hpcc/ale-repair-96764/repair96764.py" \
  "d19044a96b8075f65068b6b5847adc1d4853c119" \
  "65c116f4b351c2ad56515bb7ad57cf5caf0026a3" "repair96764.py"
fetch_verified "hpcc/clean-production/segment.py" \
  "1b08f9dabb6f3158891289bede0c7a00070340f7" \
  "15a219c75a7e417d707549c2a0e46bbebd761d19" "segment.py"

python3 -m py_compile "$CODE/repair96764.py" "$CODE/segment.py"
case "$ACTION" in
  --submit)
    python3 "$CODE/repair96764.py" --preflight
    python3 "$CODE/repair96764.py" --submit
    ;;
  --preflight)
    python3 "$CODE/repair96764.py" --preflight
    ;;
  --status)
    python3 "$CODE/repair96764.py" --status
    ;;
esac
