#!/usr/bin/env bash
# Human-readable FSI mainline monitor, hides Slurm's internal numeric job IDs.
set -euo pipefail
ROOT="$HOME/hpcc-fsi/seagrass-fsi-mainline"
MANIFEST="$ROOT/submissions.tsv"
if [[ ! -s "$MANIFEST" ]];then
  echo "Clean FSI mainline has not been submitted"
  exit 0
fi
echo "========== 三维海草真实FSI =========="
echo "已保留检查点：0.0325 s（独立认证，首个重启窗口有记录的Courant瞬态）"
echo "工程目录：$ROOT"
printf '%-12s %-17s %-16s %s\n' "计算段" "Slurm状态" "耦合窗口" "物理时间(s)"
tail -n +2 "$MANIFEST" | while IFS="$(printf '\t')" read -r letter job parent;do
  [[ -n "$letter" ]] || continue
  segment="$ROOT/segment-$letter"
  status="$(squeue -h -j "$job" -o '%T' 2>/dev/null | head -n1 || true)"
  if [[ -z "$status" ]]; then
    if [[ -f "$segment/STATE.json" ]];then
      status="$(python3 - "$segment/STATE.json" <<'PY'
import json,sys
try:
 s=json.load(open(sys.argv[1]))["status"]
 print(s)
except Exception:print("UNKNOWN")
PY
)"
    else
      status="NOT_IN_QUEUE"
    fi
  fi
  iter="$segment/runs/hpcc-implicit-002/solid/precice-Solid-iterations.log"
  n=0
  if [[ -s "$iter" ]];then
    n="$(awk 'NR>1 && NF>0 {n++} END {print n+0}' "$iter")"
  fi
  if [[ -s "$segment/FSI_SEGMENT_STAGE.json" ]];then
    info="$(python3 - "$segment/FSI_SEGMENT_STAGE.json" "$n" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
n=int(sys.argv[2])
print(f'{n}/{d["accepted_windows"]} {d["parent_time_s"]+n*d["dt_s"]:.6f}')
PY
)"
    read -r windows time_s <<< "$info"
  else
    windows="未开始"
    time_s="--"
  fi
  printf '%-12s %-17s %-16s %s\n' "$letter" "$status" "$windows" "$time_s"
done
echo "========== 已建立的计算段 =========="
active_found=0
for f in "$ROOT"/segment-*/STATE.json;do
  [[ -e "$f" ]] || continue
  active_found=1
  stage="$(basename "$(dirname "$f")")"
  printf '%s: ' "$stage"
  python3 - "$f" <<'PY'
import json,sys
s=json.load(open(sys.argv[1]))
print(s.get("status","UNKNOWN"),s.get("failure",""))
PY
done
if ((active_found==0));then echo "尚未建立计算段日志";fi
echo "内部Slurm编号留在submissions.tsv中，仅在排错时使用。"
