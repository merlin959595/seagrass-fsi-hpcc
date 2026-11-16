# 3D seagrass ALE–FSI cross-job restart forensics (2026-11-16)

## Certified scientific evidence

- Continuous job **91006**, initialized from 90873 at physical time **0.0025 s**, completed **240 accepted coupled windows** ending at **0.0325 s**. The structural watch integral had Force0 ~ **0.0176638208 N** at its relative time 0.03 s.
- This exact 0.0325 s source snapshot had correct original/deformed coordinates:
  `constant/polyMesh/points + pointDisplacement(0.0325) == 0.0325/polyMesh/points`
  with **zero residual on all eight MPI ranks**; saved `cellDisplacement` had a physically plausible maximum **~5.785 mm**.
- A direct new preCICE session from **0.0325 s** without displacement initialization had **mesh Courant ~20,848**, a fluid GAMG SIGFPE, and zero accepted windows.
- **91538**, `Displacement initialize=yes`, did initial displacement map, maximum mesh Courant ~2.79, but produced first computed fluid Force0 = **52.8753 N**, and nonlinear CalculiX divergence.
- **91542**, both `Force` and `Displacement initialize=yes`, correctly initialized Force0 = **0.0176638208 N** and still produced *exactly* **52.8753 N** first computed Force0, with the same nonlinear divergence. Therefore merely initializing Force **does not correct** the first flow/moving-mesh numerical discontinuity.
- Continuous job **91543** from 90873, at last user observation **310/1280 accepted** and maximum mesh Courant ~**0.2374**, having crossed 0.0325 s successfully **without a new preCICE session**. This job MUST remain untouched.

## Strong, not-yet-verified hypothesis

The solid restart sets its interface reference through `restart_reference/Solid-Mesh.coords`. OpenFOAM adapter 1.4.0 `Interface.C` registers the fluid ALE interface at deformed current positions when `restartFromDeformed=true`, but subtracts the stored point displacement to register original positions when `false`. If CCX solid reference coordinates are original while fluid interface coordinates are deformed, the two mapped meshes have inconsistent reference frames. This can cause apparent displacement/motion discontinuity when absolute `Displacement` is mapped.

**The prior trial of `restartFromDeformed=false` (91504) did not initialize nonzero displacement and thus does not test a valid `false + initialize=yes` combination.** Treat this combination as a controlled hypothesis, not a known solution. Never modify source checkpoint 91006 or ongoing 91543.

In addition, the original stage copy driver `hpcc/clean-production/segment.py` removes **all earlier numeric time directories** for each fluid processor and preserves just the latest one. This may lose previous-step field and mesh-motion history (oldPoints, V0/V00, native mesh flux), even when `phi` and `pointDisplacement` hash-identical. The effect on this specific timestep must be tested; missing earlier time directories alone is not proof of root cause.

## Safe audit (read only)

```bash
BASE="$HOME/hpcc-fsi"
SRC="$BASE/clean-production-src"
URL="https://raw.githubusercontent.com/merlin959595/seagrass-fsi-hpcc/upgrade/openmpi-5.0.7-hpcc/hpcc/restart-forensics"
curl -fL "$URL/audit-cross-job-fields-and-frames.py" -o "$SRC/audit-cross-job-fields-and-frames.py"
python3 "$SRC/audit-cross-job-fields-and-frames.py" --self-test
python3 "$SRC/audit-cross-job-fields-and-frames.py"
```

This reports all-rank identity/availability of `U,p,phi,Uf,cellDisplacement,pointDisplacement,k,omega,nut`, numeric-time folder histories, dynamic-mesh controls, reference policy, and original/new force continuity.

## Isolated 2-window hypothesis test (not automatic; review audit first)

The test is in:
- `hpcc/restart-forensics/try-aligned-reference-and-both-initial.py`
- `hpcc/restart-forensics/submit-aligned-reference-both-initial.sh`

It uses a new directory and a separate Slurm allocation; **never touches 91543**. The only differences from 91542 are `restartFromDeformed=false` (to register fluid mesh in CCX's original reference frame) while keeping Force and absolute Displacement `initialize=yes`.

**Failure-closed release gate**: two accepted real windows, both solvers exit 0, force continuity and first computed force within respectively 10% and 20% of original, no post-initial Mesh Co violations and native checkMesh. Do not use for 3-day continuation without passing an additional longer test.

## References
- [Official OpenFOAM adapter v1.4.0 `Interface.C`](https://github.com/precice/openfoam-adapter/blob/v1.4.0/Interface.C), lines 224–244
- [preCICE OpenFOAM adapter restart configuration](https://precice.org/docs/adapters/openfoam/config/)
- [preCICE initialization semantics](https://precice.org/docs/couple-your-code/step-by-step/initializing-coupling-data/)
- [OpenFOAM v2512 displacementLaplacian solver](https://api.openfoam.com/2512/displacementLaplacianFvMotionSolver_8C_source.html)
- [preCICE adapter implicit checkpoint mesh history](https://precice.org/docs/adapters/openfoam/extend/)
- [Independent 2025–2026 preCICE forum report of extremely similar post-restart force spikes](https://precice.discourse.group/t/instability-after-restart-in-coupled-fsi-simulation-openfoam-calculix-precice/2686)

**No universal documented fix exists for this precise combination as of the source review.** Numerical restart is not verified until real post-restart coupled-window and force/mesh continuity evidence passes.
