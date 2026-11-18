# 案例｜2026-11-16～17 三维海草 ALE–FSI 跨 Slurm 作业续算

**最新状态（2026-11-19）：G0 92264 两窗口严格 PASS；G1 92479 原生 20 窗口及检查点独立审计 PASS，但历史 1% Fx 判据仍 FAIL（最大 1.025275%）；G2 93674 两窗口原生和本段严格科学对照 PASS；G3 93691 实际完成全部 20/20 窗口，原生 `FSI_LONG_SEGMENT_PASS`，两参与者退出码均 0、终态网格 PASS，严格 Fx/Delta0/Delta2 科学验收全部 PASS。G3 正式状态 `G3_PILOT_20_WINDOW_PASS_NOT_PRODUCTION`、`production_approved=false`。接下来可准备 G4 80 窗口独立验证，但自动长程生产仍未放行。**

## 1. 模型与运行环境

- OpenFOAM.com v2512；preCICE 3.4.1；CalculiX 2.20；OpenFOAM adapter 1.4.0；CalculiX adapter 2.20.2
- UM HPCC Singularity 环境，Open MPI 5.0.7；流体 8 MPI ranks，结构 4 OpenMP threads
- 耦合：Parallel Implicit、IQN-ILS，时间步 Δt=0.000125 s
- 网格、物性、流动条件沿用原始海草算例，本事故不应通过重新划分网格来掩盖
- 源作业 91006：由物理 0.0025 s 起算，完成 240 接受窗口至物理 0.0325 s
- 连续参考作业 91543：不中断通过该物理时刻；正在运行时禁止修改、覆盖、取消
- 失败跨作业候选：91767、91819、91878；新方案：92264

## 2. 三种容易混淆的量

1. **物理时间**：接续点 0.032500 s，后两个窗口终点分别为 0.032625、0.032750 s。
2. **preCICE 相对时间**：原始 91006/连续 91543 的上述三点分别是 0.030000、0.030125、0.030250 s；新进程重置成 0、0.000125、0.000250 s。
3. **位移**：原方案交换绝对 Displacement，表面积分约 30；新方案交换每窗口的 DisplacementDelta，第一窗口积分约 0.1055。增量不能与绝对值直接比较。绝对总积分需要以源检查点位移积分为初值累加每个已接受窗口的增量。表面积分也不等于叶尖位移，不能证明所有接口节点逐点一致。

## 3. 失败的可追溯数据

### 物理 0.0325 s

| 案例 | 已接受 Fx/N | 位移积分 0 | 位移积分 2 |
|---|---:|---:|---:|
| 源 91006 | 0.0176638208 | 30.0624021 | -1.57777164 |
| 连续 91543 | 0.0176619213 | 30.0624087 | -1.57777234 |
| 失败 91878 初值 | 0（Force 未初始化） | 30.0624021 | -1.57777164 |

Force 未初始化不是唯一根因：初始化 Force 的 91819 仍产生相同类别的错误受力。

### 物理 0.032625 s，第一次原生流体求解

| 检查量 | 连续 91543 | 失败 91878 |
|---|---:|---:|
| 第一次 Mesh Courant max | 1.8095493183964e-5 | 0.12932920678317 |
| 第二次 pcorr GAMG 初始残差 | 0.31611287214121 | 0.20040800784761 |
| 第一次 p GAMG 初始残差 | 0.94098821879041 | 0.94543471884190 |
| 第一次**临时**流体 Fx / N | 11.154076549809 | 11.515278323918 |
| 窗口**已接受** Fx / N | 0.017880777427529 | 0.072198630905944 |
| 耦合迭代次数 | 22 | 29 |

首窗口 Fx 错误 303.78%；第二窗口失败 Fx=-0.120739062 N 对比连续 +0.0181010198 N，偏差 767.03%，且反号。第二窗口首次 MeshCo 虽恢复到约 2.61e-5，但受力未恢复，故不能只看 MeshCo。

91767/91819/91878 的首次 MeshCo、首次 pcorr 与临时 Fx 几乎一致，改变 Force 初始化或 purgeWrite 并未改变第一步的异常。**初始临时流体 Fx 约 11 N 在成功连续算例中也存在，不能把它和 0.018 N 已接受力比较。**

## 4. 自编跨作业代码的教训

