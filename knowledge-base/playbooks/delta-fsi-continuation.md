# 标准操作规程：以后所有三维海草双向 ALE–FSI 跨 Slurm 作业续算

**规则：默认先只读检查，不允许旧绝对位移方案自动接续。任何一步失败立刻停止，不得自动跳过科学验收。**

## A. 适用条件

- OpenFOAM.com v2512 + preCICE 3.4.1 + CalculiX 2.20、OF adapter 1.4.0、CCX adapter 2.20.2；如果升级版本，应重新审计接口数据语义。
- 源 Fluid 时间目录存在所有 8 个 MPI 一致的检查点，包含网格 points、U/p/phi、pointDisplacement 等；源 Solid 存在与同一时间匹配的 .rout、kinematic_state.bin 和原参考网格。
- 源检查点已经完成原生耦合、退出码 0、原生网格检查、科学对照；切勿只通过文件存在性判断源合格。
- 当前只允许 2/20 窗口短阶段；大于 20 窗口的生产规则尚未授权，需要再完成双重跨作业验收。

## B. 数据协议（最容易出错的一步）

- 旧 absolute Displacement 接口不得无验证地复制到新进程已经变形的 Fluid 快照中。
- 新跨作业会话的 Solid 端写 DisplacementDelta，Fluid 端读 DisplacementDelta 并对已有 pointDisplacement 累加。
- 两端均注册原始参考坐标，不得让 Solid 的参考网格和 Fluid 的目标网格处于不一致的形变参考框架。
- Force 使用已有接受值做初始交换；Delta 不接受被当作绝对位移的非零初始化。
- preCICE Relative 时间以新任务为零点；科学验收统一先转成全局物理时间。
- 第一个 PIMPLE provisional Force 与已接受 Force 绝不能互比。
- DisplacementDelta 每个窗口会重新从窗口初始位移开始计算；科学验收逐窗口比较 Delta 与连续绝对位移之差。

## C. 源作业 92264 的状态检查（只读）

在 HPCC 登录节点执行，**这不会提交新的计算**：

    JOB=92264
    BASE="$HOME/hpcc-fsi"
    W="$BASE/crossjob-fix-20261116/delta-2window/trial-$JOB"
    sacct -j "$JOB" --format=JobID,State,ExitCode,Elapsed -P
    cat "$W/STATE.json"
    test -f "$W/INCREMENTAL_DISPLACEMENT_RESULT.json" && \
      python3 -m json.tool "$W/INCREMENTAL_DISPLACEMENT_RESULT.json"
    tail -n 5 "$W/runs/hpcc-implicit-002/solid/precice-Solid-watchintegral-Interface-Integral.log"

确认：两窗口、0.03275 s、两个原生退出码零、最终网格 PASS、两次 Fx 及每窗口位移积分增量与 91543 同时间 1% 以内。

如无最终报告或状态非 PASS，停在这一步；不要临时篡改报告让下游通过。

## 2026-11-17 真实验收进展

G0 作业 92264 已收到最终 `INCREMENTAL_DISPLACEMENT_TWO_WINDOW_PASS` 与原生 `FSI_LONG_SEGMENT_PASS`。两个已接受 Fx 相对误差分别 **0.490% / 0.764%**，Delta0 的两窗相对误差约 **0.0015% / 0.0023%**，Delta2 约 **0.0254% / 0.0840%**。这证明 G0 合格，但仍不能直接宣布可三天自动接力。

G1 的只读预检已在 HPCC 实际通过，已下载并冻结用于下一阶段的代码：

    CODE="$HOME/hpcc-fsi/crossjob-fix-20261116/delta-next-a0681df79291f7f1e71b1e408891386b8c644ce0"

**历史提示：** 以下 20 窗口提交命令已在 2026-11-17 执行，真实作业号为 **92479**。它完成了 20 窗口的科学对照，但最大 Fx 误差 1.025275% > 原定 1%，因此最终原报告为 `DELTA_CONTINUATION_SHORT_STAGE_FAIL`，**不要重复提交这条旧 G1 命令**：

    FSI_DELTA_SCRIPT="$CODE/delta-continuation.py" \
    FSI_DELTA_CORE="$CODE/segment.py" \
    FSI_DELTA_RUNNER="$CODE/run-delta-continuation-container.sh" \
      bash "$CODE/submit-delta-continuation-short.sh" --submit

