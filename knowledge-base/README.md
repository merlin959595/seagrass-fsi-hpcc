# 科研计算经验库｜Research Computing Knowledge Base

这个目录专门保存**经过真实计算和原生日志核验的经验总结、故障复盘与可复用操作手册**。

与临时调试记录不同，这里的每份案例必须区分：**已证实事实 / 有证据的推断 / 未验证假设 / 修复方案的真实验收状态**。不把 Python 自检、GitHub Actions 通过或 `checkMesh` 通过写成物理 FSI 续算成功。

## 分类目录

- [**经验专栏 / Practical lessons**](experiences/README.md)：把真实修复结果提炼成可复用的技术经验。置顶：[三维海草 ALE–FSI 跨 Slurm 作业：增量位移修正、G0–G3 验收与三天 91543 全量备份续算交接](experiences/2026-11-19-seagrass-ale-fsi-restart-practice.md)。
- [问题复盘 / Case studies](cases/2026-11-16-cross-job-ale-fsi-restart.md)：2026-11-16 三维海草 FSI 跨 Slurm 作业续算问题。保留时间线、失败方案、首次 ALE 偏差证据、增量耦合修复候选与验收情况。
- [标准操作规程 / Playbooks](playbooks/delta-fsi-continuation.md)：未来类似流固耦合分段计算应如何审计、接续、验证和保护原有结果。
- [案例模板](templates/incident-template.md)：以后每一次重要数值模拟/HPCC 故障或修复都按统一格式记录。

## 状态规则

- **PROVEN**：与指定原生求解器/Slurm/耦合日志一致，指标与路径可追溯。
- **CANDIDATE**：已实现代码或小规模实验，但未满足完整真实验收。
- **BLOCKED**：必要的检查点、对照或测试尚未通过，不应提交下一段。
- **RELEASED**：短窗口、重复跨作业接续、长窗口与科学数据一致性均满足事先写明的验收门槛。

不要跨越验收层级。任何脚本默认只预检，后续 Slurm 提交必须显式选择，且**不能覆盖来源算例或仍在运行的作业**。

## 约束与检索约定

案例标题必须包含日期、研究对象和问题类型；涉及代码时标注仓库文件、版本与修改提交。必须写清物理时间 vs preCICE 相对时间、网格/物性是否改变、MPI/OMP/容器版本、结果证据以及可以复现实验的具体命令。

*此处归档的不是聊天讨论的全部猜测，而是经核验可复用的工程结论。*