- 旧阶段驱动只复制已有流体/结构磁盘检查点，就假设新 preCICE 会话等价于旧会话；哈希相等是必要检查，不是充分条件。必须验证新耦合接口的首次 ALE 更新及真实已接受轨迹。
- 旧绝对位移方案重新映射、覆盖已有变形流体的界面值。新会话坐标和 RBF 映射可能引入额外运动。该机制与首步异常相符，但旧态 mesh flux / oldPoints 也可能贡献，不能把它包装成唯一已证实根因。
- 原流体参考构形选项 true 与候选 false 不同。新方案同时对齐 Fluid、Solid 原始几何参考坐标；仍是一个新会话，不是旧 preCICE IQN 历史的原样复原。
- 早期验收错误地拿后两个窗口与同一个上一时刻 Fx 比，错误拒绝或错放行。现比较同一物理时间的**已接受** Fx。
- 新方案写出的 DisplacementDelta 为**单窗口增量**，必须与连续参考同一窗口的绝对位移差对比；不能直接和 30.x 的绝对积分比较。
- 任何单一 GitHub Actions 绿色状态、网格检查、退出码 0，都不能替代真实科学一致性验收。

## 5. 新候选：原始参考构形 + 增量位移

**工程方案**：新 Fluid 进程加载原检查点已有绝对 pointDisplacement，Coupling 只传递当窗口的 DisplacementDelta；Fluid 适配器对原场做增量叠加，CCX 适配器使用当前 vold 与窗口开始检查点的差。Solid 参考坐标由原始网格注册 hook 恢复，Fluid 的 restartFromDeformed=false；Force 初始交换为 yes，DisplacementDelta 不初始化为旧绝对位移。所有变更仅在独立复制算例中进行。

代码：
- [初次 91006→92264 候选](../../hpcc/restart-forensics/try-incremental-displacement-restart.py)
- [独立两窗口提交](../../hpcc/restart-forensics/submit-incremental-displacement-2window.sh)
- [下一阶段通用 delta 续算驱动](../../hpcc/restart-forensics/delta-continuation.py)
- [2/20 窗口独立提交](../../hpcc/restart-forensics/submit-delta-continuation-short.sh)
- [compute 容器运行入口](../../hpcc/restart-forensics/run-delta-continuation-container.sh)

**92264 第一个窗口的用户实测**：

| 指标 | 连续 91543 | 新增量 92264 |
|---|---:|---:|
| 首次 MeshCo max | 1.8095493183964e-5 | 1.8086590122887e-5 |
| 0.032625 s 已接受 Fx/N | 0.0178807774 | 0.0177932299 |
| 已接受位移 0 积分增量 | 0.1055088 | 0.105507194 |
| 已接受位移 2 积分增量 | -0.00818846 | -0.00818638042 |

首次 MeshCo 与连续计算只差约 0.049%，已接受 Fx 相对误差约 0.49%，第一窗口的位移增量也高度一致。这证明**第一个窗口明显改善**，不证明第二窗口、下一次跨作业或长程生产已经成功。

## 5.1 G0 完整真实报告更新（2026-11-17，由 HPCC 终端提供）

作业 **92264**：HPCC 终端明确给出 `G0_REPORTED_STATUS: INCREMENTAL_DISPLACEMENT_TWO_WINDOW_PASS`，`NATIVE_STATUS: FSI_LONG_SEGMENT_PASS`。其已接受 `precice-Solid-watchintegral` 对照为：

| 物理时刻 | 连续 91543 Fx/N | 92264 Fx/N | Fx 相对误差 |
|---|---:|---:|---:|
| 0.032625 s | 0.0178807774 | 0.0177932299 | 0.48961797% |
| 0.032750 s | 0.0181010198 | 0.0182393924 | 0.76444643% |

**增量位移的正确检验**（与 91543 对应窗口的绝对位移积分**之差**比较，不是与绝对积分直接比）：

| 时间窗口 | 92264 Delta0 | 91543 绝对 Disp0 窗口差 | Delta0 相对误差 | 92264 Delta2 | 91543 绝对 Disp2 窗口差 | Delta2 相对误差 |
|---|---:|---:|---:|---:|---:|---:|
| 窗口 1 | 0.105507194 | 0.1055088 | 0.001522% | -0.00818638042 | -0.00818846 | 0.025396% |
| 窗口 2 | 0.105468159 | 0.1054706 | 0.002314% | -0.00814644011 | -0.00815329 | 0.084014% |

此前已核验新方案首个 MeshCo=1.8086590122887e-5，与 91543 同物理时刻首个 MeshCo=1.8095493183964e-5 的相对差约 0.049%。最后的 PASS 记录为原生结果和科学对照提供了结束证据。**未见完整 `sacct` 完成状态；`squeue` 提示 `slurm_load_jobs error: Invalid job id specified` 表明旧 ID 不再被当前队列识别，不应据此推断计算失败。**

**G1 只读预检已成功**：
`DELTA_CONTINUATION_SHORT_STAGE_OFFLINE_SELFTEST_PASS`；
`DELTA_CONTINUATION_PREFLIGHT_PASS source .../trial-92264 from 0.03275 to 0.03525 structural_restart_step 4 windows 20`；
`SOURCE_CHECKPOINT_APPROVED_NO_SBATCH`；
`G1_PREFLIGHT_PASSED_NOT_SUBMITTED`。
已冻结下一阶段代码于 HPCC 目录 `~/hpcc-fsi/crossjob-fix-20261116/delta-next-a0681df79291f7f1e71b1e408891386b8c644ce0`。该任务尚未提交；不能标注 G1 PASS。