该历史作业的报告位于 `~/hpcc-fsi/crossjob-fix-20261116/delta-continuation/trial-92479/DELTA_CONTINUATION_RESULT.json`。原始严格 1% 科学门槛仍为 FAIL；下方新增针对该边缘失败的独立只读审核和**诊断性质的** G2 入口。

## 2026-11-18｜G1 受力边缘超限后的正确处理与 G2 诊断

G1 `92479` 的最终输出：严格科学 `FAIL`，最大 Fx 相对误差 1.025275%（超过 1% 约 0.025275 个百分点）；最大 Delta0/Delta2 误差 0.005463% / 0.095843%；首次 MeshCo 比值 0.998921，`exception=None`。这不是已证实的网格崩溃，也不意味着严格科学等价已经通过。

**先分开审查三个层级**：① 原生两个参与者、MPI 文件和结构检查点是否完整；② 首次 ALE、Force 初始化和逐窗 Delta 是否连续；③ 与 91543 的 1% 科学验收是否合格。第三项当前 FAIL，禁止修改旧结果或悄悄放宽标准。

为了测试这一小幅数值漂移是否会在**下一次真正独立的 Slurm 重启**继续扩大，已经准备了只允许从 92479 出发的两窗口 G2 诊断。使用固定 Git 提交的 [一次性预检与提交入口](../../hpcc/restart-forensics/prepare-and-submit-g2-92479.sh)，默认 `--preflight` 只读；即使显式 `--submit`，提交前也会强制执行独立 `audit-g1-92479-for-g2.py`。

- 如果 92479 的原生 `FSI_SEGMENT_RESULT.json`、20 窗口已接受数据、八个 MPI/CalculiX 检查点、第一次 MeshCo 和来源初始 Force 对照不能一致通过，则停止，不提交
- G2 诊断特别设置防止错误放大的启动护栏：Fx 误差不超过 2%，Delta0/2 各不超过 0.5%，MeshCo 与不中断对照比值在 0.8～1.2；**这些仅是选择短试验是否有意义的边界，绝不替代原 1% 科学验收**
- 允许的 G2 物理范围固定为 `0.035250 → 0.035500 s`，两耦合窗口；会从 92479 的结构最新检查点读取下一 restart step，不覆盖 G1
- G2 即使成功，结果也只能是 `G2_DIAGNOSTIC_BOUNDED_PASS_NOT_PRODUCTION`；长程生产自动接力仍被禁止，直到独立验证物理一致性并建立可解释的误差预算

HPCC 可用的执行命令（将以下长串固定 commit 替换为 GitHub 本案例实际确认版本；**不能用旧 G1 脚本替代**）：

```bash
FIX="$HOME/hpcc-fsi/crossjob-fix-20261116"
REV="e10fa97a7b5d1026867da47a5fa86190eca72c2b"
curl -fLsS \
  "https://raw.githubusercontent.com/merlin959595/seagrass-fsi-hpcc/$REV/hpcc/restart-forensics/prepare-and-submit-g2-92479.sh" \
  -o "$FIX/prepare-and-submit-g2-92479.sh"
bash "$FIX/prepare-and-submit-g2-92479.sh" --preflight
# 仅在预检通过、确实需要真实第三次独立 Slurm 验证时：
bash "$FIX/prepare-and-submit-g2-92479.sh" --submit
```

该命令不会自动修改 91543/92479/91006，也不会把源历史 `FAIL` 变成 `PASS`。如审核不通过，读取错误标签并修复真正的问题，不可用伪造状态文件绕过。

## D. 20 窗口新接续预检

优先使用 [单命令 G0 状态检查及 G1 只读准备脚本](../../hpcc/restart-forensics/prepare-g1-after-92264-readonly.sh)。它读取 92264 正式报告；若缺失或未通过，停止且不提交；若通过，会下载固定提交的后续代码副本并调用严格预检。**不会执行 sbatch。**



本仓库脚本预检是默认行为。**必须把同一 Git commit 下的脚本复制进 HPCC 的版本化独立代码目录，不要覆盖正在被其他作业使用的脚本。** 提交入口支持通过 FSI_DELTA_SCRIPT、FSI_DELTA_CORE、FSI_DELTA_RUNNER 指向同一版本的冻结副本。

- hpcc/restart-forensics/delta-continuation.py
- hpcc/restart-forensics/run-delta-continuation-container.sh
- hpcc/restart-forensics/submit-delta-continuation-short.sh

