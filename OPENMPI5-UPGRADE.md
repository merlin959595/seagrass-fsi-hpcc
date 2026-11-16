# Open MPI 5.0.7 candidate (non-destructive)

This branch adds a **candidate** container, it does NOT update or overwrite the deployed SIF.
The original `Dockerfile`, `build-fsi.yml`, and GHCR tag stay unchanged.

## Build on GitHub Actions
Open Actions → "Build FSI container (Open MPI 5.0.7 candidate)" → Run workflow.
Select branch `upgrade/openmpi-5.0.7-hpcc`.
A successful build publishes `ghcr.io/merlin959595/seagrass-fsi-hpcc:ompi5.0.7-candidate`.

Image validation covers MPI 5.0.7 version, real two-rank MPI_Init/Finalize, preCICE package version, and binary dynamic-link availability. **This is not validation of the custom WSL CalculiX binary, ALE mesh guard, Slurm integration, or real 3D FSI.** Those must be checked separately before production.

## Non-destructive HPCC pull
Run after the GHCR tag exists and is public; submit from a login node:

```bash
mkdir -p "$HOME/hpcc-fsi/logs"
sbatch -p cpu -N 1 -n 1 --mem=8G -t 02:00:00 \
  -J fsi-ompi507-pull \
  -o "$HOME/hpcc-fsi/logs/ompi507-pull-%j.out" \
  --wrap='set -eu; cd "$HOME"; test ! -e seagrass-fsi-ompi507-candidate.sif; singularity pull seagrass-fsi-ompi507-candidate.sif docker://ghcr.io/merlin959595/seagrass-fsi-hpcc:ompi5.0.7-candidate; singularity sif list seagrass-fsi-ompi507-candidate.sif'
```

Existing `$HOME/seagrass-fsi.sif` is preserved.

## On-compute-node smoke test
```bash
srun -p cpu -N 1 -n 1 --mem=4G -t 00:10:00 \
  singularity exec --cleanenv "$HOME/seagrass-fsi-ompi507-candidate.sif" \
  bash -lc 'mpirun --version; precice-version; ldd /usr/local/bin/ompi5-smoke; mpirun --oversubscribe --bind-to none -np 2 /usr/local/bin/ompi5-smoke'
```

Then separately verify compatible compiler/runtime libraries and custom binaries with `ldd -r`; a real two-participant preCICE time window and accepted-window performance are the required FSI gate. Keep using the old SIF until all gates pass.

## Caveat
The old OpenFOAM binaries were built against the previous container MPI. Overlaying a new MPI may be ABI-compatible, but is not sufficient proof of correctness. Failing checks must trigger reconstruction/recompilation, not removal of the checks. Do not combine host Open MPI 5 launcher with the container's Open MPI 4 runtime.