## 6. 严格的后续验收关卡

### G0｜初次两窗口 92264
- 必须提供 Slurm sacct 完成状态、两个参与者退出码、两次已接受真实窗口、native checkMesh 终态 PASS。
- 最终 INCREMENTAL_DISPLACEMENT_RESULT.json 状态必须为 INCREMENTAL_DISPLACEMENT_TWO_WINDOW_PASS。
- 两次 Fx 对应连续参考误差均不超过 1%，同时逐窗口 DisplacementDelta 0、2 相对于连续参考位移增量的误差均不超过 1%。
- 第一条 native MeshCo 相对正常 91543 不超过 10 倍；全程 Courant/网格守卫通过。
- **G0 真实两窗口 PASS，详见上方 5.1；G1 仍待真实提交和计算。**

### G1｜跨新进程接 20 窗口
- 仅 G0 全部通过后，执行新脚本只读 --preflight；若自动拒绝便停止。
- 物理 0.03275→0.03525 s；CalculiX READ STEP 从 3→4。
- 新程序沿用整个 Delta 数据协议，不退回绝对 Displacement，也不修改 mesh/physics。
- 20 次已接受 Fx 和 Delta0/2 与 91543 对应窗口逐个比较 ≤1%，两侧退出码 0，网格全程通过。
- 未通过时不触发后续任务。

### G2｜从 G1 的终态再次跨 Slurm 作业
- G1 成功后，再以其报告和新的 fluid/solid 检查点启动 2 窗口短任务。
- 证明第**二次**换作业时 delta 参考位移正确更新，没有重复累加、遗漏、突然归零或峰值错轨。
- 与连续 91543 对应窗口再核对受力、结构增量、MeshCo。

### G3｜长程分段生产
- G0、G1、G2 依次通过后，才另行建设 80～960 窗口的生产调度和周期性自动接力。
- 生产全程必须保留每个阶段的输入哈希、原始网格参考、固体 .rout/HHT 文件和所有 8 MPI 的同时间检查点，并保留实际计算证据。
- 当物理时间超过 91543 已计算的区间，需要专门的无参考科学校验策略，不能伪造 91543 的未来受力数据。
- 任务结束条件必须 fail closed，绝不把单窗口正常写成「已完全修复」。

## 6.1 G1 真实 Slurm 提交记录（2026-11-17）

用户在 HPCC 登录节点执行了冻结版本的 `submit-delta-continuation-short.sh --submit`。终端实际输出：

```text
DELTA_CONTINUATION_SHORT_STAGE_OFFLINE_SELFTEST_PASS
DELTA_CONTINUATION_PREFLIGHT_PASS source .../trial-92264 from 0.03275 to 0.035250000000000004 structural_restart_step 4 windows 20 NO_SBATCH_NO_SOURCE_WRITES
SUBMITTED_SINGLE_SHORT_DELTA_JOB=92479
REPORT=/home/mc55028/hpcc-fsi/crossjob-fix-20261116/delta-continuation/trial-92479/DELTA_CONTINUATION_RESULT.json
NO_AUTO_CHAIN_NO_LONG_PRODUCTION
```

这只说明 **Slurm 提交成功且预检通过**，不证明作业已经运行、20 窗口全部接受或物理等价。下次继续应检查 `squeue -j 92479`、`sacct -j 92479`、`STATE.json`、`FSI_SEGMENT_RESULT.json`、`DELTA_CONTINUATION_RESULT.json`，并读取与 `91543` 20 个物理时间点匹配的 Fx/Delta0/Delta2。尤其必须检查第二次跨作业重新初始化的首次 MeshCo。

目前没有新的 Slurm 状态或原生结果证据，**不得擅自改成 G1 PASS、不得自动提交 G2**。

## 6.2 G1 运行中里程碑：第二次跨作业接续已接受前三窗口

用户 HPCC 登录节点提供实时状态：

```text
92479 cpu fsi-delt mc55028 R 7:18 cpu-40-19
STATE.json: {"status":"RUNNING","stage":1,"restart_from_time_s":0.03275,"final_time_s":0.035250000000000004}
DELTA_CONTINUATION_RESULT.json: 尚未生成
```

新会话的初始化 `Force0 = 0.0182393924 N`，与上一段 92264 的第二窗口最终受力完全一致；`DisplacementDelta0/1/2=0`。迄今已接受：

