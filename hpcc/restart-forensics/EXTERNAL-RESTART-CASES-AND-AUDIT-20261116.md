# 跨 Slurm 作业 ALE–FSI 重启：公开案例与本工程已验证的问题（2026-11-16）

## 结论边界

- 对比对象：OpenFOAM.com v2512 + preCICE 3.4.1 + CalculiX 2.20 + OpenFOAM adapter 1.4.0；已验证连续 91543 vs 新 preCICE 会话 91767、91819、91878。
- 91878 两窗口分别迭代 29、25 次，preCICE Convergence=1，但已接受 Force0 分别 0.0721986309、-0.120739062 N；连续 91543 为 0.0178807774、0.0181010198 N。**物理连续性 FAIL**。
- 91819 与 91878 的 Force 初始化不同，接受力却几乎相同；保留 15 个历史目录的 91819 与少历史的 91767 也几乎相同，因而两因素不是充分根因。
- **明确自有脚本 bug**：早期 `audit-91878-ale-point-step-readonly.py` 使用 `.032375`/`.0325`，而实际目录 `0.032375`/`0.0325`，造成所有 8 个 MPI 分区的 `UNAVAILABLE`。已在本分支修正为解析实际数值目录，并回归测试；此前输出**不能用于判定原生 ALE 网格状态缺失**。
- `restartFromDeformed` 的影响是接口坐标注册方式，不仅仅是求解器参数。在 adapter 1.4.0 的 `Interface.C`，对于 faceNodes：`false` -> 当前点坐标**减去**已保存的 pointDisplacement；`true` -> 使用当前点坐标。两者必须与 CalculiX 的 `Solid-Mesh.coords` 定义一致，不能凭选项名字判断。
- OpenFOAM v2512 的 displacementLaplacianFvMotionSolver `curPoints()` 主要通过 `points0() + pointDisplacement` 形成当前网格。需要实际比较存档中的 polyMesh/points、pointDisplacement 和引用的 points0。
- 91543 与 91819 新会话首次在物理 0.032625s 的 Mesh Co 最大值 1.81e-5 vs 0.12933（都不是当窗口最后值），说明重启初始运动轨迹不同，但**不能独立证明哪个内存状态缺失**。
- 第一次未收敛 PIMPLE 力约 11 N 也在连续 91543 中存在，不应拿它与上一个已接受的 0.01766N 比较。旧解析器还将 Sum of moments 误认成力矩末次受力；这些自有审计错误均已修复。

## 已验证的公开教学与讨论

1. preCICE 官方计算例： https://precice.org/tutorials/perpendicular-flap/ 
   GitHub https://github.com/precice/tutorials/tree/develop/perpendicular-flap ，包含 OpenFOAM pimpleFoam、CalculiX 和 preCICE XML。**这是普通 FSI 耦合参考，不是已验证跨 Slurm 续算示例**。
2. preCICE 官方 CalculiX 重启指引（2026 年新增，页面自行声明“可能不完整或有误”）： https://precice.org/docs/adapters/calculix/configure/#restarting 。
   操作包括 `*RESTART,WRITE,FREQUENCY=1`，`*.rout -> *.rin`，`*RESTART,READ,STEP=n`；对接 OpenFOAM 的字段和时间基准仍要单独检查。2026-05-22 合并 https://github.com/precice/precice.github.io/pull/577
3. preCICE 官方 OpenFOAM adapter 配置：https://precice.org/docs/adapters/openfoam/config/ （restartFromDeformed）。
   源码核验：https://github.com/precice/openfoam-adapter/blob/v1.4.0/Interface.C
4. preCICE 社区 2025-12/2026-01 同一软件栈重启失稳：
   https://precice.discourse.group/t/instability-after-restart-in-coupled-fsi-simulation-openfoam-calculix-precice/2686
   该案例仍无确认修复，不能引用作为已验证解决方案。
5. Turek–Hron FSI 超算中断续算无法恢复案例：
   https://precice.discourse.group/t/turek-hron-fsi-with-openfoam-and-calculix/1001
   作者最终申请更长计算时间，没有证明跨作业修复。
6. preCICE 社区 restart 操作讨论：
   https://precice.discourse.group/t/restarting-coupled-fsi-simulation-with-precice/117
   关注节点坐标、RBF 映射、准牛顿历史，但不能不经本项目对照就改加速算法。
7. OpenFOAM v2512 原生 displacementLaplacian 源码：
   https://api.openfoam.com/2512/displacementLaplacianFvMotionSolver_8C_source.html

## 诊断优先顺序（不改第三方源码）

1. **先修复自有只读审计 bug**，复核 91006 最近两份真实网格状态及 91878 首两时间步；关注实际 X(t) 变化、点位移、`points0` 一致性。目录编码必须使用 0.0325 而非 .0325，或者解析浮点数匹配唯一目录。
2. 比较注册到 preCICE 的 Fluid-Mesh-Nodes、Fluid-Mesh-Faces 坐标与 CCX Solid-Mesh.coords，在是否减去绝对位移的两种参考形态下计算误差、法向/坐标轴、patch 顶点顺序。测试的是我们自己的数据/映射设置。
3. 核对 `*RESTART,READ,STEP=3` 与 `*.rout` 所对应的正确步骤，`*DYNAMIC` 时间、参考坐标、重启后第一步结构速度/加速度，不能只靠 SHA-256。
4. 比较原连续控制的第一个时间步 `pcorr`、p、phi、meshPhi、V0 及边界位移（同阶段比较）。是否有 in-memory FV motion state/oldTime 不一致目前仅是假设。
5. IQN-ILS 新会话无已积累 history 是已知数值差异来源，但不能仅凭迭代次数 29 vs 22 判定为物理力误差的根因。

**保护边界：**绝不修改 91543、91006，也不修改求解器/适配器第三方源码；无新计算提交；重启成功必须验证真实已接受的两窗 Fx 与参考 91543 同一物理时间比较。
