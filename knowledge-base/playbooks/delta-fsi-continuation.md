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

## D. 20 窗口新接续预检

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