| preCICE 相对时间 (s) | 全局物理时间 (s) | 92479 已接受 Fx (N) | Delta0 积分 | Delta2 积分 |
|---|---|---:|---:|---:|
| 0.000125 | 0.032875 | 0.0181957756 | 0.105424308 | -0.00811174060 |
| 0.000250 | 0.033000 | 0.0188509445 | 0.105380443 | -0.00806826009 |
| 0.000375 | 0.033125 | 0.0188223670 | 0.105337414 | -0.00801276540 |

**这证实 G1 新会话启动、原生求解持续接受至少三个窗口，但不能从几个正常积分值推导 20 窗口的全部科学一致性。** 该终端输出并未显示 91543 相同时刻 Fx、Delta0/2，也没有 G1 首次 MeshCo 或最终 checkMesh/退出码。需待真实结果再判断、不得自动提交 G2。

## 6.3 G1 全 20 窗口已汇总，1% 科学门槛边缘失败（2026-11-18）

用户从真实 HPCC `DELTA_CONTINUATION_RESULT.json` 输出：

```text
G1: DELTA_CONTINUATION_SHORT_STAGE_FAIL
科学对照: FAIL
最大 Fx 误差: 0.010252751525572316
最大 Delta0 误差: 5.4627645726802694e-05
最大 Delta2 误差: 0.0009584332019428214
首次 MeshCo: {
  physical_time_s: 0.032875,
  91543_first_meshco: 1.7610256378009e-05,
  candidate_first_meshco: 1.7591253341998e-05,
  ratio: 0.9989209108826642,
  tenfold_first_native_meshco_pass: true
}
异常: None
```

结果意味着：
- Fx 最大相对误差 **1.025275%**，仅比预设的严格 1% 门槛多 **0.025275 个百分点**，这是原判定 FAIL 的直接原因。不能因为超限较小就改写原始结果。
- Delta0 相对误差最大约 **0.005463%**，Delta2 最大约 **0.095843%**，结构运动积分连续性良好。
- 首次 ALE MeshCo 比值 **0.998921**，与不中断对照非常接近；但首次值不能替代全程网格检查。
- `exception=None` 不等于已完整核实原生求解器退出码、检查点和 20 个原生已接受窗口。必须额外审核 `FSI_SEGMENT_RESULT.json`、`STATE.json`、八个 MPI 流体终态和结构 restart 快照。
- 用户另提到长距离作业已完成；其最终时间、Slurm 状态和对照数据未在这条输出中给出，因此不在此虚构其终态。

**新的分层结论**：G1 严格科学一致性仍 FAIL；只有本机核实 `FSI_LONG_SEGMENT_PASS`、双参与者退出码 0、终态网格 PASS、20 个真实接受窗口、以及初始化 Force/Delta 连续性，才能认定 **G1 的原生求解与接续结构通过**。此后可考虑再做一次短 G2 复测，但这不会把 G1 原来的 1% FAIL 改成 PASS。

### 独立复核与受控 G2 实施

新建代码：

- [G1 只读原生与 20 窗口复核](../../hpcc/restart-forensics/audit-g1-92479-for-g2.py)
- [受控 G2 两窗口提交入口](../../hpcc/restart-forensics/prepare-and-submit-g2-92479.sh)
- [增量续算驱动：加入独立审计、G2 诊断状态与不放行生产的隔离](../../hpcc/restart-forensics/delta-continuation.py)
- [Slurm 单段脚本和计算容器入口](../../hpcc/restart-forensics/submit-delta-continuation-short.sh)

**诊断启动的条件比单一 Fx 阈值更严格**：来源必须恰好为 92479、目标两个窗口；要求源原生状态 PASS、MPI/CalculiX 退出码零、mesh guard 和最终 native checkMesh PASS、结构 .rout 和 HHT 存在、八个处理器有一致终态、结构重启 step 和数据名一致；源初始 Force 必须与 92264 最后已接受 Force 一致，初始 Delta 为零；20 个同物理时间已接受窗口都能对照；首个 MeshCo 与连续 91543 的比值介于 0.8～1.2；逐窗口累计最大误差在额外设置的**仅限 G2 诊断**防护范围内（Fx ≤2%，Delta0/Delta2 各 ≤0.5%）。

**2% 并不是本轮回头修改的科学验收目标**，它只能放行一次“边缘误差是否会在下一次独立 Slurm 进程中继续扩大”的诊断试验。原来的 1% 仍标记 FAIL。G2 结果即使满足这项诊断防护，也只能写成 `G2_DIAGNOSTIC_BOUNDED_PASS_NOT_PRODUCTION`，不能直接作为后续长程生产来源。

后续生产需要建立正式的可重复性基线、并在至少一次再次跨作业试验后确定科学上可接受的力和位移误差；不可因改变判据而冒充严格验收成功。

## 6.4 G1 独立原生审计 PASS；G2 诊断提交成功（2026-11-18）

用户在 HPCC 执行固定版本的 `prepare-and-submit-g2-92479.sh --submit`，在提交前独立两次核验 G1：

