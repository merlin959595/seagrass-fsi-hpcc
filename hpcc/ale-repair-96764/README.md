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

### 2026-11-22 actual C2 boundary mechanism and geometry-driven one-shot FSI repair

The cell2758 bed-constrained vertex sensitivity from 0.580500 to 0.580750 s is **direct evidence**, not an estimated response to changing a diffusivity field. The bed/wall vertices 3922 and 3923 are fixed and must remain fixed. Moving vertices 3919 (+2.629760468 µm) and 3918 (+2.205446275 µm) worsen the critical face9315→9306 projection; vertices3916 (−1.364347354 µm) and3917 (−1.201521729 µm) help. Sum is +2.269337659 µm with negligible integration error. Face9315's outward normal rotation contributes +4.959488037 µm, vs −2.690150378 µm from relative face-centre translation.

The actual old C2 factor at the five incident face IDs 9318,9306,9309,9313,9315 is only 0.9935546875; face9317 is 0.9765625. Thus its effect at the actual failed bed-side cell is weak, even though C2 brought the native *mesh guard* to 0.580625 s. This is **not** an accepted coupled restart.

**One new experimental native FSI trial** is implemented in `hpcc/ale-repair-96764/one-shot-bed2758-native-fsi.py`, with offline tests in `test_one_shot_bed2758.py`. Its spatial design preserves the original positive-Y repair C2 exactly (gain 0.85, 8 cell-adjacency rings about cell3535), adds a six-ring smoothly tapered, higher-diffusivity zone (gain 2.0) around real failed rank5/cell2758, and changes **only the private rank5 internal reference-diffusivity field**. The old center3535 remains at the unchanged C2 values; critical faces9315 and9306 get exactly twice their previous C2 coefficient. The factor 2.0 is a *bounded physics-informed experimental hypothesis* to reduce local displacement gradients and face normal rotations near the fixed wall, **not a calibrated guarantee** of mesh validity.

The controller refuses changed topology, missing original/source evidence, missing verified backups, field-encoding mismatch, a region touching a processor-coupled boundary, and duplicate active trials. It runs exactly one genuine two-way FSI candidate from the **last fully accepted 0.5635 s checkpoint** through 0.5815 s, then to 0.6035 s only after a complete stage1 pass, with full native FSI and eight fluid rank / CalculiX restart acceptance. It **does not** change wall vertices, mesh topology, quality thresholds, forces or coupling schemes, and it does **not** automatically queue production. It reuses existing complete checksum backups without making expensive second copies. GitHub tests are synthetic; do not claim a live HPCC repair or production restart until native solver validation succeeds.

If new geometry fails or the processor patch safety check refuses submission, stop and revisit the spatial motion method instead of blind parameter sweeps.

### 2026-11-22 real 98512 negative-Y gain2.0 trial: FAILED in first window, withdraw candidate

The native 98512 one-candidate real two-way FSI attempt started from the verified 0.563500 s checkpoint but **failed at the first attempted time 0.563625 s**, not at the prior C2 failure at 0.580750 s.

Evidence from the actual user-provided HPCC logs:
- First and last `SEAGRASS_MESH_GUARD`: `time=0.563625 minVolume=2.017407002313e-11 concave=1 qualityFailed=1 skewFailed=0 orthFailed=0 tetFailed=1`. This indicates geometry failure (concave and face-tet flags), not a violation of the skew or orth thresholds at that time. It does **not** identify the newly failed cell.
- The native driver `STATE.json` says `FSI_LONG_SEGMENT_FAILED`, `restart_from_time_s=0.5635`, `final_time_s=0.5815`, `FSI exits invalid: {'fluid': 1, 'solid': 134}`.
- Solid logs show preCICE socket EOF and signal 6 after the fluid OpenFOAM fatal error. This is plausibly downstream of the fluid failure; no independent structural root cause proven.
- `DELTA_CONTINUATION_RESULT.json`: `91543_CONTINUATION_FAIL`; first attempted meshCo=0.81835184350932 exceeds 0.5, though no same-time external scientific reference is available.
- `RESULT-98512.json`: `TARGETED_BED2758_REPAIR_NOT_VALIDATED`, verified_time_s=0.5635; Stage2 never launched; no production continuation queued.
- `sacct` responded with accounting DB persistent connection refused (localhost:6819), independent of the real log verdict.
- Trial applied rank5 internal reference-field patch successfully, recorded SHA-256 `7cfdb551c2b500fe392535ca118b9db562f237a654de22c32420bec64f6e58de`, but **this trial must be withdrawn**. The one-shot gain2.0 negatively altered ALE response at the restart itself.

