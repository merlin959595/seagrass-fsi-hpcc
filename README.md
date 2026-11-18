# Seagrass FSI — HPCC container

Cloud-build a Linux AMD64 container for the University of Macau HPCC.

## 科研计算经验库 / Research computing lessons

跨 Slurm 作业双向 FSI 续算等复杂问题的长期经验集中保存在 [knowledge-base](knowledge-base/README.md)。已设立独立的 [**科研计算经验专栏 / Practical Lessons**](knowledge-base/experiences/README.md)；重点文章是 [**三维海草 ALE–FSI 跨作业重启：修复原理、真实验收、三天原始作业 91543 的完整备份与接续**](knowledge-base/experiences/2026-11-19-seagrass-ale-fsi-restart-practice.md)。完整取证见 [2026-11-16 事故时间线](knowledge-base/cases/2026-11-16-cross-job-ale-fsi-restart.md)，旧测试阶段 SOP 见 [增量位移接续 SOP](knowledge-base/playbooks/delta-fsi-continuation.md)。

**最新路线（2026-11-19）：** `91543` 才是需要继续的**72 小时三天长程作业**，从物理时间 `0.0025 s` 开始，原计划目标 `0.1625 s`；其**实际最终接受时间必须在 HPCC 读取八个流体分区与结构检查点才能确定**，不能把原计划当成终态。`93691` 的增量接续分支通过 20/20 窗口原生和 ≤1% 科学对照，现用于证明修正方法。**禁止执行旧三小时/从 93691 启动的方案。** 新 [三天源作业 91543 全量 SHA-256 备份、末态审计和自动依赖续算入口](hpcc/three-day-resume/backup-and-continue-91543.sh) 已准备；首先完整备份真实 `91543`，再在源检查点同步且原生质量检查通过的前提下从其终态开启新的 `DisplacementDelta` 续算作业，所有原始算例均不覆盖。GitHub 离线测试不代表 HPC 已实际备份或已提交续算。

## Target versions

- OpenFOAM.com v2512 (official `opencfd/openfoam-default:2512`)
- preCICE 3.4.1 (official Noble Debian package)
- CalculiX 2.20 with preCICE adapter 2.20.2 (official Noble Debian package)
- OpenFOAM-preCICE adapter 1.4.0 (built inside the image)
- Ubuntu 24.04, x86-64/AMD64

## Build without using your PC as a server

1. Go to **Actions** → **Build FSI container (amd64)** → **Run workflow**.
2. Watch the **build** job. Success requires the image build and dependency checks to pass.
3. When successful, the container is pushed to GitHub Container Registry:

   `ghcr.io/merlin959595/seagrass-fsi-hpcc:v2512-precice3.4.1-ccx2.20.2`

4. To allow the HPCC to download without GitHub credentials, first set the published **package visibility to Public** in GitHub Packages, if it is private.

## University of Macau HPCC (only after a successful build)

Download and convert the published image using Singularity via a SLURM job (check that compute-node network access is permitted):

```bash
sbatch -p cpu -N 1 -n 1 --mem=8G -t 02:00:00 -J fsi-pull -o "$HOME/hpcc-fsi/logs/fsi-pull-%j.out" -e "$HOME/hpcc-fsi/logs/fsi-pull-%j.err" --wrap='cd "$HOME" && singularity pull seagrass-fsi.sif docker://ghcr.io/merlin959595/seagrass-fsi-hpcc:v2512-precice3.4.1-ccx2.20.2 && singularity sif list seagrass-fsi.sif && echo FSI_SIF_OK'
```

Inspect the actual container on a compute node:

```bash
srun -p cpu -N 1 -n 1 --mem=2G -t 00:05:00 singularity exec --cleanenv "$HOME/seagrass-fsi.sif" bash -c 'source /usr/lib/openfoam/openfoam2512/etc/bashrc; echo "$WM_PROJECT_VERSION"; command -v blockMesh; command -v ccx_preCICE; pkg-config --modversion libprecice; find "$FOAM_LIBBIN" -maxdepth 1 -name "libpreciceAdapterFunctionObject.so"'
```

## Validation status and limitations

**Config is prepared; build and FSI numerical verification are not yet complete.**

The Dockerfile checks program availability and the OpenFOAM adapter linkage. A successful build **does not** establish that fluid/solid coupling or MPI multi-node execution works. Validate against published preCICE tutorial benchmarks before running the 3D seagrass case.

The image does not include private simulation cases, SSH keys, or HPC account credentials. Mount study cases from HPCC storage. The base OpenFOAM SIF and downloaded packages already on HPCC can be kept as backups.

If the workflow fails, open the first red job step and capture the **actual failure text**. Fix that specific dependency/build issue before rerunning.