```text
verdict=G1_NATIVE_PASS_G2_DIAGNOSTIC_ELIGIBLE_STRICT_SCIENCE_FAIL
g2_diagnostic_eligible=true
production_restart_approved=false
original_G1_result_was_rewritten=false
native_completed_successfully=true
restored_step_and_delta_protocol=true
initial_force_and_zero_delta_continuity=true
first_ale_meshco_near_continuous=true
all_twenty_same_physical_time_accepted=true
strict_preexisting_1pct_scientific_gate=false
diagnostic_only_2pct_Fx_0p5pct_delta_guardrail=true
original_Fx_scientific_FAIL_preserved=true
source_has_complete_8_rank_and_solid_checkpoint=true
source_checkpoint_physical_time_verified=true
native_status=FSI_LONG_SEGMENT_PASS
max_Fx_relative=0.010252751525572316
max_Delta0_relative=0.000054627645726802694
max_Delta2_relative=0.0009584332019428214
max_error_window=1, physical_t=0.032875
```

已通过来源检查：`0.03525 → 0.03550 s`、`structural_restart_step=5`、`windows=2`、`diagnostic_g2_only=True`。

真实 Slurm 提交反馈：

```text
SUBMITTED_SINGLE_SHORT_DELTA_JOB=93674
REPORT=/home/mc55028/hpcc-fsi/crossjob-fix-20261116/delta-continuation/trial-93674/DELTA_CONTINUATION_RESULT.json
G2_DIAGNOSTIC_ONLY=1
NO_AUTO_CHAIN_NO_LONG_PRODUCTION
ORIGINAL_G1_SCIENTIFIC_FAIL_NOT_OVERWRITTEN
```

**解释**：这证实 92479 原生数值计算、20 个窗口的时刻匹配、源物理状态检查点及接口初始化通过独立审计。严格 1% 力误差的原始 G1 FAIL 依旧有效。G2 的状态仅是 **已提交**，尚未收到 Slurm RUNNING/COMPLETED、两个新接受窗口、首个 MeshCo 或最终 `DELTA_CONTINUATION_RESULT.json`，不能宣称 G2 PASS，更不能自动启动长程生产。

**下一个安全操作**：读取 `squeue -j 93674`、`sacct -j 93674`，输出 `trial-93674/STATE.json`、`FSI_SEGMENT_RESULT.json`、`DELTA_CONTINUATION_RESULT.json` 以及对应 watchintegral 两行；只有原生/科学/网格/存档检查通过才安排下一生产级验证。

## 6.5 G2 93674 正在运行，尚无接受窗口（用户 HPCC 日志，2026-11-18）

Slurm 用户实测：

```text
JOBID=93674, partition=cpu, state=R, elapsed=2:01, node=cpu-72-1
STATE.json: RUNNING; restart_from_time_s=0.03525; final_time_s=0.0355
preCICE Solid watch:
Time Force0 Force1 Force2 DisplacementDelta0 DisplacementDelta1 DisplacementDelta2
0.00000000e+00 2.61982480e-02 -9.62249636e-10 -2.47877640e-03 0 0 0
FSI_SEGMENT_RESULT.json: 尚未生成
DELTA_CONTINUATION_RESULT.json: 尚未生成
```

这只能确认新 Slurm 作业已开始、耦合初始化数据存在；**目前 0/2 个窗口已被日志证明接受**。初始 Force0=0.026198248 N，需与 92479 最后一个真正接受的 Force0 对照确认连续性；零 Delta 是预期状态，不能单独证明网格或科学受力正确。不能将 RUNNING、存在初始化日志、无最终报告视为 G2 PASS。下一步只读检查首次原生 MeshCo、两窗口的真实接受日志、92479 源终态 Fx、最终网格检查及退出码。严格 1% 科学标准保持不变。

## 6.6 G2 作业 93674：第二次续算后再次跨作业的原生与严格科学双 PASS（2026-11-18）

用户在 HPCC 真实终态提供完整 `DELTA_CONTINUATION_RESULT.json` 和 watch integral，原生结果如下：

| 审核项 | 结果 |
|---|---|
| 实际物理时间 | 0.03525→0.03550 s；两个窗口均接受 |
| 状态 | `FSI_LONG_SEGMENT_PASS` |
| 流体与结构退出码 | `fluid=0`、`solid=0` |
| 迭代次数 | 总 53；单窗口最大 37 |
| 最大 fluid Courant | 0.26607930469009（≤0.5） |
| 最大 mesh Courant | 0.29157164410703（≤0.5） |
| 原生 mesh guard | 53 次，全程无记录异常，最小体积 2.588761332386e-11 m³ |
| 原生终态 checkMesh | `PASS`，但 JSON 未提取到最大非正交角度（`null`）；不能虚构数值 |
| 原始 G1 末次 Fx / G2 初始 Fx | 均为 `0.0261982480 N`，完全一致 |
| G2 初始 Delta0/1/2 | 均为 0 |
| 首次 MeshCo | G2 1.3705240974192e-05 vs 连续 91543 1.3693908947277e-05，比值 1.000827523 |
| 结构检查点哈希 | `rout=833eccd18f4a53a05ee6831ef982f11e5a6b724fc3574f444e17ff2ad2ddfa4a`、`kinematic=c3cad739883fa8305bafd780613624e34853275676ce4937a505709b7579e1df` |