**Do not retry 98512, do not change mesh guards, do not accept any 98512 snapshot as a new coupled restart.** Maintain source 0.5635 and old checksum backups unchanged.

Read-only script `triage-98512-first-window-readonly.py` compares first and failed guards / fatal context for original C2 jobs97576 & 97854 versus 98512 and reports whether a failed first-window mesh snapshot exists for processor5. This is essential to separate initial ALE reference-field sensitivity from a new failure at the prior cell2758; the latter cannot be assumed from flags alone. In future geometry interventions, prefer removing extreme near-wall coefficient discontinuity and testing face-normal rotation/processor consistency without arbitrary escalating multipliers; do not launch another FSI without a reproducible local geometry reason and native first-window acceptance.

### 2026-11-22 comparative first-step guard audit: C2 replicated twice vs 98512

The user-supplied read-only triage output proves these native run-time mesh checks:

| Case | Native guards | First guard at 0.563625 | First failed guard | Max nonorth at failure | Skewness at failure |
|---|---:|---|---|---:|---:|
| C2 job97576 | 880 | concave=0, qualityFailed=0, tetFailed=0 | 0.580750: concave=1, qualityFailed=0, tetFailed=0 | 64.951530574951° | 3.9262362039944 |
| C2 job97854 | 877 | concave=0, qualityFailed=0, tetFailed=0 | 0.580750: concave=1, qualityFailed=0, tetFailed=0 | 64.951530839123° | 3.9262361875653 |
| New bed+2x job98512 | 1 | concave=1, qualityFailed=1, tetFailed=1 | 0.563625: first step | 64.646999220486° | 3.8330407419758 |

The new 98512 proposal dramatically worsens the earliest-step native ALE mesh quality even though orthogonality/skewness look better, and is **withdrawn**. Both original C2 runs independently and reproducibly fail only at 0.580750 s. The Fluid solver rejects the mesh, CalculiX then loses its preCICE socket. **Never promote 98512 to a restart; never claim the 98512 failed cell ID is 2758 without extracting the newly failed mesh cellSet.**

Unlike the two C2 cases, 98512 saved rank5 geometry at **0.563625**. For an authoritative OpenFOAM cell ID, `native-check-98512-first-window.py` preflights the existence of both 0.563500 and 0.563625 *for all 8 ranks*, copies just polyMesh and fvSchemes/fvSolution to a fresh private diagnostic, and submits a short 8-core native `checkMesh -parallel -time ... -allGeometry -writeSets vtk` run. The resulting private rank-local `concaveCells` cellSets identify the failing MPI rank/cell ID. Its job is **mesh diagnosis only, no fluid/solid coupling**, and native checkMesh may not replicate all custom in-situ face-tet thresholds. No preflight pass or new Slurm job exists until user runs the script on HPCC.

### 2026-11-22 Slurm 98524 confirmed native cell ID for first-step failure

The independent native OpenFOAM v2512 8-rank `checkMesh -parallel -allGeometry -writeSets vtk` on a **private copy** of job98512 geometry completed as Slurm job **98524**, at exactly two stored time states. Tool return code was 0 in both cases, but **native printed mesh verdict must be interpreted separately**:

| Actual time | Native mesh verdict | Concave cells | Face-tet quality | Max nonorth | Max skew |
|---|---|---|---|---|---|
| 0.563500 s | `Mesh OK` | none | PASS | 64.6469° | 3.83305 |
| 0.563625 s | `Failed 2 mesh checks` | **1** | **1 failed face** | 64.6470° | 3.83304 |

