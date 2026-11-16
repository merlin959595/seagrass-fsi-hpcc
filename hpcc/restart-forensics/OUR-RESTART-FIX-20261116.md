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
