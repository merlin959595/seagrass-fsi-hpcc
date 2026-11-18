# 经验总结｜三维海草 ALE–FSI 跨 Slurm 作业续算：从失真到增量位移接续

**日期：2026-11-19｜项目：UM HPCC OpenFOAM–preCICE–CalculiX 三维柔性海草｜类型：问题复盘 / 数值验证 / Slurm 续算 / 数据备份**

**状态声明**：G0～G3 的 `DisplacementDelta` 跨作业方案已经有真实 HPCC 原生/科学对照证据，**不能**把它等同于原三天作业 `91543` 已成功从真实末态继续。`91543` 最新物理时间、完整 SHA-256 备份状态、后续 Slurm 作业号仍待 HPCC 提供真实输出。G1 历史严格 1% Fx 超限也必须保留。详细逐次取证见[事故时间线](../cases/2026-11-16-cross-job-ale-fsi-restart.md)。

## 1. 事故现象：检查点存在，却不等于恢复了同一物理状态

已有真实连续 FSI 作业 `91543` 使用**绝对 `Displacement`** 接口。早期新 Slurm/新 preCICE 会话的跨作业重启（`91767`、`91819`、`91878`）虽然复制了 OpenFOAM 和 CalculiX 文件，重建接口后的首次 ALE 动作及已接受受力却与不中断参考严重偏离。

| 同物理时刻 0.032625 s | 不间断 `91543` | 旧失败候选 `91878` |
|---|---:|---:|
| 首次 Mesh Courant 最大值 | 1.8095493183964e-5 | 0.12932920678317 |
| **已接受** Fx（N） | 0.0178807774 | 0.0721986309 |
| Fx 相对偏差 | — | 约 **303.8%** |

下一窗口旧候选出现约 **−0.120739 N**，参考为 **+0.018101 N**，甚至反号。仅修正 Force 初始化、增加保留时间目录、或依赖 `checkMesh PASS` 和进程退出码都不足以保证科学一致。

**对原因的审慎表述**：重新初始化的接口/RBF 注册、绝对位移重新映射与已变形流体网格的参考构形不一致，是与真实失真数据相符的重要解释；旧 ALE 历史、映射及耦合迭代因素并未被完全逐一隔离，不能声称唯一根因已被数学证明。

最容易造成误判的一点：**第一轮临时/未接受的流体 Fx≈11 N**，在正确的不中断算例中也可能出现，不能直接拿它与上个窗口**最终接受**的 Fx≈0.018 N 比较。应逐窗口比较**已经收敛并接受**的力。

## 2. 修复方法：在原始参考构形上只传递窗口增量

通过实际修复验证的方案如下：

1. **流体保留原来的 ALE/位移检查点**，包括八个 MPI 分区的流动场、当前 `pointDisplacement`、`polyMesh/points`、时间目录和运动历史。新会话不能将已累积的绝对变形清零。
2. 新流体接口改为 `restartFromDeformed false;`，`readData (DisplacementDelta);`。OpenFOAM adapter 1.4.0 的增量读取把新值**叠加**到既有 `pointDisplacement`，与绝对 `Displacement` 的赋值语义不同。
3. **结构保留原始参考网格及内部运动状态**：`restart_reference/Solid-Mesh.coords`、`seagrass.rout`、`kinematic_state.bin`，以及实际一致的 CalculiX `*RESTART, READ, STEP=N`。CalculiX adapter 输出本窗口起始检查点到当前结构位移之间的 `DisplacementDelta`。
4. preCICE XML、OpenFOAM `preciceDict` 和 CalculiX `config.yml` 三处协议统一。**只允许 Force 交换 `initialize="yes"`，不对 `DisplacementDelta` 初始化发送整块绝对位移**。
5. 保留原 parallel implicit、IQN-ILS、时间步、材料、网格与物理条件；新 preCICE 会话**不会**天然恢复旧 IQN 历史，必须依赖物理/数值验收。
6. 所有转化及计算输入更改只能发生在**新 Slurm 作业的独立副本**；不得覆盖 `91543` 原目录或经校验备份。