真实已接受 Fx 对照：

| G2 全局物理时刻 | 93674 Fx / N | 91543 同时刻 Fx / N | 相对差 |
|---|---:|---:|---:|
| 0.035375 s | 0.0266170355 | 0.0266309841 | 0.052377% |
| 0.035500 s | 0.0270296953 | 0.0270413758 | 0.043195% |

`scientific_vs_91543.status=PASS`，最大 Fx 相对误差 **0.0005237733591677827（0.052377%）**，最大 Delta0 相对误差 **8.25711385365357e-06（0.000826%）**，最大 Delta2 相对误差 **0.0007798656656667879（0.077987%）**，都满足原来的每窗口 1% 科学门槛。

G2 原报告是 **`G2_DIAGNOSTIC_BOUNDED_PASS_NOT_PRODUCTION`**，同时包含 `native_mechanical_pass=true`、`original_strict_1pct_science_pass=true`、`bounded_2pct_diagnostic_pass=true`、`production_approved=false`、`NEVER_AUTO_QUEUE_NEXT_STAGE=true`。**不能据此直接称“所有长程重启零误差”或自动解锁生产。** G1 的严格 1% 超限未被重写；连续参考误差在 G2 两窗口回落，支持“无明显累积失控”的局部观察，但仍需更长段试跑以评估持续重复接续。

计算耗时：`wall_s=369.571` s，约 **184.786 s/窗口**；不是完整长期生产效率。原生数值的 `scientific_two_periods_verified=false` 指未验证两个湿动力振荡周期，不能与已经接受两个 preCICE 窗口混淆。

## 6.7 后续接力配置：G3 从 93674 再接 20 窗口（仅准备，未提交）

依据 93674 的真实原生与严格 1% 科学对照双 PASS，已配置新隔离的 **G3 20 窗口延长验证**：源物理时间 `0.035500 s`，目标 `0.038000 s`，下一 CalculiX `READ STEP=6`，仍为 8 流体 MPI + 4 结构 OMP、`dt=0.000125 s`、原几何/物性及 `DisplacementDelta` 协议。

- [G3 准备及受控提交入口](../../hpcc/restart-forensics/prepare-and-submit-g3-after-93674.sh) 默认为 `--preflight`，仅检查真实 `93674` 源报告与 8 MPI/结构检查点、源 Delta/Fx 数据、原始 G1 FAIL 状态；还需确认连续 `91543` 已接受日志具有下一段 20 窗口全部 21 个相对时间匹配点。缺失一项则拒绝提交。
- 新增量续算驱动 [delta-continuation.py](../../hpcc/restart-forensics/delta-continuation.py) 只允许来自固定真实 G2 `trial-93674` 的 20 窗口非生产验证，逐窗口继续严格 Fx、Delta0、Delta2 各不超过 1%，不复用 G2 的 2% 宽松诊断边界。
- 通过时只能写 `G3_PILOT_20_WINDOW_PASS_NOT_PRODUCTION` 且 `production_approved=false`；失败则写 `G3_PILOT_20_WINDOW_FAIL`。不能自动提交 G4 或三天长期链，不能覆写此前 `91006`、`91543`、`92264`、`92479`、`93674`。
- 现阶段没有 G3 Slurm 作业号或真实运行结果，故本段**尚未启动**。一切新结论必须等待原生 FSI 和逐窗科学验收。

## 6.8 G3 首次提交尝试遇到 GitHub HTTP 503（2026-11-18）

用户用 `prepare-and-submit-g3-after-93674.sh --submit` 进行 G3 提交前检查，HPCC 实际输出：

```text
G2_93674_NATIVE_AND_STRICT_SCIENCE_PASS: True
G1_ORIGINAL_SCIENTIFIC_FAIL_RETAINED: DELTA_CONTINUATION_SHORT_STAGE_FAIL
G3_REFERENCE_COVERAGE_PASS 21 consecutive reference samples
curl: (22) The requested URL returned error: 503
```

诊断：来源 G2 和不中断参考数据覆盖检查均 PASS；失败发生于下载固定源码的 `curl` 环节，**尚未进入下游 `sbatch`**，无新的 G3 Slurm 作业号。HTTP 503 是文件获取故障，不能当作 FSI 求解或 ALE 失效。已准备隔离恢复方案：下载使用有限次重试和备用 GitHub 端点；对固定 `49bb2e5...` 提交的四个源码文件硬编码真实 Git blob SHA-1，任何已缓存或新下载源码均须校验内容一致，缓存有效可直接复用，缓存不匹配会停止而非覆盖，双端点都不可用则停止不提交。

