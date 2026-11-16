# Own orchestration repair: cross-Slurm ALE-FSI restart (2026-11-16)

**Scope:** Only our Python/Bash orchestration and case-copy policy. No OpenFOAM, preCICE, CalculiX, adapter, mesh or physics source modifications. No mutations of active job 91543.

## Confirmed defects in our pipeline

1. An older Slurm job attempted to evaluate `segment.py` as Bash (the logged `import: command not found` and `def sha(path)` syntax error). Use explicit `python3` in a sanitized container shell; check `BASH_ENV`/ `ENV`. The current version of `compute.sh` already uses `python3`.
2. Our `clean-production/segment.py` discarded all old numeric fluid time folders when staging each new MPI job. This loses potentially relevant restart history. The fix stops discarding them. Retaining history is necessary conservatism, **not proof** that OpenFOAM's nonserialized moving-mesh old state is reconstructed.
3. Our `submit.sh` automatically queued six 72h jobs from a checkpoint without real cross-session force/mesh continuity proof. The fix adds a fail-closed native-restart evidence gate (20 coupled windows required before any production chain approval).
4. The old duplicate-job guard checked only `fsi-real-long`, but the active 72h job is named `fsi-3d-safe`. The fix checks all current FSI/precice/ccx/seagrass job names.
5. The old verifier tolerated Mesh Courant spikes of arbitrary magnitude inside the first restarted window, provided the last value was low. The new cross-job policy rejects any Mesh Co >0.5; historical stage-0 exception remains explicitly separate.

## Evidence of the still-unresolved numerical failure

- Source 91006 at t=0.0325s has aligned saved displacement and mesh coordinates on all 8 ranks.
- Direct restart with new session: mesh Co maximum 20848.68896415; fluid SIGFPE in GAMGSolver. This is a symptom, not evidence of a solver defect.
- Nonzero displacement initialization alone: first computed fluid force 52.8753 N vs expected 0.0176638208 N.
- Both Force and Displacement initialized: same 52.8753 N first computed load, so force initialization alone cannot fix it.
- Uninterrupted long job 91543 crossed that time with mesh Co ~0.2374.
- Hypothesis not yet proven: fluid/solid reference-frame mismatch in our restart initialization, compounded by unpersisted ALE history. Do not blame or patch upstream code.

## 91767 disclosure and repair

The first submitted 2-window test (91767) was pinned at
`5d995bebb2df7c887019a941cd0b6791f5569dd4`. Its
`--self-test` and `--preflight` used `FSI_ISOLATED_CORE`, **but its
actual `run()` loaded the older `seagrass-fsi-mainline/bin/segment.py`**.
This is OUR orchestration defect, not a solver defect. Results from 91767
may still inform the original-reference / initial-data hypothesis, but must
NOT be represented as validating the corrected checkpoint copy policy.
Do not cancel or modify 91767 in flight; preserve it as an old-driver control.

Fixed in commit `99812f5239d8866b728f1baa0492a67648773294`.
A subsequent regression test now invokes the actual `run()` entrypoint
with an isolated sentinel CORE and stops before launching any solver.
GitHub Actions proves the **correct Python module is selected**, not that
physical continuity is achieved. A new independent test, if warranted after
reading 91767 results, must use revision >=
`b8ab0eb986175b8ec126b4e65449edbbc6880f21` pinned throughout.

## Real trial 91767: run success != restart validity

User-observed trial 91767 at t=0.0325 -> 0.03275:
- 2/2 preCICE windows accepted, 50 total coupling iterations, both participants exit 0.
- Max fluid Courant 0.28998, max Mesh Courant 0.32928, native mesh PASS.
- Initial mapped Force Fx 0.0176638208 N exactly matches the prior state.
- The first computed OpenFOAM blade force is 11.5152783 N
  (relative error 650.91322 = about 652 times the original magnitude).
- Thus the outer scientific acceptance must FAIL even when the solver
  runtime reports `FSI_LONG_SEGMENT_PASS`. Fix: `segment.py` now enforces
  a first-computed force-continuity gate for each real stage>=1. A specific
  self-test reproduces the 91767 force and requires rejection.
- The older FPE heuristic falsely flagged `trapFpe`/unrelated signal text;
  the verifier now matches actual floating-point exception signal patterns.
  The supplied trial process exit codes are both zero.
- Trial stderr shows two Python entrypoint files were read as Bash, despite
  successful execution. They were passed as positional arguments into the
  sourced OpenFOAM bashrc. The new batch script saves the four values in
  named shell variables and executes `set --` BEFORE sourcing bashrc; CI
  asserts the order. This is an orchestration fix, not a solver modification.
  The exact originating internal source command has not yet been instrumented,
  so do not overclaim causality.

