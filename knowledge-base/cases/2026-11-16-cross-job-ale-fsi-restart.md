# 案例｜2026-11-16～17 三维海草 ALE–FSI 跨 Slurm 作业续算

**状态：G0 双窗口 PASS；G1 跨 Slurm 作业 92479 已 RUNNING，最近一次实测已接受 3/20 窗口，但尚未完成真实数值验收。长程自动接力未放行。** 用户 HPCC 实际输出确认 92264 的 `INCREMENTAL_DISPLACEMENT_TWO_WINDOW_PASS`、原生 `FSI_LONG_SEGMENT_PASS`，且源检查点经增量续算驱动再次按 Fx、位移增量对照审核后给出 `DELTA_CONTINUATION_PREFLIGHT_PASS`。仅代表第一次两窗口跨进程恢复得到验证，不代表连续 20 窗口及再次跨作业重启已成功。GitHub CI 是离线程序自检，不替代真实 HPC 数据。

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

## 7. 只读证据与公开源码

- [原取证详细记录](../../hpcc/restart-forensics/OUR-RESTART-FIX-20261116.md)
- [原生流体首时间步对照程序](../../hpcc/restart-forensics/audit-91819-continuous-vs-restart-first-pressure-readonly.py)
- [OpenFOAM adapter 1.4.0 增量位移读取](https://github.com/precice/openfoam-adapter/blob/v1.4.0/FSI/DisplacementDelta.C)
- [CalculiX adapter 2.20.2 增量写入](https://github.com/precice/calculix-adapter/blob/v2.20.2/adapter/PreciceInterface.c)

## 8. 归档要求

本文件是**带验收状态的经验复盘**。目前 92264 两窗口已 PASS；只有后续 G1/G2 真实作业证据也确认无误，才允许把总体状态改成 RELEASED。应届时补充：作业 ID、sacct 完成时间、计算窗口数、每个阶段源码 commit、checkpoint SHA256、关键曲线与报告路径。不得因为本仓库 CI 自检 PASS 自动改变状态。