The native `processor5/0.563625/polyMesh/sets/concaveCells` contains exactly `1(2758)`; all other ranks 0..4 and 6..7 contain `0()`. **The old C2 late failure and new 98512 first-step failure are the SAME exact rank5/cell2758.** 98512 does not merely transfer a failure to a new region; it accelerates the original failure. No evidence yet identifies the *face tet* as face9315, or confirms the first-step concavity is triggered by the same face-centre pair; the previous face9315→9306 result is from a **different C2 geometry at 0.580750 s**.

The 98512 native failed geometry exists for both 0.5635/0.563625 on all 8 ranks. A new **no-Slurm, read-only** `compare-98512-and-c2-cell2758.py` (using the existing `audit-cell2758-geometry-readonly.py` binary reader) checks the first-window cell face-pair signed normal projection, separates relative face-centre movement vs face-normal rotation, attributes vertex sensitivities and confirms the native concave cell set, comparing separately to 97576-C2 geometry at 0.5805/0.58075. It explicitly warns that those C2 comparison times are later, and the C2 first-step point geometry was not saved. This is the next required diagnostic before any further ALE field redesign. No new production or FSI jobs are permitted solely from this checkMesh finding.

### 2026-11-22 exact first-window deformation: 98512 rank5/cell2758 (read-only)

From saved real private `98512` mesh snapshots at 0.563500→0.563625 s, the independently authored geometry proxy found the SAME face-centre pair 9315→9306 associated with the native rank5/cell2758 concavity, and a **much stronger onset than the old C2 late failure**:

- Face-pair outward signed normal projection: **−176.683719 µm → +997.371856 µm**, net **+1174.055575 µm** in a single 0.000125 s step.
- Face9315 unit normal orientation rotated **9.359856°** in that one step (vs **0.037137°** across the old C2 0.580500→0.580750 s samples).
- Exact algebraic separation of the projection: relative face-centre translation **−66.024801 µm**, normal rotation **+1240.080376 µm**; sum **+1174.055575 µm**.
- Actual fluid mesh vertex displacements (µm, X/Z): 3916 (−43.708, +28.120); 3917 (+195.144, −46.691); 3918 (+977.382, −306.685); 3919 (+1038.250, −322.121). Physical bed/wall vertices 3922/3923 remain exactly stationary. These 1-mm-class motions are fluid mesh coordinates, **not proof of seagrass blade motion**.
- The 98512 `0.5635` cell2758 is natively `Mesh OK`; `0.563625` fails one concave cell and one face-tet check. Native checkMesh remains authoritative, and the independent face-centre pair is a geometric proxy, not a replacement for native code.
- The previous Python `finite_difference_vertex_attribution` was a 16-step midpoint integration of a nonlinear normal/centroid response. It raised `SENSITIVITY_NUMERIC_CLOSURE_FAILURE` on the 9.36° / 1-mm deformation; this exception is from the **read-only analysis**, not another FSI solver or new filesystem failure. It must never invalidate the already-printed point coordinates or exact two-term rotation/translation decomposition.
- `compare-98512-and-c2-cell2758.py` now uses a finite **exact order-averaged vertex substitution** (permutation-based counterfactual/Shapley attribution). For up to seven moving face vertices, all endpoint-contribution sums mathematically telescope to the observed full projection change; synthetic 1-mm nonuniform motion and zero-motion CI tests pass. Note: attribution is not a unique physical causal split and counterfactual intermediate vertex layouts are not real FSI states. This diagnostic is strictly read-only and does not start Slurm.
- C2 0.563625 first-window mesh geometry was not saved. The updated comparison checks whether C2 and 98512 have precisely identical source mesh coordinates at 0.563500, but it cannot claim how C2's individual vertices moved at the unsaved first step.
- Repair design implication: The failed 2× near-bed diffusivity patch produced a major first-step mesh-motion gradient and a 9.36° rotation at the fixed bed. Do not assume larger coefficient implies safer ALE; no modified field/mesh should become a production restart without *native* first-window mesh validation and full long-time FSI acceptance. No new run authorized from this report.