以及同一 commit 里的 hpcc/clean-production/segment.py。先在当前 Shell 设置路径，例如：

    export FSI_DELTA_SCRIPT="$HOME/hpcc-fsi/crossjob-fix-20261116/delta-next-REV/delta-continuation.py"
    export FSI_DELTA_CORE="$HOME/hpcc-fsi/crossjob-fix-20261116/delta-next-REV/segment.py"
    export FSI_DELTA_RUNNER="$HOME/hpcc-fsi/crossjob-fix-20261116/delta-next-REV/run-delta-continuation-container.sh"

以下 D/E/F 中的同一份 submit-delta-continuation-short.sh 也应使用这个冻结版本；不要把已变动的 GitHub 工作分支脚本与旧的 container runner 混用。

随后执行：

    BASE="$HOME/hpcc-fsi"
    FIX="$BASE/crossjob-fix-20261116"
    bash "$FIX/submit-delta-continuation-short.sh" --preflight

只读预检会打开 92264 的正式 PASS 报告，检查所有源文件、八个 Fluid MPI 检查点、结构 restart step、preCICE 数据名和 Force-only initial 设置，并打印从 0.03275→0.03525 s、STEP 3→4 的接续计划。

预检失败不得提交。**“准备下一段”与“启动下一段”是两个不同动作。**

## E. 明确批准后只提交一次 20 窗口

只有 D 全部通过且确认资源预算时：

    bash "$HOME/hpcc-fsi/crossjob-fix-20261116/submit-delta-continuation-short.sh" --submit

脚本保留 immutable 源目录，给新作业创建独立 trial-NNNN 目录，固定并校验执行脚本 SHA，尽量避开 91543 的节点，采用 CPU 分区、12 CPU / 24 GB、3 小时资源预约，最多 20 窗口。**没有后续自动提交。**

查看新作业结果：

    sacct -j <new_job> --format=JobID,State,ExitCode,Elapsed -P

    python3 -m json.tool \
      "$HOME/hpcc-fsi/crossjob-fix-20261116/delta-continuation/trial-<new_job>/DELTA_CONTINUATION_RESULT.json"

**要求**：DELTA_CONTINUATION_SHORT_STAGE_PASS，同时其 FSI_SEGMENT_RESULT.json 的 native quality、exit codes 与实际输出相符。受力及 Delta0/2 每一窗口均要科学对照，不只是第一个窗口。

## F. 第二次跨作业复测

对 G1 合格的 trial-NNNN 结果先执行新一次只读预检：

    export FSI_DELTA_SOURCE_WORK="$HOME/hpcc-fsi/crossjob-fix-20261116/delta-continuation/trial-<G1_job>"
    export FSI_DELTA_WINDOWS=2
    bash "$HOME/hpcc-fsi/crossjob-fix-20261116/submit-delta-continuation-short.sh" --preflight

之后只在独立批准的前提下执行 --submit。须从 G1 的最新结构/流体状态继续，检查下一窗口 Force 与 Delta 没有重置或重复累计；仍不自动链式提交。

## G. 以后按此接续的硬约束

每个源作业必须 PASS 才是下一作业的 parent；保持原始参考构形与 Data 名一致。不得回到旧 absolute Displacement 的启动方式，不得修改原算例。没有同步时间点的科学参考时必须记录缺口并另立有效验收方法，不能伪造相似性。保留每段输入哈希、source/target 时间、checkpoint hashes、输出以及作业 Slurm 证据。长段运行必须在双重跨作业短测通过之后单独开发和放行。

## H. 常见失败与处理

- **没有结果文件**：可能仍在 RUNNING，也可能计算异常结束，先看 sacct 和日志；禁止生成假报告。
- **两个退出码正常但受力偏差大**：不能视为 PASS，应回到 Native ALE 首步、接口参考构形、Delta 映射与固体动态持久化诊断。
- **首次 MeshCo 正常，后面 Fx 错误**：依然不通过；排查错误是否留存在第一窗口末态。
- **第二次接力错误**：对比前段最后接受的 Force / D 与下一段初始 Force / Delta=0，检查窗口基准位移是否重新建立。
- **工程范围扩大/超过 20 窗口**：短阶段程序明确阻断，另行科研验收后再实现长阶段调度，不得悄悄放宽限制。