该项目当时的已验证计算环境：OpenFOAM.com **v2512**、preCICE **3.4.1**、CalculiX **2.20**、OpenFOAM adapter **1.4.0**、CCX adapter **2.20.2**、Open MPI **5.0.7**、Fluid **8 MPI** + Solid **4 threads**、耦合窗口 `dt=0.000125 s`。实验沿用原有三维 blockMesh 网格和 HDPE 工况，入口与流体初始场 `U=0.16 m/s` 自 `t=0` 起生效；不可重新引入已取消的 1 s ramp。

**三个不可混淆的量**：

- 新进程 `t_physical = t_source_checkpoint + t_precice_relative`；不中断 `91543` 的参考相对钟起于物理 **0.0025 s**，不能直接按日志行号比较。
- 结构 `DisplacementDelta` 是**一个已接受窗口的位移增量**。若与不中断计算对照，应比较不中断绝对位移的相邻两个接受值之差，而不是把增量与绝对总量相比较。
- `precice-Solid-watchintegral-Interface-Integral.log` 的位移量是**接口积分**，不是叶尖位移 mm，也不是所有节点逐点相等的证明。

## 3. G0～G3 实测结果：分清原生通过与科学通过

| 真实作业 | 物理时间区间 (s) | 接受窗口 | 原生 FSI | 与 `91543` 同时刻最大 Fx 差异 | 科学状态 |
|---|---|---:|---|---:|---|
| G0：`92264` | 0.032500→0.032750 | 2/2 | PASS | **0.764446%** | 原定 1% PASS |
| G1：`92479` | 0.032750→0.035250 | 20/20 | **PASS**，MPI/结构检查点完整 | **1.025275%** | 原定 1% **FAIL** |
| G2：`93674` | 0.035250→0.035500 | 2/2 | PASS，双方退出码 0 | **0.052377%** | 本段严格 PASS，但属于诊断作业 |
| G3：`93691` | 0.035500→0.038000 | 20/20 | **`FSI_LONG_SEGMENT_PASS`**，双方退出码 0、终态网格 PASS | **0.054976%** | 本段严格 PASS，但属于非生产试验 |

其他已核实的关键指标：

- **G1**：Fx 严格 1% 只超 **0.025275 个百分点**；最大 Delta0 误差约 **0.005463%**、Delta2 **0.095843%**；首次 MeshCo 比值 **0.998921**。**不得**把 `DELTA_CONTINUATION_SHORT_STAGE_FAIL` 改写为 PASS。
- **G2**：上一段最后接受的 Fx = 新段零相对时刻 Force0 = **0.0261982480 N**；新会话初始三个 `DisplacementDelta` 分量均为 0；首次 MeshCo 比值 **1.000827523**；Delta0/Delta2 最大误差 **0.000826%/0.077987%**。
- **G3**：完整原生状态 `FSI_LONG_SEGMENT_PASS`，20/20、`fluid=0`、`solid=0`、终态网格 PASS；最大 Fx/Delta0/Delta2 误差 **0.054976% / 0.005178% / 0.079814%**，均在预设 1% 内。原报告仍为 `G3_PILOT_20_WINDOW_PASS_NOT_PRODUCTION`、`production_approved=false`。报告中的最大非正交角度是 `null`，不能臆造值。
- `sacct` 曾出现 `localhost:6819 Connection refused`，是记账数据库访问故障，不能凭此认为 FSI 失败，也不能在没有记账证据时宣称 SlurmDB 的 `COMPLETED` 已核实。

**结论**：跨 Slurm 的增量协议在多次真实重启中已经显示高度良好的科学一致性；**原生 PASS 不等于科学 PASS**，G1 历史 FAIL 和 G2/G3 的非生产标志必须持续保留。

## 4. 新聊天继续长作业必须逐项检查

