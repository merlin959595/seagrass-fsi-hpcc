# ALE concavity recovery for job 96764 (2026-11-22)

This is HPCC-executable code, **not** a claim that a real replacement FSI job has already run.

## Frozen evidence

- Last verified restart source: /data/icto/$USER/seagrass-fsi558-runs.sNIpi9/trial-96763/runs/hpcc-implicit-002 at 0.563500 s, 8 fluid MPI ranks plus CalculiX binary restart files.
- Job 96764 failed at 0.579375 s from a single concave cell: processor5/cell3535, global cell ID 3535, center about (0.114597,0.046203,0.009133) m.
- Six neighboring local cells: 3409,3531,3532,3533,3534,20547. Six internal faces: 11491,11899,11901,11903,11905,11907.
- Mesh guard near failure: maxNonOrtho 64.927811 degrees, maxSkew 3.918997. Do not weaken the 65-degree or skewness-4 constraints.
- Active model: displacementLaplacian/seagrass558RampFile, pinned library SHA256 1032420382c07a8138f122199017013ed0aa242410f73a41330cbff199aac1a2.
- Existing native FSI restart core is pinned from the proven cross-job branch and invokes the HPCC-installed resume-cycles.py.

## One HPCC terminal command

Run on an HPCC login node to download and submit an independent Slurm repair job:

    curl -fLsS https://raw.githubusercontent.com/merlin959595/seagrass-fsi-hpcc/029e676d9f1b2491c251adec8bbe332f9985f32c/hpcc/ale-repair-96764/bootstrap-96764.sh -o /tmp/ale-96764-bootstrap.sh && bash /tmp/ale-96764-bootstrap.sh --submit

Substitute --preflight to run checks without submitting, or --status to inspect results. The bootstrap verifies pinned Git blob hashes and Python syntax. It requires no new container builds.

## Submitted-job behavior

1. Verify the trusted 0.5635 s checkpoint, expected processor5 topology, and exact existing ALE library.
2. Full-copy trial-96763 and trial-96764 to independent backups, with SHA256 checks of each source before and after copying and of each backup.
3. For each trial, use the original resume-cycles.py and native FSI core. Hook only private staged clones and change only processor5/constant/motionReferenceDiffusivity by a smooth topological-distance multiplier around cell3535. No remeshing or mesh guard changes.
4. Sequential controlled candidates: multiplier/radius (1.20,8), (0.85,8), (1.35,12). Replay 144 actual FSI time windows to 0.5815 s for each candidate until one passes. Then 176 more windows to 0.6035 s, carrying forward the existing modified field exactly once.
5. Demand true native FSI pass, accepted windows, both fluid and solid exit codes 0, complete fluid/solid restart, and no mesh-guard failure at any window. Preserve failed trial snapshots.
6. After a **real** 0.6035 s FSI pass only, queue five 640-window native continuation jobs with strict afterok dependencies, targeting 1.0035 s. A failed job blocks successors.

## Scope and safety

- The original three-day 91543 data and prior verified backups are untouched. The newly copied trials are stored under the separate recovery root.
- GitHub Actions CI tests syntax and fail-closed parsing using synthetic files; it does not run live HPCC FSI.
- A successful projected sweep (96750) is insufficient acceptance; only actual FSI windows count.
- The three local multipliers are experimental and are not proven to eliminate cell concavity. They are intentionally bounded and fully tested under native guards.
- Disk user quota must be sufficient for two complete trial snapshots on /data/icto; shared-filesystem capacity alone does not prove quota.
- GitHub cannot directly submit Slurm jobs without an authorized HPCC runner or terminal. The bootstrap command above is the one required HPCC action.
- Slurm outputs, test variants, backup proofs, and subsequent production chain are saved under /data/icto/$USER/seagrass-fsi558-runs.sNIpi9/repair-96764-github-20261122 and fresh trial directories.
