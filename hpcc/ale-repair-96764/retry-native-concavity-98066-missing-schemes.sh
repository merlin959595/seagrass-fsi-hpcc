#!/usr/bin/env bash
# Repair ONLY an incomplete PRIVATE checkMesh diagnostic and rerun 2 snapshots.
# Reuses files from 98066; does not re-copy meshes or touch FSI/production.
# Source FSI and verified backups are treated read-only.
set -Eeuo pipefail
P="/data/icto/${USER:?}/seagrass-fsi558-runs.sNIpi9"
SRC="$P/trial-97576-repair96764-c2-stage1/runs/hpcc-implicit-002/fluid"
DST="$P/diagnostics/native-concavity-97576-c2"
IMG="$HOME/seagrass-fsi-ompi507-scotch-time.sif"
[[ -d "$SRC" && -d "$DST" && -s "$IMG" ]] || {
    echo "MISSING_EXISTING_PRIVATE_DIAGNOSTIC_OR_CONTAINER_NO_ACTION"; exit 20;
}
[[ -f "$DST/checkNativeConcavity.sbatch" && -f "$DST/native-check.sh" && -s "$DST/checkMesh-0.5805.log" && -s "$DST/checkMesh-0.58075.log" ]] || {
    echo "ORIGINAL_98066_DIAGNOSTIC_FILES_MISSING_NO_ACTION"; exit 21;
}
for t in 0.5805 0.58075;do
    grep -Fq 'cannot find file' "$DST/checkMesh-$t.log" || {
        echo "ORIGINAL_DIAGNOSTIC_NOT_MISSING_DICTIONARY_NO_ACTION $t"; exit 22;
    }
    grep -Fq "/processor0/system/fvSchemes" "$DST/checkMesh-$t.log" || {
        echo "ORIGINAL_DIAGNOSTIC_FAILURE_OTHER_THAN_FVSCHEMES_NO_ACTION $t"; exit 22;
    }
done
if squeue -h -u "$USER" -n ale96764repair,ale96764go,ale96764diag | grep -q .;then
    echo "FSI_REPAIR_OR_DIAG_RUNNING_NO_ACTION"; exit 23;
fi
[[ ! -e "$DST/checkNativeConcavity-r1.sbatch" ]] || {
    echo "RETRY_ALREADY_PREPARED_NO_OVERWRITE"; exit 24;
}

for i in {0..7};do
    target="$DST/processor$i/system"
    mkdir -p "$target"
    for f in fvSchemes fvSolution;do
        from="$SRC/processor$i/system/$f"
        if [[ ! -f "$from" ]];then
            from="$SRC/system/$f"
        fi
        [[ -f "$from" ]] || {
            echo "MISSING_ORIGINAL_SYSTEM_FILE rank=$i filename=$f - NO_JOB_SUBMITTED"; exit 25;
        }
        [[ ! -e "$target/$f" ]] || {
            echo "DEST_ALREADY_EXISTS_NO_OVERWRITE $target/$f"; exit 26;
        }
        cp -L -- "$from" "$target/$f"
        echo "PRIVATE_SYSTEM_COPIED rank=$i $f"
    done
    # Retain the private minimal controlDict; never use source controller.
    cp -L -- "$DST/system/controlDict" "$target/controlDict"
    for t in 0.5805 0.58075;do
        [[ -s "$DST/processor$i/$t/polyMesh/points" ]] || {
           echo "PRIVATE_MESH_POINTS_MISSING rank=$i time=$t - NO_JOB_SUBMITTED"; exit 27;
        }
    done
done
# Make sure root case has compatible independent dictionaries as well.
for f in fvSchemes fvSolution;do
    [[ ! -e "$DST/system/$f" ]] || {
        echo "ROOT_DEST_ALREADY_EXISTS_NO_OVERWRITE $f"; exit 28;
    }
    cp -L -- "$DST/processor0/system/$f" "$DST/system/$f"
done
BATCH="$DST/checkNativeConcavity-r1.sbatch"
cat > "$BATCH" <<EOF
#!/bin/bash
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=8
#SBATCH --cpus-per-task=1
#SBATCH --mem=16G
#SBATCH --time=00:30:00
#SBATCH --job-name=ale96764diag
#SBATCH --output=$DST/slurm-r1-%j.out
#SBATCH --error=$DST/slurm-r1-%j.err
set -Eeuo pipefail
module load gnu14/14.2.0 openmpi5/5.0.7
export SINGULARITYENV_USER="\$USER"
for t in 0.5805 0.58075;do
    echo "NATIVE_DIAG_RETRY_START time=\$t"
    set +e
    singularity exec --cleanenv -B /data/icto:/data/icto "$IMG" /bin/bash "$DST/native-check.sh" "$DST" "\$t" >"$DST/checkMesh-r1-\$t.log" 2>&1
    code=\$?
    set -e
    echo "NATIVE_DIAG_RETRY_RESULT time=\$t exit=\$code"
    grep -aEi 'Concave cells|concaveCells|concav|Mesh OK|Failed|error|non.?orth|skew|Checking geometry|time=' "$DST/checkMesh-r1-\$t.log" | tail -35 || true
done
echo "NATIVE_DIAG_RETRY_COMPLETED_EXAMINE_LOGS_NOT_FSI_PASS"
EOF
bash -n "$BATCH"
jid="$(sbatch --parsable "$BATCH")"
jid="${jid%%;*}"
[[ "$jid" =~ ^[0-9]+$ ]] || { echo "BAD_SBATCH_JOB_ID $jid"; exit 29; }
printf '%s\n' "$jid" > "$DST/diagnostic-retry-job-id.txt"
echo "NATIVE_DIAG_RETRY_SUBMITTED $jid"
echo "OUTPUT $DST/slurm-r1-$jid.out"
echo "PRIVATE_DIAGNOSTIC_ONLY_SOURCE_AND_BACKUPS_UNMODIFIED"
