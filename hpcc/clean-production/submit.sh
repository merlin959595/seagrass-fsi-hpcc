#!/usr/bin/env bash
# One-time clean fresh Slurm production submission.
# Use --count 6 (default) to prequeue 6 afterok segments, each up to 3 days.
# New canonical directories: ~/hpcc-fsi/seagrass-fsi-mainline/segment-A, -B...
# No source, results, mesh, or checkpoint data of 91006 are modified.
set -euo pipefail
BASE="$HOME/hpcc-fsi"
SOURCE="$BASE/clean-production-src"
ROOT="$BASE/seagrass-fsi-mainline"
NAME="seagrassFSI"
COUNT=6
if [[ "$#" -gt 0 ]]; then
  if [[ "$#" -ne 2 || "$1" != "--count" ]]; then
    echo "Usage: bash submit.sh [--count N], N=1..12" >&2
    exit 2
  fi
  COUNT="$2"
fi
if [[ ! "$COUNT" =~ ^([1-9]|1[0-2])$ ]]; then
  echo "Stage count must be from 1 through 12" >&2
  exit 2
fi
for path in "$SOURCE/segment.py" "$SOURCE/compute.sh" "$SOURCE/monitor.sh" \
            "$HOME/seagrass-fsi-ompi507-scotch-time.sif" \
            "$BASE/FSI_91006_RESUME_CERT.json"; do
  test -s "$path" || { echo "MISSING $path" >&2; exit 3; }
done
test ! -e "$ROOT" || {
  echo "CLEAN_MAINLINE_ALREADY_EXISTS; refusing to overwrite $ROOT" >&2
  exit 4
}
python3 -m py_compile "$SOURCE/segment.py"
bash -n "$SOURCE/compute.sh" "$SOURCE/monitor.sh"
if grep -Eq '__LIBPATH__|__PKGPATH__' "$SOURCE/compute.sh"; then
  echo "Unresolved environment placeholder; aborting" >&2
  exit 5
fi
python3 "$SOURCE/segment.py" --self-test
# A frozen checkpoint and a clean Slurm dependency graph do NOT establish
# numerical continuity across a new preCICE/CalculiX process.
# Until a separate real coupled restart has passed native force/mesh checks,
# never queue multi-day stage A-L jobs from 91006's t=0.0325 checkpoint.
PROOF="$BASE/FSI_CROSS_JOB_NATIVE_RESTART_PROOF.json"
if [[ ! -s "$PROOF" ]]; then
  echo "CROSS_JOB_CHAIN_BLOCKED: no native verified cross-process restart proof" >&2
  echo "Run an isolated 2-window test, then a longer restart comparison; do not change solvers." >&2
  exit 61
fi
python3 - "$PROOF" "$BASE" <<'PY_NATIVE'
import hashlib,json,math,pathlib,sys
proof=json.loads(pathlib.Path(sys.argv[1]).read_text())
base=pathlib.Path(sys.argv[2])
source=base/"fsi-long-stage0-job91006/runs/hpcc-implicit-002"
def require(cond,msg):
    if not cond: raise SystemExit("CROSS_JOB_CHAIN_BLOCKED: "+msg)
require(proof.get("status")=="FSI_CROSS_JOB_NATIVE_RESTART_PASS",
        "native cross-process continuity not certified")
require(proof.get("source_job")==91006 and
        abs(float(proof.get("restart_from_time_s",-1))-.0325)<1e-10,
        "wrong source job or physical time")
require(int(proof.get("verified_coupled_windows",0))>=20,
        "insufficient real coupled restart windows")
require(proof.get("participant_exit_codes")=={"fluid":0,"solid":0},
        "restart participants have not both exited normally")
require(proof.get("native_terminal_mesh_status")=="PASS",
        "native terminal mesh not checked")
for key,lim in (("max_mesh_Co",.5),("max_fluid_Co",.5),
                ("initial_force_rel_error",.1),("first_computed_force_rel_error",.2)):
    try: v=float(proof[key])
    except (KeyError,ValueError,TypeError): raise SystemExit(
        "CROSS_JOB_CHAIN_BLOCKED: missing "+key)
    require(math.isfinite(v) and 0<=v<=lim,"invalid numerical gate "+key)
h=hashlib.sha256
for key,path in (
    ("solid_rout_sha256",source/"solid/seagrass.rout"),
    ("solid_kinematic_sha256",source/"solid/kinematic_state.bin"),
    ("fluid_proc0_points_sha256",source/"fluid/processor0/0.0325/polyMesh/points")):
    require(path.is_file() and h(path.read_bytes()).hexdigest()==proof.get(key),
            "source checkpoint hash mismatch "+key)