**No further long job is authorized.** The first raw force may belong to
an unaccepted implicit iteration; use the new read-only differential audit to
compare the first and accepted-window force against the 91543 continuous run
before choosing another physical-state repair.

Read-only evidence command, pinned to the branch SHA:
```bash
REV=REPLACE_WITH_CURRENT_PINNED_REPAIR_SHA
OUT="$HOME/hpcc-fsi/crossjob-fix-20261116/audit-91767-continuity-readonly.py"
curl -fLsS "https://raw.githubusercontent.com/merlin959595/seagrass-fsi-hpcc/$REV/hpcc/restart-forensics/audit-91767-continuity-readonly.py" -o "$OUT"
python3 "$OUT" --self-test
python3 "$OUT" --base "$HOME/hpcc-fsi"
```

This only reads saved logs, copies, and watch integrals. It does not
modify 91543, 91767, the 91006 checkpoint, solver sources, or scheduler.

## 91819 falsification: retaining all 15 source time directories is NOT enough

**Actual HPCC evidence supplied 2026-11-16**:
- 91819 staged 15/15 numeric source history time directories in all 8 fluid MPI ranks and disabled `purgeWrite` ONLY in the isolated trial case.
- The amended driver used the pinned private core; self-test + preflight passed, and no automatic continuation was submitted.
- Source 91006 end Fx = 0.0176638208 N; 91819 first computed Fx = **11.515278323918 N**, identical to 91767.
- First accepted watch: **0.0721967879 N** versus uninterrupted 91543 **0.0178807774 N** (relative difference 303.8%).
- Second accepted watch: **-0.120743419 N** versus 91543 **0.0181010198 N** (relative difference 767.1%, opposite sign).
- Mesh Courant peak = 0.32927715580634. `fluid_FPE=false`, no solid nonlinear divergence.
- Our numerical force guard correctly marked 91819 `FSI_LONG_SEGMENT_FAILED`, even though both implicit windows produced watch-integral rows; no `FSI_SEGMENT_RESULT.json` was approved. This is a deliberate scientific rejection, **not proof the subprocesses crashed**.

**Conclusion:** The time-directory-copy defect was real but is **not a sufficient cause** of the numerical discontinuity. In particular, preserving directories does not imply in-memory oldPoints/mesh flux/history or preCICE iteration/state are reconstructed on new process startup. The hypothesis "copy 15 histories fixes restart" has been disproven for this case. Do not submit that same experiment again.

**Next investigation (read-only first):** Check exactly which stored histories are one native time-step apart, OpenFOAM ddt and ALE settings, whether frame references and CCX persistent state are restored in consistent units/time, and the first flow-step force decomposition. Inspect the 91543 continuous reference without altering its files. Do not alter OpenFOAM/preCICE/CalculiX/adapters or restart a 72-hour job.

## 2026-11-16 accepted displacement/pressure audit and confounding controls

- At physical t=0.032625 and t=0.032750, 91819 watch Force0 is 0.0721967879 N and -0.120743419 N versus continuous 91543 0.0178807774 N and 0.0181010198 N. The force path is genuinely wrong even after accepted preCICE iterations.
- The relative Displacement0 watch **integrals** differ from 91543 only 0.00928% and 0.01254%. This does **not** establish equal nodal displacement, local velocity, acceleration, or equivalent fluid volume swept.
- The source 91006 and both restarts have SHA-256 identical p, phi, Uf, meshPhi and V0 at 0.0325 across 8 ranks. The initial force 11.515278323918 N comprises 11.514455344525 N pressure and 0.00082297939296837 N viscous.
- The old-point files are not present as distinct files, which is not proof of a defective solver; meshPhi and V0 **are** present and identical.
- **Important experimental confound:** continuous 91543 starts from 90873 at 0.0025s with `restartFromDeformed true` and no initialized preCICE exchanges. Both 91767 and 91819 restart a new preCICE session at 0.0325s while using `restartFromDeformed false` AND `initialize=yes` for Force and Displacement. Those two changes were deliberately made in OUR case input, not in the third-party solver. Thus the results cannot uniquely identify a missing native ALE history; they may reflect fluid motion initialization or frame/initial-data mismatch.
- **New evidence-first step:** compare first pressure solver traces and source/reference interface-integral derivatives at identical physical time, using `audit-91819-continuous-vs-restart-first-pressure-readonly.py`. Interpret derivatives of watchintegral as integrated quantities only.
- No further Slurm candidate before the above read-only evidence is reviewed. The working three-day job 91543 remains untouched.

## Correction after pressure-trace evidence (2026-11-16, required reading)

