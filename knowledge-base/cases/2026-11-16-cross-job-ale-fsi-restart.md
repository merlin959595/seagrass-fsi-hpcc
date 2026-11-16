# 案例｜2026-11-16～17 三维海草 ALE–FSI 跨 Slurm 作业续算

**状态：CANDIDATE，未完全修复，不得启动自动长程接力。** 用户最后提供的 HPCC 日志显示作业 92264 仍 RUNNING，新方案已接受第一个耦合窗口，第二窗口和作业最终报告未提供。此状态须由真实计算记录更新，GitHub CI 不代表真实 FSI 验收。

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

## 6. 严格的后续验收关卡

### G0｜初次两窗口 92264
- 必须提供 Slurm sacct 完成状态、两个参与者退出码、两次已接受真实窗口、native checkMesh 终态 PASS。
- 最终 INCREMENTAL_DISPLACEMENT_RESULT.json 状态必须为 INCREMENTAL_DISPLACEMENT_TWO_WINDOW_PASS。
- 两次 Fx 对应连续参考误差均不超过 1%，同时逐窗口 DisplacementDelta 0、2 相对于连续参考位移增量的误差均不超过 1%。
- 第一条 native MeshCo 相对正常 91543 不超过 10 倍；全程 Courant/网格守卫通过。
- **目前只见首窗口日志，G0 不能宣称通过。**

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

## 7. 只读证据与公开源码

- [原取证详细记录](../../hpcc/restart-forensics/OUR-RESTART-FIX-20261116.md)
- [原生流体首时间步对照程序](../../hpcc/restart-forensics/audit-91819-continuous-vs-restart-first-pressure-readonly.py)
- [OpenFOAM adapter 1.4.0 增量位移读取](https://github.com/precice/openfoam-adapter/blob/v1.4.0/FSI/DisplacementDelta.C)
- [CalculiX adapter 2.20.2 增量写入](https://github.com/precice/calculix-adapter/blob/v2.20.2/adapter/PreciceInterface.c)

## 8. 归档要求

本文件是**带验收状态的经验复盘**。只有 92264 最终文件和后续 G1/G2 真实作业证据确认无误，才允许把状态改成 RELEASED。应届时补充：作业 ID、sacct 完成时间、计算窗口数、每个阶段源码 commit、checkpoint SHA256、关键曲线与报告路径。不得因为本仓库 CI 自检 PASS 自动改变状态。