### 2026-11-22 **repaired large-motion comparison finished**: exact paired-cell diagnostics

The real read-only geometry comparison run by the user on the HPCC completed without errors. It checked **both the independent native checkMesh outputs and the analytic exact signed face-centre projection decomposition**, including an exactly closed symmetric vertex permutation attribution.

**Common starting mesh is identical:** C2 trial97576 and failed bed+2x trial98512 have a maximum **zero** coordinate difference at their common restart t=0.563500 s for processor5. This is proof of matching *starting mesh points*, **not proof that all fields/structural states match**.

| Evidence for rank5 cell2758 | C2 at 0.580500 -> 0.580750 | bed+2x at 0.563500 -> 0.563625 |
|---|---:|---:|
| native concave rank5/cell2758 | 1 at later endpoint | 1 at first-step endpoint |
| native face-tet failure | 0 | 1 |
| face9315->9306 projection at earlier snapshot | -2.065299 µm | -176.683719 µm |
| face9315->9306 projection at failing snapshot | +0.204039 µm | +997.371856 µm |
| signed projection change | +2.269338 µm | +1174.055575 µm |
| face9315 unit-normal rotation | 0.03713748° | 9.35985603° |
| contribution from relative centre motion | -2.690150 µm | -66.024801 µm |
| contribution from face-normal rotation | +4.959488 µm | +1240.080376 µm |
| exact permutation attribution 3919 | +2.629760 µm | **+689.562337 µm** |
| exact permutation attribution 3918 | +2.205446 µm | **+517.335372 µm** |
| exact permutation attribution 3917 | -1.201522 µm | -45.824803 µm |
| exact permutation attribution 3916 | -1.364347 µm | +12.982669 µm |
| bed nodes3922/3923 | 0 µm motion | 0 µm motion |

All the symmetric vertex contributions **close exactly to their observed endpoint projection differences**. The two comparisons have **different durations and different absolute physical times**; do not call them a same-time A/B displacement error. C2 first-step point snapshots at 0.563625 were not saved.

**Physics-informed mechanism for investigation, NOT fully proven cause:** OpenFOAM.com v2512 `displacementLaplacianFvMotionSolver::solve()` explicitly re-solves a `fvm::laplacian(diffusivity, cellDisplacement)` after correcting the diffusivity. The motion solver then derives points using the stored displacement/initial reference, so an abrupt, rank5-only *constant* diffusivity field change while restarting from an already deformed mesh can re-distribute the existing **absolute** mesh displacement at the first step, without an equally large new structural boundary movement. The ~1.09 mm interior motion in 125 μs near fixed bed is consistent with this *hypothesis*, but alone cannot prove which combination of initial pointDisplacement, absolute displacement solver, rank-interface consistency, interpolation and preCICE boundary update caused it. Original OF v2512 source: https://api.openfoam.com/2512/displacementLaplacianFvMotionSolver_8C_source.html.

**Immediate constraints:** WITHDRAW the failed +2.0 negative-Y bed patch; do not restart from 98512 or loosen mesh quality. Do not try more gain sweeps without verifying start-state identity (pointDisplacement and points0 in all 8 ranks, native face motion, structural restart). Any eventual redesign must account for the *transient of changing the ALE PDE*, not merely make a better instantaneous geometry at 0.58075. A time-continuous update might be an option, but is unproven and must be shown to satisfy all native mesh, coupled force, displacement and checkpoint gates before long production.

**Next evidence gate, entirely read only**: compare hashes of `fluid/processor{0..7}/0.5635/pointDisplacement` and `0.5635/polyMesh/points` among source trial96763, C2 trial97576 and failed trial98512; inspect `points0` on disk (do not guess its directory), field SHA-256 and mesh-motion configuration. Analyze absolute vs incremental ALE displacement and first-window boundary moves. Do not claim a structural 1 mm jump unless the corresponding structural displacement or interface point values are actually observed.

### 2026-11-22 final no-Slurm restart-state differential check (after exact geometry proof)