**Our previous verdict used an invalid comparison.** Comparing the first,
unaccepted OpenFOAM/PIMPLE blade force from the restarted session
(11.5152783 N) to the previous *accepted preCICE coupling window* force
(0.0176638208 N) produced an asserted 650.9-fold error. This compares
different iteration states. The uninterrupted continuous 91543 case also
has a provisional first force of **11.15407655 N** at the same 0.032625s
time; 91006 has 11.15324928 N at 0.0325s. The directly comparable
provisional force difference between restarted and uninterrupted cases
at 0.032625s is only **3.2383%**. A high early PIMPLE pressure force
alone is not evidence of a broken solver or an invalid restart.

**A second error was our own parser:** the old
`audit-91819-continuous-vs-restart-first-pressure-readonly.py` counted
`Sum of moments` Total/Pressure/Viscous as forces, yielding spurious
`FINAL_FORCE_COMPONENTS` around 1e-10 N. The parser is now restricted
to the section between `Sum of forces` and `Sum of moments`, with
regression tests for both sections. Counts of `Time =` blocks are called
fluid time records, NOT accepted preCICE iterations.

**The restart is STILL scientifically invalid:** actual accepted watch
Force0 is 0.0721967879 N and -0.120743419 N for 91819 versus
0.0178807774 N and 0.0181010198 N in uninterrupted 91543.
Core `validate_cross_job_force` now only records provisional forces
as diagnostics without vetoing an otherwise valid implicit iteration.
Acceptance is gated by `validate_accepted_force_continuity`
and, where available, same-physical-time continuous controls.

**Stronger discriminating clue:** the first recorded Mesh Courant maximum
at physical t=0.032625 is ~0.129329 in the new session, versus
~0.0000180955 in uninterrupted 91543, a ~7147-fold difference.
This is a FIRST-RECORD comparison rather than the maximum over the whole
window, and warrants checking initial ALE interface data and reference
setup before pressure-solver changes. It does not uniquely establish the
cause: restart 91819 simultaneously changes preCICE initial data and
`restartFromDeformed` compared with 91543.

No new Slurm job is justified until the corrected force trace is examined.
Never patch third-party solver or adapter sources merely because a
continuous and a cross-process run diverge.

## One small, isolated real test while 91543 continues

Use the **commit SHA** of this repair branch in raw GitHub URLs so test binaries/scripts stay pinned. On the HPCC login node:

```bash
BASE="$HOME/hpcc-fsi"
FIX="$BASE/crossjob-fix-20261116"
REV="REPLACE_WITH_REPAIR_COMMIT_SHA"
URL="https://raw.githubusercontent.com/merlin959595/seagrass-fsi-hpcc/$REV/hpcc"
mkdir -p "$FIX"
curl -fLsS "$URL/clean-production/segment.py" -o "$FIX/segment.py"
curl -fLsS "$URL/clean-production/restart-initial-data-candidate.py" -o "$FIX/restart-initial-data-candidate.py"
curl -fLsS "$URL/clean-production/restart-both-initial-fields-candidate.py" -o "$FIX/restart-both-initial-fields-candidate.py"
curl -fLsS "$URL/restart-forensics/try-aligned-reference-and-both-initial.py" -o "$FIX/try-aligned-reference-and-both-initial.py"
curl -fLsS "$URL/restart-forensics/submit-our-restart-2window-20261116.sh" -o "$FIX/submit-our-restart-2window-20261116.sh"

python3 -m py_compile "$FIX"/*.py
bash -n "$FIX/submit-our-restart-2window-20261116.sh"
FSI_ISOLATED_CORE="$FIX/segment.py" python3 "$FIX/try-aligned-reference-and-both-initial.py" --self-test
FSI_ISOLATED_CORE="$FIX/segment.py" python3 "$FIX/try-aligned-reference-and-both-initial.py" --preflight
# Explicit user step; submits only one 2-window Slurm job into a new trial dir:
bash "$FIX/submit-our-restart-2window-20261116.sh"
```

The test copies the original t=0.0325s checkpoint without changing it. It keeps all available source fluid time history; initializes Force and Displacement; and tests the original-reference adapter setting `restartFromDeformed=false` **in the isolated case copy only**. This is configuration of our experimental case, not modification of solver/adapter software.

The two-window acceptance criteria are both solver processes exit 0, both windows converge, native mesh checks pass, Mesh Co and fluid Co <=0.5, mapped initial force within 10%, first computed force within 20% of source and no floating-point error. If the test fails, preserve and inspect logs; **never** auto-start long-chain jobs.

## Offline CI

`.github/workflows/test-crossjob-restart-safety.yml` validates shell/Python syntax, tightened Courant logic, and mocked Slurm submission/duplicate-protection policy. CI passing is NOT a scientific cross-job FSI qualification.

## Do not do

- No `scancel`, no signals to 91543
- No rewriting `three-day-proven/long-job-91543`
- No edits to OpenFOAM, preCICE, CalculiX or adapters
- No promotion of a candidate just because files exist or a test starts cleanly
