# 经验专栏｜已验证的科研计算故障修复与工程实践

这里存放**可独立阅读、可复用到下一次计算的经验文章**。与“事故时间线”不同，经验文章重点回答：问题为什么发生、哪些操作确实解决问题、哪些验收指标必须保留、下次遇到相同问题应如何做。

## 当前专栏

### 2026-11-19｜三维海草 ALE–FSI 跨 Slurm 作业接续（置顶）

**[从错误绝对位移重启到原始参考构形 + DisplacementDelta：真实验收、三天作业完整备份及续算交接](2026-11-19-seagrass-ale-fsi-restart-practice.md)**

包含：
- 旧重启 91767 / 91819 / 91878 的 ALE/受力失真与不能据以误判的临时力
- Force-only initial、OpenFOAM `restartFromDeformed false`、统一 `DisplacementDelta`、CCX restart/参考坐标的关键设置
- G0～G3 真实 HPCC 计算、原生与科学分层判定，特别保留 G1 的 1% 严格 FAIL
- 必须核对的 8 MPI、结构检查点、时间对应、ALE、Slurm、哈希以及 GitHub 503 恢复事项
- **真正的三天作业 91543**：完整 SHA-256 备份、实际末态审计、独立续算、后续聊天交接说明

**证据与实现链接**：[完整事故记录](../cases/2026-11-16-cross-job-ale-fsi-restart.md) · [增量续算旧阶段 SOP](../playbooks/delta-fsi-continuation.md) · [91543 专用备份续算入口](../../hpcc/three-day-resume/backup-and-continue-91543.sh)

## 发布标准

1. **PROVEN**：必须有真实 OpenFOAM、CalculiX、preCICE 和 HPCC 数据证据，标明对应物理时刻、作业 ID 和验收条件。
2. **CANDIDATE**：只完成脚本、离线 CI 或前期预检时不得称数值方案正式成功。
3. **BLOCKED**：缺失完整检查点、同步时间、全量备份或关键原生状态时不得自动推进。
4. **RELEASED**：必须明确整个长程工作流在用户指定范围内真实验收，不能用一个绿色 CI 代替。

文件应包括“已证实 / 未证实”“失败原因及边界”“固定版本源码”“操作前置条件”“失败即停止条件”“后续聊天交接”。此栏目不保存原始三天模拟的大型数据文件；大型计算数据须在超算中独立完整备份。