Pinned script: `hpcc/ale-repair-96764/audit-restart-state-96763-c2-98512-readonly.py`. It checks SHA-256 equality in all **eight MPI partitions**, at the **identical physical restart timestamp 0.5635 s** in the certified source 96763, C2 97576, and failed bed+2x 98512. Checked fields: polyMesh/points, pointDisplacement, U, p, phi, constant reference motion diffusivity, fvSchemes/fvSolution, and present points0/dynamicMeshDict variants. It prints differences only and fails closed if required snapshot files are missing. This is a *read-only integrity and configuration comparison*, NOT a simulation validation or dynamic-mesh motion proof.

If the mesh coordinates, pointDisplacement and other initial states are unchanged but the motion diffusivity differs, abrupt re-equilibration of the *absolute displacement* elliptic mesh solution becomes the leading hypothesis for 98512's approximately 1-mm first-step interior movement. Even then, the long-time C2 near-concavity at 0.58075 remains a separate original geometry-robustness problem. If the restart displacement/reference states differ, first resolve that inconsistency instead. Do not alter original source or claim physical restart is validated from hashes.

### 2026-11-22 completed 8-rank 0.563500 s restart-state SHA audit

The user's actual HPCC execution of `audit-restart-state-96763-c2-98512-readonly.py` returned:

```text
DIFFERENT reference_motion_diffusivity rank 5 {
 "source_96763": "5d176429081ec91d",
 "C2_97576": "f5d61356b5be71b3",
 "bad_gain2_98512": "7cfdb551c2b500fe"
}
HASH_AUDIT_SUMMARY {
 "counts":{"different":1,"missing":24,"same_all":71},
 "different_ranks_by_field":{"reference_motion_diffusivity":[5]}
}
NO_FSI_SUBMITTED; HASH_MATCH_IS_NOT_NATIVE_RESTART_VALIDATION
```

At the common restart `t=0.563500 s`, the tested files across 8 fluid partitions (including `pointDisplacement`, `polyMesh/points`, `U`, `p`, `phi`) have matching SHA-256 in all three cases; the **only identified saved file difference is rank5/constant/motionReferenceDiffusivity**. The 24 missing comparisons are optional locations such as `points0`/dynamicMeshDict candidates; **the audit does not identify which keys were missing or prove whether points0 is present under another path**. Thus avoid claiming full ALE solver in-memory state or structural restart equivalence.

Combined with independent native mesh checks: **C2 (gain0.85 at positive Y) passes the first 0.563625 s check and fails at 0.580750 s**, whereas the rank5 C2+negative-Y gain2.0 modification in **98512 fails at 0.563625 s** with 1 concave cell2758 + 1 face-tet failure and 9.35986 deg rotation of face9315. Earlier C1 (gain1.20 radius8 at positive-Y cell3535) also failed in the first window, reinforcing that changing diffusivity at an already deformed restart is sensitive. This is a controlled file-level contrast, but native motion-law and initial points0 are not yet verified.

**Strongest supported working hypothesis:** the changed spatial diffusivity of the displacement-Laplacian ALE solver caused an initial redistribution of absolute mesh displacement near the pinned bed. Do not claim a proved root cause from hash equality alone; check the custom seagrass558RampFile C++ implementation, time update of the coefficient field, processor coupling, and points0 before proposing a continuous-time coefficient ramp or a mesh redesign.

**Engineering gate:** Reuse original untouched 0.5635 s FSI source and SHA-verified backups; withdraw 98512 gain2.0; do not use any failed snapshots as accepted restarts. Any new candidate needs (i) documented coefficient-transition model, (ii) native guard PASS in a two-window short test before 144-window or longer native FSI, (iii) preserve native concavity, face-tet, non-orthogonality<=65 deg, skew<4, meshCo<=0.5 and participant exit codes 0, (iv) force/displacement and 8-rank/solid checkpoint acceptance, (v) cross 0.580750 and subsequently 0.603500. No automatic production job until validated.

### 2026-11-22 exact native dynamicMeshDict and compiled custom diffusivity verified

From actual UM HPCC read-only command, the accepted source trial96763 fluid `constant/dynamicMeshDict` contains:

