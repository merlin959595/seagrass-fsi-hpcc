#!/usr/bin/env python3
"""G1 preflight evidence extractor, READ ONLY. No jobs, file writes, solver calls.

Uses the completed G0 JSON and the actual deployed FSI controller/configuration.
It prints bounded evidence for implementing and later validating a true
three-participant persistent restart; it never labels restart as verified.

Usage: python3 g1-readiness-readonly.py --audit ~/hpcc-fsi/g0-audit-*.json
"""
import argparse
import json
from pathlib import Path
import re

BASE_REL = "performance-full160-job-89038/optimized-160/runs/hpcc-implicit-002"
SOURCE_REL = "seagrass-implicit-20261111/fsi-implicit-production/run_production.py"
KEYWORDS = re.compile(
    r"restart|checkpoint|rout|rin\b|kinematic|reference|write(?:Interval|Control)|"
    r"startFrom|startTime|latestTime|processor|pre[Cc][Ii][Cc][Ee]|"
    r"(?<!\w)Popen\b|(?<!\w)solve\b|(?<!\w)prepare\b|"
    r"(?<!\w)CCX\b|rollback|restore|timeStep|startFromDeformed",
    flags=re.I,
)
SENSITIVE = re.compile(r"(password|secret|token|private[_-]?key)\s*[:=]\s*\S+", re.I)


def plain(text):
    return SENSITIVE.sub(r"\1=<redacted>", str(text))


def evidence_lines(path, max_lines=95):
    if not path.is_file():
        return {"path": str(path), "missing": True}
    all_lines = path.read_text(errors="replace").splitlines()
    matches = [(i, plain(line[:190])) for i, line in enumerate(all_lines, 1)
               if KEYWORDS.search(line)]
    return {"path": str(path), "total_lines": len(all_lines),
            "matches": len(matches), "selected": matches[:max_lines],
            "truncated_matches": max(len(matches)-max_lines,0)}


def key_config_lines(path):
    if not path.is_file():
        return {"path": str(path), "missing": True}
    text = path.read_text(errors="replace")
    results = []
    for i,line in enumerate(text.splitlines(),1):
        if re.search(r"restart|checkpoint|time-window|time-windows-reused|"
                     r"max-time|convergence-measure|coupling-scheme|"
                     r"participant|initialize|exchange|read|write|"
                     r"motion|displacement|pressure|reload|interface",
                     line, re.I):
            results.append([i, plain(line.strip()[:190])])
    return {"path":str(path),"matching_lines":len(results),"selected":results[:65],
            "truncated_matches": max(len(results)-65,0)}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--audit", type=Path, required=True)
    p.add_argument("--self-test", action="store_true")
    args=p.parse_args()
    if args.self_test:
        assert KEYWORDS.search("restartFromDeformed true;")
        assert KEYWORDS.search("*RESTART,WRITE")
        assert not KEYWORDS.search("no relevant content")
        print("G1_READINESS_STATIC_SELF_TEST_PASS")
        return
    a=json.loads(args.audit.expanduser().read_text())
    if a.get("schema")!="seagrass-fsi-g0-audit-v1" or a.get("mode")!="READ_ONLY_NO_SLURM_NO_SOLVER":
        raise SystemExit("STOP: G0 JSON schema/mode mismatch")
    base=Path(a["base"])
    if a.get("audit_errors"):
        print("WARNING: G0 errors present:",a["audit_errors"])
    assert a.get("cases") and a.get("controller")
    print("G1_RESTART_READINESS_EVIDENCE_ONLY")
    print("audit:",args.audit)
    print("base:",base)
    for key in ("87186","89038","89270"):
        c=a["cases"][key]
        state=c["state"]
        w=c["windows"]
        cp=c["checkpoint_evidence"]
        print(f"\n=== CASE {key} ===")
        print("status:",state.get("status"),
              "accepted:",w.get("count"),"iterations:",w.get("total_iterations"),
              "restart_verified:",state.get("persistent_checkpoint",{}).get("status","NO"),
              "last_time_processors:",cp.get("latest_processor_times_s"))
        print("solid_rout_present:",cp.get("solid_rout_present"),
              "kinematic_present:",cp.get("solid_kinematic_state_present"),
              "interface_reference:",cp.get("restart_reference_present"))
        print("restart_deck_indicators:",c.get("restart_deck_indicators"))
    run=base/BASE_REL
    source=base/SOURCE_REL
    print("\n=== ORIGINAL DEPLOYED CONTROLLER (READ ONLY) ===")
    d=evidence_lines(source)
    print("path:",d["path"],"lines:",d.get("total_lines"),
          "matches:",d.get("matches"),"omitted:",d.get("truncated_matches"))
    for i,line in d.get("selected",[]):
        print(f"{i:04d}: {line}")
    print("\n=== PRECISE CONFIGURATION EVIDENCE ===")
    for relative in ("precice-config.xml","fluid/system/controlDict",
                     "fluid/system/preciceDict","solid/config.yml",
                     "solid/seagrass.inp"):
        d=key_config_lines(run/relative)
        print("\nFILE",relative, "matches:",d.get("matching_lines"),
              "omitted:",d.get("truncated_matches"),"missing:",d.get("missing",False))
        for i,line in d.get("selected",[]):
            print(f"{i:04d}: {line}")
    print("\n=== BLOCKING G1 VERIFICATION ===")
    for msg in a.get("g1_blockers",[]):
        print("BLOCKED:",msg)
    print("G1_PERSISTENT_RESTART=UNVERIFIED")
    print("NO_SLURM_NO_SOLVER_NO_INPUT_CHANGES")


if __name__=="__main__":
    main()