print("CROSS_JOB_NATIVE_RESTART_PROOF_VALIDATED")
PY_NATIVE
python3 - "$BASE/FSI_91006_RESUME_CERT.json" <<'PY'
import json,sys
p=json.load(open(sys.argv[1]))
assert p["status"]=="FSI_91006_CONDITIONAL_RESTART_ELIGIBLE"
assert p["source_job"]==91006
assert p["next_step"]==3
assert p["native_terminal_checkMesh"]["status"]=="PASS"
assert p["evidence"]["accepted_windows"]==240
assert p["evidence"]["original_guard_failures"]==0
assert p["evidence"]["startup_exception"] is True
print("CERTIFIED_0P0325_CHECKPOINT_INPUT_PASS")
PY
python3 "$SOURCE/segment.py" --base "$BASE" --chain-root "$ROOT" \
  --stage 1 --previous-job 91006 --max-windows 960 --preflight-only
ACTIVE="$(squeue -h -u "$USER" -n "$NAME" -o '%j %T')" || {
  echo "Slurm queue lookup failed" >&2; exit 41; }
if [[ -n "$ACTIVE" ]]; then
  echo "Existing clean-mainline job detected, aborting duplicate" >&2
  echo "$ACTIVE" >&2
  exit 42
fi
# Check globally that nobody is already running a long seagrass FSI, even if
# named using the retired submission mechanism. Do not cancel other tasks.
OLD="$(squeue -h -u "$USER" -n fsi-real-long -o '%j %T')" || exit 43
if [[ -n "$OLD" ]]; then
  echo "Former FSI long-run jobs still queued. Refusing duplicate compute." >&2
  echo "$OLD" >&2
  exit 44
fi
umask 027
mkdir "$ROOT"
mkdir -p "$ROOT/bin" "$ROOT/logs"
cp "$SOURCE/segment.py" "$ROOT/bin/segment.py"
cp "$SOURCE/compute.sh" "$ROOT/bin/compute.sh"
cp "$SOURCE/monitor.sh" "$ROOT/bin/monitor.sh"
chmod a-w "$ROOT/bin/segment.py" "$ROOT/bin/compute.sh" "$ROOT/bin/monitor.sh"
(
 cd "$ROOT/bin"
 sha256sum segment.py compute.sh monitor.sh > SHA256SUMS
)
cat > "$ROOT/bin/run.sbatch" <<'SBATCH'
#!/bin/bash
set -euo pipefail
ROOT="$HOME/hpcc-fsi/seagrass-fsi-mainline"
test -s "$ROOT/bin/SHA256SUMS"
(cd "$ROOT/bin" && sha256sum -c SHA256SUMS)
test -n "$SEGMENT_LABEL"
test -n "$SEGMENT_INDEX"
test -n "$PARENT_JOB"
exec env -u BASH_ENV -u ENV /bin/bash --noprofile --norc \
  "$ROOT/bin/compute.sh" "$SEGMENT_LABEL" "$SEGMENT_INDEX" "$PARENT_JOB"
SBATCH
bash -n "$ROOT/bin/run.sbatch"
printf 'segment\tinternal_job_id\tprevious_internal_job_id\n' > "$ROOT/submissions.tsv"
previous=""
for ((i=1;i<=COUNT;i++));do
  printf -v LETTER '%b' "$(printf '\\x%02x' $((64+i)))"
  parent=91006
  if [[ -n "$previous" ]]; then parent="$previous"; fi
  opts=(--parsable --partition=cpu --nodes=1 --ntasks=1
        --cpus-per-task=12 --mem=24G --time=3-00:00:00
        --job-name="$NAME"
        --output="$ROOT/logs/segment-$LETTER-%j.out"
        --error="$ROOT/logs/segment-$LETTER-%j.err"
        --export="ALL,BASH_ENV=,ENV=,SEGMENT_LABEL=$LETTER,SEGMENT_INDEX=$i,PARENT_JOB=$parent")
  if [[ -n "$previous" ]];then
    opts+=(--dependency="afterok:$previous" --kill-on-invalid-dep=yes)
  fi
  if ! id="$(sbatch "${opts[@]}" "$ROOT/bin/run.sbatch")";then
    echo "PARTIAL_SUBMISSION_FAILURE_AT_SEGMENT=$LETTER" >&2
    echo "Prior queued work retained; see $ROOT/submissions.tsv" >&2
    exit 55
  fi
  printf '%s\t%s\t%s\n' "$LETTER" "$id" "$parent" >> "$ROOT/submissions.tsv"
  previous="$id"
  echo "已排入队列：计算段 $LETTER"
done
echo "CLEAN_FSI_CHAIN_SUBMITTED"
echo "CHECKPOINT=0.0325s; OLD_CASES_UNTOUCHED=YES"
echo "PROJECT=$ROOT"
echo "MONITOR=bash $ROOT/bin/monitor.sh"
echo "Automatic afterok continuation; any stage failure stops the chain."
