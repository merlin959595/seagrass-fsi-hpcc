#!/usr/bin/env bash
# Prepare a self-contained, reproducible transfer archive from the verified WSL case.
# Does not stop solvers, mutate case files, or include any currently growing run results.
set -euo pipefail
ROOT="${SG_ROOT:-$HOME/OpenFOAM/merlin-v2512/run/seagrass-fsi-30s}"
OUT="${SG_ARCHIVE:-$HOME/seagrass-implicit-hpcc-inputs-20261111.tar.gz}"
HISTORY="runs/fsi-0.02s-20261102T030440Z-10ae15"
if [[ ! -d "$ROOT" ]]; then echo "ERROR: source root not found: $ROOT" >&2; exit 1; fi
if [[ -e "$OUT" || -e "$OUT.sha256" ]]; then
  echo "STOP: destination already exists: $OUT or $OUT.sha256" >&2; exit 1
fi

required=(
  "fsi-implicit-production/run_production.py"
  "fsi-implicit-production/run.sh"
  "fsi-explicit-test/prepare_inputs.py"
  "fsi-explicit-test/inputs/SOURCE_BINDING.json"
  "fsi-explicit-test/inputs/FROZEN_BINDING.json"
  "fsi-explicit-test/inputs/fluid/0/U"
  "fsi-explicit-test/inputs/fluid/constant/motionReferenceDiffusivity"
  "fsi-explicit-test/mesh-guard/lib/libseagrassExplicitMeshGuard.so"
  "scripts/env.sh"
  "scripts/resources.py"
  "scripts/native/bin/ccx_preCICE_persistent_v2"
  "scripts/native/lib/libseagrassReferenceRestart.so"
  "$HISTORY/assessment.json"
  "$HISTORY/checkpoint_manifest.json"
  "$HISTORY/precice-config.xml"
)
for file in "${required[@]}"; do
  if [[ ! -s "$ROOT/$file" ]]; then
    echo "ERROR missing required source: $ROOT/$file" >&2; exit 1
  fi
done

# Inventory source/native files for rebuilding under the HPCC container ABI.
echo "===== Native source/build inventory ====="
find "$ROOT/scripts/native" "$ROOT/fsi-explicit-test/mesh-guard" \
   -maxdepth 4 -type f \( -name '*.c' -o -name '*.C' -o -name '*.cpp' -o -name '*.h' \
   -o -name '*.f' -o -name '*.f90' -o -name 'Makefile' -o -name '*.sh' \) \
   -printf '%P\n' | head -n 80 || true

items=(
  "fsi-implicit-production/run_production.py"
  "fsi-implicit-production/run.sh"
  "fsi-explicit-test/prepare_inputs.py"
  "fsi-explicit-test/inputs"
  "fsi-explicit-test/mesh-guard"
  "scripts"
  "$HISTORY/assessment.json"
  "$HISTORY/checkpoint_manifest.json"
  "$HISTORY/precice-config.xml"
)
if [[ -d "$ROOT/modeling" ]]; then items+=("modeling"); fi
for optional in \
  fsi-implicit-production/run_chain.sh \
  fsi-implicit-production/qualify_restart.py \
  fsi-implicit-production/launch_restart_wsl.sh \
  fsi-implicit-production/launch_recovery_wsl.sh; do
  if [[ -f "$ROOT/$optional" ]]; then items+=("$optional"); fi
done
echo "===== Source summary ====="
du -sh "$ROOT/scripts" "$ROOT/fsi-explicit-test/inputs" "$ROOT/fsi-explicit-test/mesh-guard"
echo "===== Building transfer archive (NO active runs) ====="
tmp="$OUT.partial"
trap 'rm -f "$tmp"' EXIT
tar -czf "$tmp" -C "$ROOT" "${items[@]}"
tar -tzf "$tmp" >/dev/null
mv "$tmp" "$OUT"
trap - EXIT
sha256sum "$OUT" > "$OUT.sha256"
ls -lh "$OUT" "$OUT.sha256"
echo "===== SHA256 ====="
cat "$OUT.sha256"
echo "TRANSFER_ARCHIVE_READY"
