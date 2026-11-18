# Seagrass FSI — HPCC container

Cloud-build a Linux AMD64 container for the University of Macau HPCC.

## 科研计算经验库 / Research computing lessons

跨 Slurm 作业双向 FSI 续算等复杂问题的长期经验集中保存在 [knowledge-base](knowledge-base/README.md)。当前最重要的案例是 [2026-11-16 海草 ALE–FSI 跨作业重启事故与修复验收](knowledge-base/cases/2026-11-16-cross-job-ale-fsi-restart.md)，可复用流程见 [增量位移接续 SOP](knowledge-base/playbooks/delta-fsi-continuation.md)。

**最新状态（2026-11-18）：** 92264 两窗口 G0 严格 PASS；92479 G1 原生 20 窗口 PASS，但最大 Fx 差异 **1.025275%**，原定严格 1% 判据仍 FAIL；93674 G2 又经新的独立 Slurm 作业完成 2/2 窗口，原生 PASS、Fx 最大误差 **0.052377%**，本段严格科学对照 PASS。G2 报告保留 `G2_DIAGNOSTIC_BOUNDED_PASS_NOT_PRODUCTION` 和 `production_approved=false`。已经准备 [从 G2 93674 接 20 窗口的独立延长试验](hpcc/restart-forensics/prepare-and-submit-g3-after-93674.sh)；仍不自动开启长程生产。

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