修复文件：[G3 带网络恢复和校验的入口](../../hpcc/restart-forensics/prepare-and-submit-g3-after-93674.sh)。这次仅改变下载可靠性，未改网格、物性、耦合算法或已有结果；应下载修复后的入口并重新执行 `--submit`，观察 `SUBMITTED_SINGLE_SHORT_DELTA_JOB` 确定真正成功提交，不能从预检通过自行推断作业已经提交。

## 6.9 G3 503 重试恢复成功，已提交 Slurm 93691（2026-11-18）

用户在 HPCC 登录节点重新运行修复后的 G3 提交入口，终端证据如下：

```text
G2_93674_NATIVE_AND_STRICT_SCIENCE_PASS: True
G1_ORIGINAL_SCIENTIFIC_FAIL_RETAINED: DELTA_CONTINUATION_SHORT_STAGE_FAIL
G3_REFERENCE_COVERAGE_PASS 21 consecutive reference samples
PINNED_CACHED_FILE_VERIFIED: delta-continuation.py
PINNED_CACHED_FILE_VERIFIED: run-delta-continuation-container.sh
FETCH_PINNED: submit-delta-continuation-short.sh
DOWNLOADED_PINNED_SHA_VERIFIED: submit-delta-continuation-short.sh
FETCH_PINNED: segment.py
curl: (22) The requested URL returned error: 503
DOWNLOADED_PINNED_SHA_VERIFIED: segment.py
DELTA_CONTINUATION_SHORT_STAGE_OFFLINE_SELFTEST_PASS
DELTA_CONTINUATION_PREFLIGHT_PASS source .../trial-93674 from 0.0355 to 0.038
    structural_restart_step 6 windows 20 diagnostic_g2_only False NO_SBATCH_NO_SOURCE_WRITES
SUBMITTED_SINGLE_SHORT_DELTA_JOB=93691
REPORT=/home/mc55028/hpcc-fsi/crossjob-fix-20261116/delta-continuation/trial-93691/DELTA_CONTINUATION_RESULT.json
G2_DIAGNOSTIC_ONLY=0
G3_20_WINDOW_PILOT_ONLY=1
NO_AUTO_CHAIN_NO_LONG_PRODUCTION
G3_PILOT_ONLY_NO_LONG_PRODUCTION_NO_AUTO_CHAIN
```

这次 GitHub HTTP 503 后通过**限定次数的网络重试**恢复，另有两份旧缓存通过固定 Git blob SHA 校验，四个固定计算脚本均被验证；预检、参考覆盖与来源通过，Slurm **确认提交 93691**。这证明网络错误恢复逻辑在真实环境中生效，并不证明 G3 的 20 个 FSI 时间窗口已经完成。

下一步只读检查作业 `93691` 的 `squeue`/`sacct`，以及其隔离目录中的 `STATE.json`、原生 `FSI_SEGMENT_RESULT.json`、`DELTA_CONTINUATION_RESULT.json`、首个 MeshCo 与接受积分。G3 只能在所有 20 个窗口、原生检查与同时间 Fx/Delta0/Delta2 各 ≤1% 的科学对照全部 PASS 时标记 `G3_PILOT_20_WINDOW_PASS_NOT_PRODUCTION`。不许默认继续自动长程链。

## 6.10 G3 作业 93691 已真实运行并接受 9/20 个窗口（用户 HPCC 最新日志）

```text
JOBID 93691; PARTITION cpu; NAME fsi-delt; ST R; TIME 13:55; NODE cpu-40-15
STATE.json: RUNNING, stage=1, restart_from_time_s=0.0355, final_time_s=0.038
accepted preCICE relative t: 0.000750, 0.000875, 0.001000, 0.001125
latest accepted physical t: 0.0355 + 0.001125 = 0.036625 s
latest accepted Force0: 0.0298741812 N
latest accepted DisplacementDelta0: 0.102951095
latest accepted DisplacementDelta2: -0.00857517046
FSI_SEGMENT_RESULT.json: 尚未生成
DELTA_CONTINUATION_RESULT.json: 尚未生成
```

通过最后一条已接受日志，G3 已推进 **9/20 窗口（45%）**，目标是物理 0.038 s；剩余 11 窗口。最后四个已接受 Fx 分别为 `0.0291376618`、`0.0294019930`、`0.0296650202`、`0.0298741812` N。近期 Fx 未出现旧重启问题的剧烈异常或变号，但不能由此推断与连续 91543 的**严格 ≤1%** Fx 差值全数通过；所贴日志没有给出 G3 第一步 MeshCo、最终原生质量及科学对照报告。

