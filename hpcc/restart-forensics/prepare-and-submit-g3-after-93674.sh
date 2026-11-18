#!/usr/bin/env bash
# Nonproduction 20-window G3 pilot: physical 0.03550 -> 0.03800.
# Preserves G1 1% strict scientific FAIL; G2 93674 source must independently
# pass native, accepted same-physical-time Fx and Delta0/2 strict 1% checks.
# --preflight default: no sbatch, only read source and download pinned scripts.
# --submit explicit: one isolated Slurm job, never auto-chain another stage.
set -euo pipefail
ACTION="${1:---preflight}"
if [[ "$#" -gt 1 || ( "$ACTION" != "--preflight" && "$ACTION" != "--submit" ) ]];then
  echo "Usage: bash prepare-and-submit-g3-after-93674.sh [--preflight|--submit]" >&2
  exit 2
fi
BASE="$HOME/hpcc-fsi"
ROOT="$BASE/crossjob-fix-20261116"
REV="49bb2e5871fcdea6c9e46d61b0c42273a63f45cf"
CODE="$ROOT/g3-pilot-$REV"
RAW="https://raw.githubusercontent.com/merlin959595/seagrass-fsi-hpcc/$REV"
PARENT="$ROOT/delta-continuation/trial-93674"
RESULT="$PARENT/DELTA_CONTINUATION_RESULT.json"
G1="$ROOT/delta-continuation/trial-92479/DELTA_CONTINUATION_RESULT.json"
for f in "$RESULT" "$G1" "$PARENT/FSI_SEGMENT_RESULT.json";do
  test -s "$f" || { echo "BLOCKED: required result missing $f" >&2;exit 3; }
done
python3 - "$RESULT" "$G1" <<'PY'
import json,sys
g2=json.load(open(sys.argv[1]))
g1=json.load(open(sys.argv[2]))
must=(g2.get("status")=="G2_DIAGNOSTIC_BOUNDED_PASS_NOT_PRODUCTION"
 and g2.get("original_strict_1pct_science_pass") is True
 and g2.get("native_mechanical_pass") is True
 and g2.get("scientific_vs_91543",{}).get("status")=="PASS"
 and g2.get("diagnostic_g2_only") is True
 and g2.get("production_approved") is False
 and g2.get("NEVER_AUTO_QUEUE_NEXT_STAGE") is True
 and abs(float(g2.get("end_t",-1))-.0355)<1e-9
 and g2.get("windows")==2
 and g1.get("status")=="DELTA_CONTINUATION_SHORT_STAGE_FAIL")
print("G2_93674_NATIVE_AND_STRICT_SCIENCE_PASS:",must)
print("G1_ORIGINAL_SCIENTIFIC_FAIL_RETAINED:",g1.get("status"))
if not must:raise SystemExit("BLOCKED: G2 and original G1 reports inconsistent")
PY
echo "===== 91543 reference coverage for future 20 windows ====="
python3 - "$BASE" <<'PY_REFERENCE'
from pathlib import Path
import sys,math
ref=(Path(sys.argv[1])/"three-day-proven/long-job-91543/runs/hpcc-implicit-002/solid/"
     "precice-Solid-watchintegral-Interface-Integral.log")
if not ref.is_file():raise SystemExit("BLOCKED: 91543 continuous watch missing")
times=set()
for line in ref.read_text(errors="replace").splitlines():
    p=line.split()
    if len(p)<7:continue
    try:
        vals=[float(x) for x in p[:7]]
    except ValueError:continue
    if all(math.isfinite(x) for x in vals):times.add(round(vals[0],9))
need=[round(.0355 + i*.000125-.0025,9) for i in range(21)]
missing=[x for x in need if x not in times]
if missing:
    raise SystemExit(f"BLOCKED: 91543 lacks {len(missing)} G3 reference checkpoints; first missing rel t={missing[0]}")
