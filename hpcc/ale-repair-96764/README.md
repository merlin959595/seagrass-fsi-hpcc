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

    curl -fLsS https://raw.githubusercontent.com/merlin959595/seagrass-fsi-hpcc/7d1a4d4af688c3b0da33214a8893e79482345d03/hpcc/ale-repair-96764/bootstrap-96764-v4.sh -o /tmp/ale-96764-bootstrap.sh && bash /tmp/ale-96764-bootstrap.sh --submit

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

## 2026-11-22 V3 fix

The initial V1 preflight rejected binary `motionReferenceDiffusivity`; V2 added native OpenFOAM binary parsing and passed the user's live preflight. V3 fixes one more discovered issue before real FSI: the existing continuation driver expects the `trial-96763` ROOT as `source_work`, not the nested `runs/hpcc-implicit-002` path. V3 uses a fresh `repair-96764-github-20261122-v3/code-v3` recovery directory and runs only one preflight inside `--submit`. If a V2 repair job is pending or running, V3 refuses duplicate submission; never run both simultaneously.

## V4 patch — stalled submission after READONLY_PREFLIGHT_PASS

V3's submit function called `find_core(local)`. Although bootstrap downloaded the validated native core to `code-v3/segment.py`, `find_core` searched only `code-v2` / `code`, then performed a potentially enormous recursive scan of old HPCC run data. This explains a submission hanging after preflight without a Slurm job ID. V4 uses only the pinned `repair-96764-github-20261122-v4/code-v4/segment.py` and checks the exact Git blob hash. No recursive filesystem search occurs. CI adds a direct core-resolution test, plus pinned code integrity and bash syntax checks. **Before starting V4, ensure the V3 foreground process has exited; check `squeue -n ale96764repair,ale96764go` and never launch a second repair job if one is active.**

## Job 97576 evidence and V5 fallback (2026-11-22)

Slurm accepted job 97576 from V3 and reported RUNNING on cpu-40-5.
Its stdout has READONLY_PREFLIGHT_PASS and BACKUP_FULL_TRIAL_SHA256_PASS trial-96763 (14092 entries, 4335472723 bytes).
Its stderr has Bash parsing errors for repair96764.py ("line 11: from: command not found"), which indicate a Bash process attempted to interpret Python code. This does not itself prove the main FSI job is terminal, as the supplied Slurm snapshot still reports RUNNING and the second backup outcome is unknown.

DO NOT submit V5 while 97576 or any replacement FSI repair/production job is active. Do not cancel a running backup solely because this stderr appeared. Inspect actual Slurm state and full evidence first.

V5 is a contingency for a terminal V3 job without verified FSI completion:
- A separately pinned container entrypoint run-96764-container.sh explicitly executes /usr/bin/python3 with the controller argument, eliminating nested bash -c command/positional ambiguity;
- The V5 controller reuses the original V3 recovery root repair-96764-github-20261122-v3, checks SHA256 backup manifests before reuse, and avoids duplicating copies if completed backups already exist;
- All new code stays in code-v5, preserving V3 code, batch files, trial-96763, trial-96764 and existing backups;
- The controller rejects an active repair/production job, duplicate V5 submissions, unexpected core binaries, and invalid/incomplete backups;
- If a previous V3 backup is incomplete, fail closed and preserve it for manual reconciliation instead of deletion.

Only if 97576 has reached terminal state without a validated continuation:
use hpcc/ale-repair-96764/bootstrap-96764-v5.sh from a fixed Git commit, not an unpinned branch. CI runs parser, binary-file, native wrapper and file-hash checks, but cannot validate live FSI.

## 2026-11-22 confirmed V3/V5 native mesh failure: fixed-gain scan exhausted

Verified observed numerical results (not inferred from failed process exit codes):

