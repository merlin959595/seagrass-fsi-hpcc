#!/usr/bin/env bash
# Read-only, low-cost status for uninterrupted three-day FSI.
set -euo pipefail
ROOT="$HOME/hpcc-fsi/three-day-proven"
SUB="$ROOT/long-job.submitted"
if [[ ! -r "$SUB" ]];then
  echo "没有找到已提交的三天任务。"
  exit 1
fi
JOB="$(sed -n 's/^JOB=//p' "$SUB")"
[[ "$JOB" =~ ^[0-9]+$ ]] || exit 2
WORK="$ROOT/long-job-$JOB"
echo "========== 三维真实FSI（三天长程段）=========="
printf 'Slurm内部作业: %s\n' "$JOB"
echo "已知基线: 已验证90873 t=0.0025s"
echo "预期终点: t=0.1625s (1280个耦合窗口)"
squeue -j "$JOB" -o "%.10i %.12T %.12M %.10l %R" || true
echo "========== 计算接受窗口（可能有写入缓冲）=========="
ITER="$WORK/runs/hpcc-implicit-002/solid/precice-Solid-iterations.log"
if [[ -s "$ITER" ]];then
  awk 'NR>1 && NF>=7 {accepted++;last=$0}
       END {printf "记录的已接受窗口 %d / 1280\n",accepted+0;
            if(accepted>0)print last;}' "$ITER"
else
  echo "尚未产生可确认的已接受窗口"
fi
echo "========== 最新物理时间与网格Courant =========="
if [[ -s "$WORK/fluid.log" ]];then
  grep -E '^Time = |Mesh Courant Number|SEAGRASS_MESH_GUARD' \
    "$WORK/fluid.log" | tail -n 12 || true
else
  echo "流体尚未写入启动日志"
fi
echo "========== 两端活跃/错误 =========="
for participant in fluid solid;do
  if [[ -s "$WORK/$participant.log" ]];then
    if grep -Ei 'FOAM FATAL|Floating point exception|solution seems to diverge|SIGFPE' \
       "$WORK/$participant.log" | tail -n 1;then :;fi
  fi
done
echo "========== 验收结果 =========="
if [[ -f "$WORK/THREE_DAY_RESULT.json" ]];then
  python3 - "$WORK/THREE_DAY_RESULT.json" <<'PY'
import json,sys
j=json.load(open(sys.argv[1]))
print("验证状态:",j.get("status"))
print("目标物理时间:",j.get("final_time_s_target"))
print("是否已有继续计算的成对检查点:",
  j.get("status")=="FSI_3DAY_PAIRED_RESTART_READY_NOT_RESUME_VALIDATED")
print("跨作业接力仍需重新验证（不会自动提交）")
PY
elif [[ -f "$WORK/STATE.json" ]];then
  cat "$WORK/STATE.json"
else
  echo "还未形成正式验证结论"
fi