```foam
dynamicFvMesh dynamicMotionSolverFvMesh;
motionSolverLibs ("libfvMotionSolvers.so" "/home/mc55028/hpcc-fsi/three-day-resume-20261119/.mesh-repair558-data.29CSy1/lib/libseagrass558RampDiffusivity.so");
solver displacementLaplacian;
displacementLaplacianCoeffs
{
    diffusivity seagrass558RampFile
        motionReferenceDiffusivity
        0.5535 0.5565 0.925 1.000 1.5 -0.35;
}
```

The installed custom `.so` SHA-256 is exactly `1032420382c07a8138f122199017013ed0aa242410f73a41330cbff199aac1a2`, matching the frozen production verifier. A `find` under the known helper workspace at maxdepth4 returned no `*Diffusivity*.C`, `*Diffusivity*.H`, `*Ramp*.C`; the identical command under `processor5` did not find a file literally named `points0` within maxdepth4. These absences DO NOT imply source or reference points are absent elsewhere, nor that the solver did not initialize its `points0()` state in memory.

**Crucial distinction:** The first two custom numbers `0.5535 0.5565` are chronologically **before** physical restart at `0.5635`, but without the compiled custom model's C++ source one cannot assert their meaning or that a ramp has already completed. Nor do the other parameters `0.925 1.000 1.5 -0.35` have a verified parameter definition. Unlike upstream `displacementLaplacian`, `seagrass558RampFile` is a project-defined runtime-selected model, not a standard named diffusivity in the official v2512 documentation.

Official OpenFOAM v2512 upstream `displacementLaplacianFvMotionSolver::solve()` explicitly calls `diffusivity().correct()` then updates point/cell displacement boundary fields and solves a Laplacian equation for `cellDisplacement`; the `curPoints()` implementation relates initial/reference points to `pointDisplacement`: https://api.openfoam.com/2512/displacementLaplacianFvMotionSolver_8C_source.html . This confirms **why** altered reference diffusivity could change the reconstructed interior ALE displacement at the first iteration. It does NOT, alone, prove the particular custom ramp algorithm.

The prior 8-rank SHA audit did NOT compare the potentially relevant runtime input `cellDisplacement` field, nor determine all `points0` variants. Added strictly read-only diagnostic `hpcc/ale-repair-96764/audit-ale-ramp-lib-and-cellDisplacement-readonly.py` audits same-instant `cellDisplacement`, `pointDisplacement`, `pointLocation`, several `points0` path candidates and complete case config SHA across source96763, C2 97576 and failed98512. It runs `nm -DC` and `strings -a` against the *same verified custom library* for names and hints without loading or executing it. All output is diagnostic only, never a reason to assume compiled parameter semantics. No solver or Slurm process is launched.

### 2026-11-22 completed static library + all-rank cellDisplacement audit

Actual user's HPCC output of `audit-ale-ramp-lib-and-cellDisplacement-readonly.py`:

- Installed `libseagrass558RampDiffusivity.so` SHA256 is **1032420382c07a8138f122199017013ed0aa242410f73a41330cbff199aac1a2** (pinned good).
- **All 8 ranks** have identical `cellDisplacement`, `pointDisplacement`, and `polyMesh/points` at `t=0.5635 s` in source96763, C2 97576 and failed gain2 98512. This was independently confirmed for `U`, `p`, `phi` in prior audit.
- All 3 `constant/dynamicMeshDict` SHA256 equal: `fe945daf2950091690201828f51e708ce3a6cc7f84254cff6aca6b1a87a927ee`; custom ramp configuration is exactly `motionReferenceDiffusivity 0.5535 0.5565 0.925 1.000 1.5 -0.35`.
- Only rank5 `constant/motionReferenceDiffusivity` differs: original `5d176429081ec91d...`; C2 `f5d61356b5be71b3...`; gain2 `7cfdb551c2b500fe...`; rank0..4,6,7 files identical.
- `pointLocation`, `points0` in tested saved paths, and original time0 displacement fields absent in all 8 partitions; no assertion that `points0()` is missing from runtime.
- `nm -DC` found `Foam::seagrass558RampFile::operator()() const` and **inherited OpenFOAM `Foam::fileDiffusivity::correct()`**, with `Foam::seagrass558RampFile` registered via the motionDiffusivity Istream constructor. `strings` reports `Invalid ALE diffusivity ramp`. Symbols do **not** establish whether this model interpolates in time, how many args are times, or its exact formula.
- OpenFOAM.com v2512 upstream solves `fvm::laplacian(diffusivity().operator()(),cellDisplacement_)` after `diffusivity().correct()`: https://api.openfoam.com/2512/displacementLaplacianFvMotionSolver_8C_source.html .