| 检查类别 | 必需条件 / 不能犯的错误 |
|---|---|
| **真实接续源** | 本轮用户明确要求：从原始**三天**连续作业 **91543** 末态继续，而非误从 `91006`、`93691` 重算 |
| **源是否仍活跃** | 用 `squeue -h -u "$USER" -o '%i|%T|%N'` 检查 `91543`；仍在运行不得当作静止目录完整备份或重启 |
| **流体时间一致** | 八个 `processor0..7` 最新**完整**场目录均同一物理时间；核对 `U, p, phi, pointDisplacement, polyMesh/points, uniform/time` |
| **结构重启** | 最后**已接受**的 preCICE 时间与流体检查点吻合；`seagrass.rout`、`kinematic_state.bin`、原始坐标与真实可读取的 `*RESTART READ STEP` 一致，不能仅凭输入里的数字猜步骤 |
| **协议/几何** | `restartFromDeformed false` + `readData (DisplacementDelta)` + CCX writer 同名 + preCICE XML Force-only initial；若起始源还是 absolute `Displacement`，只在新的独立拷贝使用已经验证的转换函数 |
| **数值约束** | 原网格/物性/离散格式/初始 U、`dt` 不改；每个窗口 preCICE accepted、原生网格 guard、负体积/面失败、Co/MeshCo、PIMPLE/CCX 退出码与终态 checkMesh 均要留证 |
| **科学对照** | 在 `91543` 有同物理时间参考的区间内：逐窗口 Fx/Delta0/Delta2 各严格 ≤1%；**从 `91543` 的真实终态向未来继续时，没有第二条不中断参考**，不得虚构未来 1% 对照 |
| **任务依赖** | 前一真实作业必须通过原生及可用科学验收、保存检查点并退出 0 才放行下一段；使用 Slurm `afterok`，任一失败停链保留证据 |
| **运行环境** | 容器/OF/CCX/preCICE/OMPI/adapter、MPI ranks 与线程数统一，避免 ABI 或并行分解/场时间混乱 |
| **隔离和审计** | 每次新目录 `trial-<JOBID>`，记录代码 commit、输入文件 hash、源/目标时间、restart step、原生退出码、首窗力和 MeshCo、最终 JSON |

## 5. 先保护整个三天作业，再继续计算

**这次纠正最重要：72 小时是 Slurm 墙钟计算时长，不是物理模拟时间。**

- `91006` 是早期物理时间约 **0.0325 s** 的源作业，不是这次需要继续的“三天作业”。
- `92264 / 92479 / 93674 / 93691` 是验证修正方法的独立接续分支，G3 的 **0.038 s** 不等于三天原作业的真正终点。
- **`91543` 才是要继续的原始三天作业**。仓库里曾有目标物理时间 **0.1625 s**，但这只是目标，**至今未取得真实八 MPI/结构检查点的最后接受时间**；已有证据只证明 `91543` 至少经过 0.038 s。不能从 72 小时推断物理终点。

源目录：

```text
$HOME/hpcc-fsi/three-day-proven/long-job-91543
  └── runs/hpcc-implicit-002/
      ├── fluid/processor0...processor7/...
      ├── solid/seagrass.rout
      ├── solid/kinematic_state.bin
      ├── solid/precice-Solid-watchintegral-Interface-Integral.log
      ├── restart_reference/Solid-Mesh.coords
      └── precice-config.xml
```

**备份程序必须复制整个 `long-job-91543`，不是仅保存最近一个 `polyMesh` 或一两个时间目录**：网格、场历史、CCX 内部状态、preCICE/XML、所有日志、各种原生报告、源码或输入记录等全部保留。拷贝前扫描源 SHA-256，拷贝后再次扫描源和副本；三份清单严格一致才生成 `FULL_THREE_DAY_91543_BACKUP_SHA256_VERIFIED`。任何源在拷贝期间变动、外部软链接未包含、剩余空间不足或校验不一致，均不允许宣称成功。

**备份介质提示**：默认目录 `$HOME/hpcc-fsi-backups` 可能与原文件同一个存储故障域，只是防误删的另一份副本，**不是离线/异地灾备**。必须检查配额和剩余空间，尽可能在独立的数据存储或安全的第二位置再保留一份完整副本；不要为了腾地方删除三天原件。

目前相关实现文件：

- [91543 真实末态只读审计](../../hpcc/three-day-resume/inspect-91543.py)
- [91543 全目录 SHA-256 备份](../../hpcc/three-day-resume/backup-91543-full.py)
- [私有副本中的 absolute→delta 接续](../../hpcc/three-day-resume/resume-91543-delta.py)
- [完整三天备份优先与 Slurm afterok 链](../../hpcc/three-day-resume/submit-91543-continuation.py)
- [固定 Git 提交与源码 SHA 校验入口](../../hpcc/three-day-resume/backup-and-continue-91543.sh)
- [最早的已验证 absolute→delta 转换](../../hpcc/restart-forensics/try-incremental-displacement-restart.py)

上述文件**已经写入仓库并通过离线语法/自检流程**；目前还没有实际 `91543` 完整备份成功回执，也没有其末态续算作业号。不能将「GitHub Actions 绿色」等同于「正式三天续算已成功」。