| Job / candidate | Motion reference diffusivity gain | Native ALE guard | Verdict |
|---|---:|---|---|
| 97576 / C1 | 1.20, radius 8 | concave=1 at 0.563625 s | failed |
| 97576 / C2 | 0.85, radius 8 | concave=1 at 0.580750 s | failed |
| 97576 / C3 | 1.35, radius 12 | concave=1 at 0.563625 s | failed |
| 97854 / C1 | 1.20, radius 8 | concave=1 at 0.563625 s | failed |
| 97854 / C2 | 0.85, radius 8 | concave=1 at 0.580750 s | failed |

The structural exit 134 is downstream of the OpenFOAM mesh guard abort; **it is not independent evidence of a CalculiX material divergence**. All V3 stage-1 trials failed; V5 C1/C2 repeated those failure fingerprints, and V5 C3 uses the same already-failed algorithm. The failure is a **geometric concavity guard**, not nonorthogonality, skewness, negative volume or face-tet. Global volume and angle PASS do not override concavity.

The local field patch changed **only the processor5 internal face diffusivity values** near cell3535, with gains/radii from the failed trials. It did not change the reference blockMesh geometry, re-decompose a new grid, or demonstrate consistency across processor patches. The repeated failures establish that simple scalar multipliers are not sufficient; **do not submit another unchanged candidate set**. The exact offending cell(s) at 0.580750 s are *not yet identified*. It is unsound to assume that the last failure is the same processor5/cell3535 as the earlier 0.579375 s failure.

Job 97576 returned REPAIR_NOT_YET_VALIDATED and next_production_submission_permitted=false. The last **fully accepted segment with verified native FSI restart** remains 0.5635 s; a later Time= line or passing per-iteration mesh guard does NOT establish a recoverable coupled checkpoint. The separate read-only forensic report checks candidate transient files across 8 MPI fluid partitions and structural restart; it cannot certify restartability by itself.

**Safe immediate action:** If V5 C1/C2 replicated identical fatal guards and job 97854 remains active, the pinned stop-duplicate-97854.sh will cancel only that Slurm job, leaving source, SHA256 backups and partial candidate data untouched.

**Next engineering gate:** Before new production simulations, identify the actual failing cell/face/rank and its geometry; audit accepted reference geometry versus pointDisplacement at restart, interface/processor diffusivity continuity, and restart force/displacement state. Modify the ALE motion field using a new geometry-based intervention and independently validate one native FSI path past 0.58075 and 0.6035, not three arbitrary constant multipliers. Do not claim a real FSI pass or queue production until that evidence exists.

### 2026-11-22 native failed-cell identity resolved

The private isolated eight-MPI OpenFOAM v2512 `checkMesh -allGeometry -writeSets vtk` on saved V3-C2 mesh snapshots returned:

- `0.580500 s`: `Mesh OK`, `Concave cell check OK`; max non-orthogonality 64.9473°, max skewness 3.92492.
- `0.580750 s`: `***Concave cells (using face planes) found, number of cells: 1`; `Failed 1 mesh checks`; max non-orthogonality 64.9515°, max skewness 3.92624.
- `processor5/0.58075/polyMesh/sets/concaveCells`: `1(2758)`; all seven other processor cellSets are `0()`. The **new failing cell is rank5/cell2758**, not the **prior multiplier center rank5/cell3535**. Their physical distance and adjacency are not yet established.
- The saved failing mesh independently reproduces concavity, so this is **not solely an unpersisted coupling-iteration artifact**.
- A VTK geometry export exists at `diagnostics/native-concavity-97576-c2/postProcessing/0.58075/concaveCells/concaveCells.vtp`.

Next action: run `audit-cell2758-geometry-readonly.py` on the pre-existing private mesh copy to determine face connectivity, 3535→2758 graph distance and vertex movement from 0.5805 to 0.58075. The diagnostic uses only Python stdlib, does not modify user data or start a Slurm job. It was syntax/fixture tested in GitHub CI; native geometry analysis on actual HPCC data remains to be performed. Do not change any ALE coefficient or submit production until topology and face-plane geometry are examined.

### 2026-11-22 face-centre sign-change identified (read-only v2)

