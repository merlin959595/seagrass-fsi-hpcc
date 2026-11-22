#!/usr/bin/env bash
# Strictly read-only extraction of the exact pinned custom ALE library's
# COMPLETE operator() disassembly. Never loads the .so or touches FSI data.
set -Eeuo pipefail
A="$HOME/hpcc-fsi/three-day-resume-20261119/.mesh-repair558-data.29CSy1"
LIB="$A/lib/libseagrass558RampDiffusivity.so"
EXPECTED="1032420382c07a8138f122199017013ed0aa242410f73a41330cbff199aac1a2"
SYM="_ZNK4Foam19seagrass558RampFileclEv"
if [[ ! -s "$LIB" ]]; then
    echo "LIBRARY_MISSING_NO_ACTION $LIB" >&2
    exit 10
fi
ACTUAL="$(sha256sum "$LIB" | awk '{print $1}')"
if [[ "$ACTUAL" != "$EXPECTED" ]]; then
    echo "PINNED_LIBRARY_HASH_DIFFERENT_NO_ACTION $ACTUAL" >&2
    exit 11
fi
for tool in nm objdump readelf mktemp; do
    command -v "$tool" >/dev/null || { echo "TOOL_MISSING $tool" >&2; exit 12; }
done
# Do not use grep -q here: with 'set -o pipefail', grep may close the
# pipe after the first match and make nm fail with SIGPIPE (status 141).
# grep -F consumes the entire nm output, so the status is trustworthy.
if ! nm -D -S "$LIB" | grep -F -- "$SYM" >/dev/null; then
    echo "EXPECTED_OPERATOR_SYMBOL_MISSING_OR_NM_ERROR_NO_ACTION" >&2
    exit 13
fi
DEST="$(mktemp -d /tmp/seagrass558-elf-static.XXXXXXXX)"
REPORT="$DEST/full-seagrass558-operator-readonly.txt"
{
    echo "SOURCE_LIB=$LIB"
    echo "LIB_SHA256=$ACTUAL"
    echo "CUSTOM_OPERATOR_SYMBOL=$SYM"
    echo "==== ELF SECTIONS ===="
    readelf -W -S "$LIB" | grep -E '\.text|\.rodata|\.debug_info|\.debug_line|\.gnu_debuglink' || true
    echo "==== OPERATOR SYMBOL AND LENGTH ===="
    nm -D -S -C "$LIB" | grep -F 'Foam::seagrass558RampFile::operator()() const'
    echo "==== FULL NAMED OPERATOR() DISASSEMBLY IN INTEL FORMAT ===="
    objdump --no-show-raw-insn -M intel -d --disassemble="$SYM" "$LIB"
    echo "==== LITERAL CONSTANT DATA USED BY THE TIME SMOOTHSTEP SECTION ===="
    objdump -s -j .rodata --start-address=0x26960 --stop-address=0x26a40 "$LIB" || true
    echo "==== END OF READ-ONLY BINARY EVIDENCE ===="
} >"$REPORT"
if ! grep -Fq "$SYM" "$REPORT"; then
    echo "OPERATOR_DISASSEMBLY_NOT_CAPTURED" >&2
    exit 14
fi
echo "PINNED_LIBRARY_HASH_PASS $ACTUAL"
echo "DISASSEMBLY_RECORD=$REPORT"
echo "DISASSEMBLY_LINES=$(wc -l < "$REPORT")"
echo "FIRST_16_RELEVANT_LINES"
grep -E '^ *(207[89a-f][0-9a-f]|208[0-9a-f]{2}|209[0-9a-f]{2}):' "$REPORT" | head -n 16 || true
echo "NO_SLURM_NO_SOLVER_NO_FSI_CASE_FILES_CHANGED"
echo "SEND_THE_CONTENT_OF_DISASSEMBLY_RECORD_FOR_FULL_STATIC_MODEL_ANALYSIS"