### 给新聊天窗口的第一条检查命令

登录 HPCC，先获取客观事实：

```bash
BASE="$HOME/hpcc-fsi"
echo "===== 91543 是否还在运行 ====="
squeue -h -u "$USER" -o '%i|%T|%N' | grep '^91543|' || true

echo "===== 三天完整目录与可用存储 ====="
du -sh "$BASE/three-day-proven/long-job-91543"
df -h "$HOME"
# 确认已下载、校验冻结代码之后：
python3 "$BASE"/three-day-91543-code-*/inspect-91543.py --base "$BASE"
```

如代码未下载，先参照[固定源码下载入口](../../hpcc/three-day-resume/backup-and-continue-91543.sh)获取经哈希验证的版本，使用 `--inspect` 查实际末态，**不是一开始就盲目执行 `--submit`**。源码冻结版本也要对照 GitHub 当前审计结果，不混用不同 commit 的 runner、驱动和适配器。

**最关键的后续动作**：拿到 `91543` 的真实已接受终点 → 检查原生结构 restart step 和流体/结构同步 → 完整目录备份并校验 → 仅在新拷贝转换原始 absolute 协议 → 从真实最后物理时间连续接算 → 通过原生质量与已接受数据检查后接下一 Slurm 作业。

## 6. 故障排查速查

| 现象 | 容易犯的错误 | 正确处理 |
|---|---|---|
| 首窗 MeshCo 与参考差几个数量级，已接受 Fx 反号 | 重建网格或放宽质量阈值掩盖 | 查参考坐标、接口映射、absolute/delta 语义、Fluid 检查点历史 |
| 临时 Fx≈11 N，上一段已接受 Fx≈0.02 N | 拿不同耦合阶段直接相比 | 只按同物理时间、同 accepted 阶段比较 Fx |
| `sacct` 连接失败 | 宣称 FSI 算失败 | 记录记账故障，检查 squeue、原生日志、STATE、终态 JSON、双方退出码 |
| raw GitHub HTTP 503 | 改物理参数、跳过源码校验 | 固定 commit 重试、备用端点、下载后 hash；失败停止提交 |
| 原生 PASS 但科学 Fx 差 1.025% | 私自把门槛改成 2% PASS | 保存真实严格 FAIL，诊断试验另设标准，绝不替代科学门槛 |
| 只看一份 `BACKUP_COMPLETE.json` | 认为原件已安全 | 核对全目录/manifest/逐字节 SHA 与故障域，必要时做第二份副本 |

## 7. 新聊天窗口可复制的任务交接

> 当前唯一优先级：**继续原始三天作业 91543 的真实剩余计算**，不是再测 G4，也不是从 91006 或 93691 重跑。先取得 91543 的最后已接受物理时间及八个 Fluid/结构检查点，完整备份其 `three-day-proven/long-job-91543` 全目录并逐文件 SHA-256 验证，再在全新私有副本中把旧 absolute `Displacement` 方案按已验证的原始参考构形 + `DisplacementDelta` 语义转换并长时间续算。多个 Slurm 作业使用 afterok 依次接力，任何网格、收敛、检查点、源码/备份校验异常必须停链，不能覆盖旧文件。  
> 实证：G0 92264 2/2 严格 PASS；G1 92479 原生 20/20 PASS 但 Fx 1.025275% **严格 FAIL**；G2 93674 2/2 严格 PASS；G3 93691 20/20 严格 PASS（Fx 0.054976%、Delta0 0.005178%、Delta2 0.079814%），但正式报告仍是非生产。软件环境 OF v2512 + preCICE 3.4.1 + CCX 2.20 + OMPI 5.0.7，已验证 8 Fluid MPI + 4 Solid threads，dt=0.000125 s，全域初始 0.16 m/s。  
> **未完成事实**：91543 最终真实物理时间未知；完整备份尚无成功回执；91543 末态后的真实续算尚无新作业号。先检查 `--inspect`，然后再决定启动，不可冒称已接续成功。旧“备份三小时/从 93691 生产接续”分支明确不使用。

**一语总结：**文件存在 ≠ 成功重启；位移绝对/增量必须匹配原始参考构形，结构/流体时间与检查点必须一致，验证必须看已接受窗口和原生状态，长程历史必须先完整备份并核验。
