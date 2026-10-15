# Seagrass FSI — HPCC container

Cloud-build a Linux AMD64 container for the University of Macau HPCC.

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
