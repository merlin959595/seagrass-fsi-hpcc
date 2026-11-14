# HPCC FSI release gate — 2026-11-12

## Evidence accepted, not to be repeated

- Frozen 282,332-cell blockMesh case transferred with SHA256 confirmation (199 MB).
- Native initial mesh: `Mesh OK.`, quality/geometry/topology checks passed.
- Open MPI 5.0.7: real two-rank Init/Finalize passed.
- preCICE 3.4.1: rebuilt without legacy PETSc / Open MPI 4 C++ binding dependency.
- Custom persistent CalculiX 2.20 and two native libraries: `NATIVE_BINARY_ABI_PASS`.
- Scotch 8-way `decomposePar` and input staging: `FSI_002_PREFLIGHT_PASS` in job 87156.
- Job 87156 did **NOT** start fluid/solid; missing `/usr/bin/time` in container.
- GitHub workflow run 43049294784 failed because Docker build container DNS could not resolve archive.ubuntu.com/security.ubuntu.com. It is **NOT** evidence of missing `time` in Ubuntu packages.

## Current code changes — NOT YET RUNTIME VALIDATED

- `Dockerfile.ompi5-time`: copies real GNU `/usr/bin/time` staged from same-release Ubuntu 24.04 GitHub Actions host; does **not** need `apt-get` inside Docker.
- `.github/workflows/build-ompi5-time.yml`: fail-closed runner staging and build, verifies `time -v` and FSI executable dependency resolution.
- `hpcc/deploy-timefix-and-run-implicit-002.sh`: separate SIF and pilot paths, full native/external dependency check before real solve; leaves all prior evidence untouched.
- Existing `hpcc/implicit-002-driver.py`: 8 fluid MPI, 2 CalculiX OpenMP threads, dt=0.000125, 160 windows to 0.02 s, frozen baseline, strict accepted-window checks.

## Mandatory gate sequence

1. GitHub Actions workflow **Build FSI MPI5 Scotch + GNU time candidate** on branch `upgrade/openmpi-5.0.7-hpcc` must end in `success`. Find `FSI_MPI5_FULL_CONTROLLER_DEPENDENCY_SMOKE_PASS` in build log and confirm GHCR push.
2. HPCC Slurm job from `hpcc/deploy-timefix-and-run-implicit-002.sh` must report `GNU_TIME_RUNTIME_PASS` and `FULL_CONTROLLER_DEPENDENCY_PREFLIGHT_PASS`.
3. HPCC preflight must report `FSI_002_PREFLIGHT_PASS`; do **not** equate this with solver success.
4. Both participants must run and produce coherent, accepted preCICE window logs.
5. The real 0.02 s run must write `GATE-0160.json` with `LIVE_GATE_PASS` and finish with `HPCC_IMPLICIT_0P02_ACCEPTED_160_WINDOWS_PASS`.
6. Only then plan 8/16/24 rank throughput benchmarking and 0.2s production.
7. Same-time persistent 3-way restart (fluid, solid, preCICE) is still **UNVERIFIED**; no 1s chained Slurm scheduling until independently proven.

## Hard constraints

- Preserve all frozen inputs, blockMesh topology and accepted 75 mm ALE validation.
- Initial `0/U` and inlet must remain uniform (+0.16,0,0) m/s from t=0, no ramp.
- Coupling must remain parallel implicit with IQN-ILS and 1e-5 residuals.
- Do not run snappyHexMesh, Gmsh, stitchMesh or topology reconstruction.
- Do not modify or interrupt the current WSL run.
- Do not overwrite `$HOME/seagrass-fsi.sif`, `$HOME/seagrass-fsi-ompi507-scotch.sif`, source archive, failed pilot logs, or existing result directories.
- Do not describe GitHub build or ABI checks as proof of FSI convergence.