The read-only face-centre and outward-normal geometry proxy for **rank5/cell2758** reproduces the independently proven native checkMesh pass/fail at the two stored snapshots. It flags **face 9315 → face 9306**:

| Time | Signed projection (m) | Normalized projection | Native checkMesh |
|---|---:|---:|---|
| 0.580500 s | -2.0652985610429553e-6 | -0.00026723537883100704 | Mesh OK |
| 0.580750 s | +2.0403909842909781e-7 | +0.000026400283593251755 | 1 concave cell |

The sign crossed zero, a change of +2.269337659472053e-6 m (**+2.269337659 µm**). Faces are 9315 [3918,3919,3922,3923] and 9306 [3916,3917,3919,3918]; vertices 3922/3923 are stationary across these snapshots, while other vertices move 3.83-5.84 µm. Prior centre cell3535 at Y=+0.046203 m has a much safer proxy maximum (~ -2.46e-4 m), while failing cell2758 at Y=-0.046203 m is 7 graph layers away.

**Interpretation limits**: Independent geometry proxy is NOT an OpenFOAM source-code equivalence proof. The prior 8-ring smooth diffusivity change can influence the failed cell but its weight falls off strongly with distance. Do not claim the failure was caused by a particular vertex or that changing scalar diffusivity alone guarantees repair. The actual failing cell, sign-crossing pair and nonzero face motion are observed facts; effective ALE intervention is still experimental.

Updated `audit-cell2758-geometry-readonly.py` decomposes the critical signed-projection change into (a) relative motion of the face centres and (b) rotation of face9315 outward unit normal; test all new repair ideas against this precise failure metric AND the native checkMesh and real two-way FSI guards, not merely the zero crossing. No production calculation has been authorized from the failed trial.

### 2026-11-22 verified root geometry mechanism: face normal rotation dominates

The latest `CRITICAL_PAIR_9315_TO_9306_BREAKDOWN` output from the private failed V3-C2 mesh isolates the **+2.269337659 µm** movement across the concavity boundary:

| Term | Change in outward face-to-face projection |
|---|---:|
| Relative motion of face centres | **−2.690150378 µm** (helps) |
| Rotation of outward unit normal of face9315 | **+4.959488037 µm** (harms) |
| Net | **+2.269337659 µm** |

The face9315 normal turned only **0.03713748°**, from (-0.82726248, -0.04357972, 0.56012284) to (-0.82689974, -0.04356092, 0.56065967). The centre-based normal projection moved from −2.06530 µm at 0.580500 s (native checkMesh PASS) to +0.204039 µm at 0.580750 s (one native concave cell rank5/2758). Static face9315 vertices 3922/3923 had zero motion across these snapshots while its other two vertices 3918/3919 moved ~4.10/3.83 µm in mostly +X/−Z. The critical pair is geometrically near-degenerate; simply altering centre translation is the wrong primary control.

**Not established**: Whether vertices 3922/3923 are physical wall patch vertices or only transiently stationary; whether the patch face itself is an interface or processor boundary; which individual ALE degrees of freedom controls the normal rotation; and whether a coefficient change preserves reliable fluid-solid restart. The C2 repair field was changed solely around prior rank5 cell3535 at Y=+0.046203 m, whereas cell2758 is at Y=−0.046203 m, seven topological layers away.

A new strictly read-only `--constraints` mode of `audit-cell2758-geometry-readonly.py` reports exact boundary patch memberships of eight vertices, original C2 gain=0.85 face weighting at six incident faces, and finite-difference projection sensitivity attribution across real observed motion. This is the required precondition for designing a **smooth, boundary-respecting bilateral/negative-Y near-bed ALE displacement-gradient intervention**. The intended production workflow remains: original verified checkpoint t=0.5635 s -> isolated native coupled FSI until beyond 0.58075 and target 0.6035 -> verify eight fluid ranks, solid restarts, force/disp coupling and all guards -> then queue continuation. **No speculative restart and no blind coefficient sweep.**