**Conclusion boundary**: In tested saved on-disk settings the sole differential input is the rank5 reference diffusion field, and the same cell2758 first-step failure is correlated with that modification. Given large interior motion (up to ~1.09 mm) and stationary physical bed, a new elliptic absolute mesh displacement equilibrium is the strongest explanatory mechanism. But do not state the exact *custom* ramp's current-time behaviour as proven without its C++ source or equivalent statically decoded function.

**Next gate**: local read-only search for C++ source or ELF debug information (NOT running the .so). If the model's time interpolation can be verified, only then design a physically continuous transition from the C2 known first-step pass state to a gentle near-bed modified field. Any such scheme needs the identical 0.5635 t0 and **two-window native FSI first-step meshCo, concave and face-tet PASS** before testing long-term avoidance at 0.580750; do not automatically launch production. C2 itself still fails at .58075, so merely undoing 98512 does not solve the original late geometric limitation.

### 2026-11-22 partial ELF disassembly: ramp-time smoothstep **verified**

User executed `nm -D -S -C` and `objdump -d --disassemble='_ZNK4Foam19seagrass558RampFileclEv'` against the exact pinned custom `.so` (`sha256=1032420382c07a8138f122199017013ed0aa242410f73a41330cbff199aac1a2`). No custom `*.C` or `*.H` file found inside the helper directory at maxdepth7, and `readelf -W -S` found no `.debug_info`, `.debug_line`, `.gnu_debuglink`.

The `operator()() const` symbol address is **0x20780**, length **0x0e51** bytes, so stop-address is **0x215d1**. The user pasted **only the first 160 disassembly lines**, ending at ~0x209dd; the rest of the function is **not yet inspected**.

In the actually supplied instructions, the object members at offsets `+0x1b0` and `+0x1b8` are used to form `(meshTime - time0)/(time1-time0)`. Branches implement saturation to [0,1]. At 0x20930–0x2094c the coefficient is transformed as `s = u*u*(3-2*u)` (smoothstep). At 0x2081b–0x20859, two other scalar members at offsets `+0x1c0`/`+0x1c8` are interpolated `a + s*(b-a)` and a dynamic string `exponent` is passed into OpenFOAM field creation machinery. Given the exact 6 input tokens `0.5535 0.5565 0.925 1.000 1.5 -0.35`, a **very strong but not yet constructor-verified interpretation** is:
- `time0 = 0.5535`, `time1 = 0.5565`
- first interpolated quantity is `exponent` from `0.925` to `1.000`
- `1.5`, `-0.35` are other parameters requiring the unexamined remainder of the implementation to interpret.

At the actual FSI recovery `t=0.5635`, `t>0.5565`, so this existing smoothstep is **already saturated at 1** if the inferred time interpretation is confirmed. Replacing the rank5 reference face diffusivity after this historical transition therefore **does not automatically gain a new gradual transition**. This supports the ALE re-equilibration hypothesis, but does not establish the complete spatial coefficient formula or rule out solver state/processor interaction.

**Do not change model time constants, target field, or solver based on this partial ELF disassembly.** Next read-only evidence: dump the remaining full named `operator()` disassembly (prefer `objdump -d -M intel --no-show-raw-insn --disassemble=...` to a single `/tmp` text file) and ELF data literal context. Confirm constructor input order and full field expression with source if it can be found; do not execute or patch the `.so`. Then design continuity-respecting mesh motion, first-window native gate and bounded FSI verification.