print("G3_REFERENCE_COVERAGE_PASS",len(need),"consecutive reference samples")
PY_REFERENCE
mkdir -p "$CODE"
# Pin all four exact Git blob SHA-1 values to the already reviewed REV.
# Reuse only byte-for-byte verified files from a previous interrupted attempt.
git_blob_sha1() {
  python3 - "$1" <<'PY_BLOB'
import hashlib,sys
from pathlib import Path
p=Path(sys.argv[1])
b=p.read_bytes()
print(hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest())
PY_BLOB
}
for spec in \
 "hpcc/restart-forensics/delta-continuation.py:delta-continuation.py:34d214a58fea571b0fa86facf9e163b1a1c4274c" \
 "hpcc/restart-forensics/run-delta-continuation-container.sh:run-delta-continuation-container.sh:6fe3f7169a6bd6a4dd08e026a71b0be6bcb355ea" \
 "hpcc/restart-forensics/submit-delta-continuation-short.sh:submit-delta-continuation-short.sh:d860072b83b7ea3e17cddfcbbeda7c4fa9fd1a93" \
 "hpcc/clean-production/segment.py:segment.py:15a219c75a7e417d707549c2a0e46bbebd761d19";do
  IFS=: read -r remote name expected_sha <<< "$spec"
  dest="$CODE/$name"
  if [[ -e "$dest" ]];then
    if [[ ! -f "$dest" || "$(git_blob_sha1 "$dest")" != "$expected_sha" ]];then
      echo "BLOCKED: existing pinned file failed SHA-1 check: $dest" >&2
      exit 4
    fi
    echo "PINNED_CACHED_FILE_VERIFIED: $name"
    continue
  fi
  tmp="$(mktemp "$CODE/tmp.XXXXXXXX")"
  trap 'rm -f "$tmp"' EXIT
  echo "FETCH_PINNED: $name"
  if ! curl -fLsS --retry 5 --retry-delay 2 --retry-all-errors \
       --connect-timeout 15 --max-time 45 "$RAW/$remote" -o "$tmp";then
    echo "Raw GitHub unavailable; trying alternate GitHub endpoint" >&2
    if ! curl -fLsS --retry 5 --retry-delay 2 --retry-all-errors \
         --connect-timeout 15 --max-time 45 \
         "https://github.com/merlin959595/seagrass-fsi-hpcc/raw/$REV/$remote" -o "$tmp";then
      echo "BLOCKED: both GitHub download endpoints failed for $name; NO SBATCH" >&2
      exit 5
    fi
  fi
  if [[ "$(git_blob_sha1 "$tmp")" != "$expected_sha" ]];then
    echo "BLOCKED: pinned source SHA-1 mismatch for $name; NO SBATCH" >&2
    exit 6
  fi
  mv "$tmp" "$dest"
  trap - EXIT
  echo "DOWNLOADED_PINNED_SHA_VERIFIED: $name"
done
export FSI_DELTA_SCRIPT="$CODE/delta-continuation.py"
export FSI_DELTA_CORE="$CODE/segment.py"
export FSI_DELTA_RUNNER="$CODE/run-delta-continuation-container.sh"
export FSI_DELTA_SOURCE_WORK="$PARENT"
export FSI_DELTA_WINDOWS=20
export FSI_DELTA_DIAGNOSTIC_G2=0
export FSI_DELTA_G3_PILOT=1
echo "===== G3 strict new physical-time checkpoint and delta preflight ====="
bash "$CODE/submit-delta-continuation-short.sh" --preflight
if [[ "$ACTION" == "--preflight" ]];then
  echo "G3_PILOT_PREFLIGHT_PASS_NO_SBATCH"
  echo "PLAN=0.035500_to_0.038000,20_windows,STEP_6,NOT_PRODUCTION"
  exit 0
fi
echo "===== Submit 20-window nonproduction pilot only ====="
bash "$CODE/submit-delta-continuation-short.sh" --submit
echo "G3_PILOT_ONLY_NO_LONG_PRODUCTION_NO_AUTO_CHAIN"
