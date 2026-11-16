#!/usr/bin/env python3
"""Offline mocked submission integration test; no Slurm, FSI, mesh or container."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import tempfile

HERE=Path(__file__).resolve().parent

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def test():
    with tempfile.TemporaryDirectory(prefix="fsi-clean-chain-test-") as td:
        root=Path(td)
        home=root/"fake-home"
        base=home/"hpcc-fsi"
        src=base/"clean-production-src"
        src.mkdir(parents=True)
        for f in ("segment.py","compute.sh","submit.sh","monitor.sh"):
            shutil.copy2(HERE/f,src/f)
        (home/"seagrass-fsi-ompi507-scotch-time.sif").write_text("fake-image-only")
        case=base/"fsi-long-stage0-job91006"/"runs/hpcc-implicit-002"
        (case/"solid").mkdir(parents=True)
        (case/"solid/seagrass.inp").write_text(
            "*RESTART,READ,STEP=2\n*STEP\n*DYNAMIC,DIRECT\n0.000125, 0.03\n*END STEP\n")
        (case/"solid/seagrass.rout").write_bytes(b"r"*1600)
        (case/"solid/kinematic_state.bin").write_bytes(b"k"*1600)
        (case/"restart_reference").mkdir()
        (case/"restart_reference/Solid-Mesh.coords").write_bytes(b"x"*1600)
        for rank in range(8):
            d=case/f"fluid/processor{rank}/0.0325"
            (d/"polyMesh").mkdir(parents=True)
            (d/"uniform").mkdir()
            for f in ("U","p","phi","pointDisplacement"):
                (d/f).write_text(f"rank{rank},field={f}")
            (d/"polyMesh/points").write_text(f"rank{rank},points")
            (d/"uniform/time").write_text("0.0325")
        cert={
          "status":"FSI_91006_CONDITIONAL_RESTART_ELIGIBLE",
          "source_job":91006,"next_step":3,
          "native_terminal_checkMesh":{"status":"PASS"},
          "evidence":{
            "accepted_windows":240,"original_guard_failures":0,
            "startup_exception":True,
            "first_window_meshCo_last_record":.235,
            "remaining_239_windows_meshCo_max":.309,
            "checkpoint_hashes":{
              "solid_rout_sha256":sha(case/"solid/seagrass.rout"),
              "solid_kinematic_sha256":sha(case/"solid/kinematic_state.bin"),
              "fluid_proc0_terminal_points_sha256":
                sha(case/"fluid/processor0/0.0325/polyMesh/points"),
            }
          }
        }
        (base/"FSI_91006_RESUME_CERT.json").write_text(json.dumps(cert))
        fakebin=root/"fake-bin"
        fakebin.mkdir()
        squeue=fakebin/"squeue"
        squeue.write_text("#!/bin/sh\nexit 0\n")
        squeue.chmod(0o755)
        sbatch=fakebin/"sbatch"
        sbatch.write_text(
          "#!/usr/bin/env python3\n"
          "import json,os,sys,pathlib\n"
          "p=pathlib.Path(os.environ['FAKE_SBATCH_LOG'])\n"
          "calls=json.loads(p.read_text()) if p.is_file() else []\n"
          "calls.append(sys.argv[1:])\n"
          "p.write_text(json.dumps(calls))\n"
          "print(70000+len(calls))\n")
        sbatch.chmod(0o755)
        calls=root/"sbatch.json"
        env=os.environ.copy()
        env["HOME"]=str(home)
        env["USER"]="mockuser"
        env["PATH"]=str(fakebin)+os.pathsep+env["PATH"]
        env["FAKE_SBATCH_LOG"]=str(calls)
        # Unit test a deliberate safety stop BEFORE creating any jobs.
        blocked=subprocess.run(["bash",str(src/"submit.sh"),"--count","3"],
            env=env,capture_output=True,text=True,timeout=120)
        assert blocked.returncode==61, blocked.stdout+"\n"+blocked.stderr
        assert "CROSS_JOB_CHAIN_BLOCKED" in blocked.stderr
        assert not calls.exists()
        assert not (base/"seagrass-fsi-mainline").exists()
        # A synthetic certificate checks the GUARD'S MECHANICS only;
        # it does not constitute real FSI validation.
        mock_proof={
            "status":"FSI_CROSS_JOB_NATIVE_RESTART_PASS",
            "source_job":91006,"restart_from_time_s":0.0325,
            "verified_coupled_windows":20,
            "participant_exit_codes":{"fluid":0,"solid":0},
            "native_terminal_mesh_status":"PASS",
            "max_mesh_Co":.24,"max_fluid_Co":.26,
            "initial_force_rel_error":.01,
            "first_computed_force_rel_error":.02,
            "solid_rout_sha256":sha(case/"solid/seagrass.rout"),
            "solid_kinematic_sha256":sha(case/"solid/kinematic_state.bin"),
            "fluid_proc0_points_sha256":sha(case/"fluid/processor0/0.0325/polyMesh/points"),
        }
        (base/"FSI_CROSS_JOB_NATIVE_RESTART_PROOF.json").write_text(json.dumps(mock_proof))
        result=subprocess.run(["bash",str(src/"submit.sh"),"--count","3"],
            env=env,capture_output=True,text=True,timeout=120)
        assert result.returncode==0, result.stdout+"\n"+result.stderr
        manifest=base/"seagrass-fsi-mainline/submissions.tsv"
        assert manifest.is_file()
        lines=manifest.read_text().strip().splitlines()
        assert len(lines)==4,lines
        assert [line.split("\t")[0] for line in lines[1:]]==["A","B","C"]
        assert [line.split("\t")[1] for line in lines[1:]]==[
            "70001","70002","70003"]
        commands=json.loads(calls.read_text())
        assert len(commands)==3
        assert not any("--dependency" in a for a in commands[0])
        for idx in (1,2):
            assert "--dependency=afterok:"+str(70000+idx) in commands[idx]
            assert "--kill-on-invalid-dep=yes" in commands[idx]
        for idx,command in enumerate(commands,1):
            assert "--time=3-00:00:00" in command
            assert "--cpus-per-task=12" in command
            assert "--job-name=seagrassFSI" in command
            label="ABC"[idx-1]
            assert any("SEGMENT_LABEL="+label in a for a in command)
        assert "CLEAN_FSI_CHAIN_SUBMITTED" in result.stdout
        assert "70001" not in result.stdout  # hide internal Slurm job IDs
        assert "已排入队列：计算段 C" in result.stdout
        assert not (base/"seagrass-fsi-mainline/segment-A").exists()
        assert (case/"solid/seagrass.rout").read_bytes()==b"r"*1600
        print("FSI_CLEAN_OFFLINE_SUBMISSION_CHAIN_PASS absent-proof blocked; mock-proof 3 stages, afterok, immutable source")

if __name__=="__main__":
    test()