**操作提醒**：用户粘贴的长 Python here-doc 在 `PY  print(...)` 一带被截断，终端实际仍输出“尚未生成”，不影响正在运行的 Slurm FSI。后续保持 93691 运行、只读检查结果，不因 9 个窗口正常就启动 G4 或长程自动生产。科学验收应使用原生最终 JSON 的逐窗口 Fx、Delta0、Delta2 与完整网格质量。

## 6.11 G3 93691 已匹配全部 20 个 Fx 时间点，最大误差 0.054976%（2026-11-19）

用户在 HPCC 对 `trial-93691` 的 `precice-Solid-watchintegral-Interface-Integral.log` 与不中断参考作业 `91543` 运行只读 `awk` 对照，实际输出：

```text
已对照窗口: 20
当前最大 Fx 相对误差: 0.054976%
目前已对照窗口满足 1% Fx 门槛
```

该 `awk` 使用时间偏移 `0.033 s`（G3 起点物理 0.0355，参考作业原点 0.0025），按相对时间 9 位小数匹配，展示本段已接受 Force0 相对误差最大约 `5.4976e-4`。对 20 个点按原定 1% **Fx** 指标观察，全部满足。本结果**不是最终报告**，不包含 Delta0、Delta2 或全程 mesh guard/原生退出码/最终 CheckMesh 的直接验收证据，不可自行宣告 `G3_PILOT_20_WINDOW_PASS_NOT_PRODUCTION`。需要读取 `trial-93691/FSI_SEGMENT_RESULT.json` 与 `DELTA_CONTINUATION_RESULT.json` 核查全套 PASS 后，才能开始下阶段长段生产级验证；尤其原 G1 的 1.025275% 超限仍需保留。

## 6.12 G3 作业 93691 正式原生及严格科学验收通过（2026-11-19）

用户从 HPCC 源文件直接读取如下最终报告，而非仅凭之前的 awk 对照：

```text
native status: FSI_LONG_SEGMENT_PASS
accepted_windows: 20
participant_exit_codes: {"fluid":0,"solid":0}
native_terminal_mesh.status: PASS
native_terminal_mesh.max_nonorthogonality_deg: null
scientific_vs_91543.status: PASS
max_Fx_relative_error: 0.0005497641496844777  (0.05497641496844777%)
max_delta0_relative_error: 5.1779075974898424e-05 (0.005177907597489842%)
max_delta2_relative_error: 0.0007981449629633493 (0.07981449629633493%)
DELTA_CONTINUATION_RESULT.status: G3_PILOT_20_WINDOW_PASS_NOT_PRODUCTION
exception: null
production_approved: false
```

这证实了 G3 整个 20 窗口区间 `0.0355→0.0380 s` 的真实 FSI、终态网格与逐窗科学对照通过。并未给出最大非正交角的数值（JSON 为 null），不可自行推断。

`sacct -j 93691` 在登录节点返回 `localhost:6819 Connection refused`，这是 Slurm 记账数据库连接异常，不等于作业 FAILED；因此目前不能声称已核实 SlurmDB 的 `COMPLETED` 记账状态。原生两个参与者退出码均为 0 及 FSI 官方原生日志是独立的计算结果证据。

仍然**不改写 G1 92479 的历史 FAIL**，亦不将 G3 的非生产 `production_approved:false` 改成 true。下一阶段应设计受控的 **80 窗口 G4（物理 0.038→0.048 s）**，必须先核实 91543 参考覆盖、全部 8 MPI 检查点、CalculiX 下一个 restart step=7、网格和接口协议；不同于已验证的 20 窗口，长段还需新的真实运行证据才能判定安全。

## 7. 只读证据与公开源码

- [原取证详细记录](../../hpcc/restart-forensics/OUR-RESTART-FIX-20261116.md)
- [原生流体首时间步对照程序](../../hpcc/restart-forensics/audit-91819-continuous-vs-restart-first-pressure-readonly.py)
- [OpenFOAM adapter 1.4.0 增量位移读取](https://github.com/precice/openfoam-adapter/blob/v1.4.0/FSI/DisplacementDelta.C)
- [CalculiX adapter 2.20.2 增量写入](https://github.com/precice/calculix-adapter/blob/v2.20.2/adapter/PreciceInterface.c)

## 8. 归档要求

本文件是**带验收状态的经验复盘**。92264 的 G0 两窗口、93674 的 G2 两窗口均满足严格科学标准；92479 的 G1 原生通过而最大 Fx 严格 1% 科学标准未通过。可继续筹备长段独立验证，但不能据此将整个工作流标记为 RELEASED。应届时补充：作业 ID、sacct 完成时间、计算窗口数、每个阶段源码 commit、checkpoint SHA256、关键曲线与报告路径。不得因为本仓库 CI 自检 PASS 自动改变状态。
