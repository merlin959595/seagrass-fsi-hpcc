#!/usr/bin/env python3
"""G2 bottleneck triage + G3 frozen-160 baseline acceptance, OFFLINE and READ ONLY.

Reads validated HPC run directories and computes evidence-supported performance
ceilings and per-window quality checks. Never imports the original controller,
never launches a solver/Slurm, and never modifies original cases.

Optional --out FILE: create NEW evidence JSON plus NEW Markdown sibling, refusing
overwrites or output inside frozen cases. No external Python dependencies.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import sys

CASES = {
    "87186": ("implicit-pilot-002-8mpi-timefix-87186/production",160),
    "89038": ("performance-full160-job-89038/optimized-160",160),
    "89270": ("performance-omp12-iqn15-job-89270/optimized-20",20),
}
REUSE15_20 = "performance-iqn20-job-88550/reuse-15/PERFORMANCE_RESULT.json"
TIME_WINDOW = 0.000125
TOL = 1e-5


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as ex:
        return {"_read_error": f"{type(ex).__name__}: {ex}"}


def file_meta(path):
    try:
        s=path.stat()
        return {"present":True,"bytes":s.st_size}
    except OSError:
        return {"present":False}


def expect(ok, label, errors):
    if not ok:
        errors.append(label)
    return bool(ok)


def finite_num(x):
    return isinstance(x, (float,int)) and not isinstance(x,bool) and math.isfinite(x)


def case_report(base, job, rel, count):
    root=base/rel
    run=root/"runs/hpcc-implicit-002"
    state=read_json(root/"STATE.json")
    windows=read_json(run/"WINDOWS.json")
    gate=read_json(run/f"GATE-{count:04d}.json")
    errors=[]
    expected_status={"87186":"HPCC_0P02_IMPLICIT_PASS_RESTART_UNVERIFIED",
                     "89038":"OPTIMIZED_0P02_FSI_PASS",
                     "89270":"SHORT_FSI_PERFORMANCE_PASS"}[job]
    expect(state.get("status")==expected_status,"status",errors)
    expect(state.get("accepted_windows")==count,"accepted_windows",errors)
    expect(state.get("participant_exit_codes")=={"fluid":0,"solid":0},
           "participant_exit_codes",errors)
    expect(gate.get("status")=="LIVE_GATE_PASS","GATE status",errors)
    expect(finite_num(gate.get("gate_s")) and abs(gate["gate_s"]-count*TIME_WINDOW)<1e-10,
           "GATE physical time",errors)
    valid=isinstance(windows,list) and len(windows)==count
    expect(valid,"WINDOWS.json count/format",errors)
    iters=[]
    residual_force=[]
    residual_disp=[]
    if valid:
        for i,w in enumerate(windows,1):
            if not isinstance(w,dict):
                errors.append(f"window {i} malformed")
                continue
            if w.get("window")!=i:
                errors.append(f"window {i} index mismatch")
            t=w.get("time_s")
            if not finite_num(t) or abs(t-i*TIME_WINDOW)>1e-9:
                errors.append(f"window {i} time mismatch")
            n=w.get("iterations")
            if not isinstance(n,int) or n<1 or n>50:
                errors.append(f"window {i} iterations missing/out of 1..50")
            else:
                iters.append(n)
            a,b=w.get("force_residual"),w.get("displacement_residual")
            if not finite_num(a) or a<0 or a>TOL:
                errors.append(f"window {i} force convergence failed")
            else:
                residual_force.append(a)
            if not finite_num(b) or b<0 or b>TOL:
                errors.append(f"window {i} displacement convergence failed")
            else:
                residual_disp.append(b)
    q=gate.get("quality") or {}
    quality_limits=[
        ("max_nonorthogonality_deg",0,65),
        ("max_Co",0,.5),
        ("max_mesh_Co",0,.5),
    ]
    for key,lo,hi in quality_limits:
        val=q.get(key)
        expect(finite_num(val) and lo<=val<=hi,f"quality.{key}",errors)
    expect(finite_num(q.get("min_volume_m3")) and q["min_volume_m3"]>0,
           "quality.min_volume_m3",errors)
    expect(len(iters)==count,"all coupling iteration records present",errors)
    wall=state.get("elapsed_s")
    expect(finite_num(wall) and wall>0,"elapsed_s",errors)
    evidence={
        "job":job,
        "status":state.get("status"),
        "accepted_windows":state.get("accepted_windows"),
        "expected_windows":count,
        "time_s":count*TIME_WINDOW,
        "wall_s":wall,
        "per_window_s":wall/count if finite_num(wall) else None,
        "iterations":sum(iters),
        "iterations_per_window":statistics.mean(iters) if iters else None,
        "median_iterations":statistics.median(iters) if iters else None,
        "p90_iterations":sorted(iters)[math.ceil(.9*len(iters))-1] if iters else None,
        "wall_seconds_per_iteration":wall/sum(iters)
          if finite_num(wall) and sum(iters)>0 else None,
        "force_residual_max":max(residual_force) if residual_force else None,
        "disp_residual_max":max(residual_disp) if residual_disp else None,
        "quality":q,
        "solid_log":file_meta(run/"solid.log"),
        "spooles_out":file_meta(run/"solid/spooles.out"),
        "fluid_log":file_meta(run/"fluid.log"),
        "precice_fluid_profile":file_meta(run/"fluid/precice-profiling"),
        "precice_solid_profile":file_meta(run/"solid/precice-profiling"),
        "g3_frozen_acceptance": "PASS" if not errors else "FAIL",
        "errors":errors,
    }
    if iters:
        chunks=[]
        for j in range(0,len(iters),20):
            chunk=iters[j:j+20]
            chunks.append({"from":j+1,"to":j+len(chunk),
                           "mean_iterations":round(statistics.mean(chunk),3),
                           "max_iterations":max(chunk)})
        evidence["iterations_20_window_blocks"]=chunks
    return evidence


def capacity_scenarios(wall_per_window):
    result=[]
    for period in (.35,.5,1.0):
        n=round(2*period/TIME_WINDOW)
        permitted=72*3600/n
        result.append({
            "single_period_assumed_s":period,
            "period_is_measured":False,
            "two_periods_s":2*period,
            "windows":n,
            "max_wall_seconds_per_window_for_72h":permitted,
            "current_89038_projection_days":n*wall_per_window/86400,
            "required_relative_speedup":wall_per_window/permitted,
            "operational_target_seconds_per_window":permitted*.85,
        })
    return result


def diff_review(base, cases):
    r4=read_json(base/REUSE15_20)
    r12=read_json(base/"performance-omp12-iqn15-job-89270/OMP12_IQN15_20_COMPARISON.json")
    errors=[]
    if r4.get("status")!="SHORT_FSI_PERFORMANCE_PASS" or r4.get("windows")!=20:
        errors.append("88550 IQN15 4-OMP 20-window baseline unavailable")
    if r12.get("status")!="OPTIMIZED_20_12THREAD_IQN15_PASS":
        errors.append("89270 12-OMP comparison unavailable")
    d={"g2_4v12_20_window_comparison":"INCOMPLETE","errors":errors}
    if not errors:
        t4=r4.get("wall_s")
        t12=r12.get("new_wall_s")
        if finite_num(t4) and finite_num(t12) and t4>0 and t12>0:
            d.update({
                "g2_4v12_20_window_comparison":"MEASURED_DIFFERENT_NODES",
                "four_omp_seconds":t4,
                "twelve_omp_seconds":t12,
                "twelve_omp_wall_pct_change":100*(t12/t4-1),
                "four_omp_iterations":r4.get("coupling_iterations"),
                "twelve_omp_iterations":cases["89270"]["iterations"],
                "notes":"Different nodes and different iteration counts; no universal scaling conclusion.",
            })
    return d


def summarize(base):
    cases={k:case_report(base,k,*v) for k,v in CASES.items()}
    original=cases["87186"]; optimized=cases["89038"]
    saved_pct=None
    if finite_num(original["wall_s"]) and finite_num(optimized["wall_s"]):
        saved_pct=100*(1-optimized["wall_s"]/original["wall_s"])
    file_metrics={
        "baseline_87186_frozen":"PASS" if original["g3_frozen_acceptance"]=="PASS" else "FAIL",
        "baseline_89038_frozen":"PASS" if optimized["g3_frozen_acceptance"]=="PASS" else "FAIL",
        "short_89270_reference":"PASS" if cases["89270"]["g3_frozen_acceptance"]=="PASS" else "FAIL",
    }
    return {
        "schema":"seagrass-g2g3-offline-v1",
        "generated_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
        "mode":"OFFLINE_READ_ONLY_NO_SLURM_NO_SOLVER",
        "cases":cases,
        "g2_measured_wall_time_savings_89038_vs_87186_pct":saved_pct,
        "g2_thread_scaling":diff_review(base,cases),
        "g2_bottleneck_unresolved":True,
        "g2_profile_guidance":[
            "Total job wall time and total coupling iterations cannot isolate SPOOLES time.",
            "Use actual solid.log, spooles.out, preCICE rank traces for phase-level timing.",
            "Do not sum blocking preCICE durations across parallel ranks.",
            "G2 optimized solver candidate has not been executed or validated.",
        ],
        "g3_reference_gates":file_metrics,
        "g3_new_candidate_full160":"NOT_TESTED",
        "g3_large_deformation_gate":"NOT_TESTED",
        "g1_three_participant_persistent_restart":"UNVERIFIED",
        "g2_72hour_capacity_scenarios":capacity_scenarios(optimized["per_window_s"])
            if finite_num(optimized["per_window_s"]) else [],
        "warning":"Two periods cannot be inferred from startup motion. Input periods are hypotheses, not observed underwater oscillations.",
    }


def markdown(a):
    lines=["# G2/G3离线分析与验收", "",
           "此报告只读取已完成HPCC结果，不占用FSI计算资源。",
           "", "| 作业 | 时间窗 | 真实墙钟(s) | 耦合迭代 | 窗口平均(s) | 独立历史验收 |",
           "|---|---:|---:|---:|---:|---|"]
    for key,x in a["cases"].items():
        lines.append("| "+ " | ".join(str(y) for y in [
            key,x["accepted_windows"],x["wall_s"],x["iterations"],
            round(x["per_window_s"],3) if finite_num(x["per_window_s"]) else "N/A",
            x["g3_frozen_acceptance"]])+" |")
    lines.extend(["","## G2性能","",
                  f"- 89038对87186耗时节省：{a['g2_measured_wall_time_savings_89038_vs_87186_pct']}",
                  f"- 4与12 OMP 20窗口：{a['g2_thread_scaling'].get('g2_4v12_20_window_comparison')}",
                  "- **结构矩阵分解所占比例未由现有总时长数据独立证明**，需要实际profiler计时。",
                  "", "## 三天容量边界（周期全为条件假设）","",
                  "| 假设单周期(s) | 两周期窗口 | 允许秒/窗口 | 需要总体加速 | 目前外推天数 |",
                  "|---:|---:|---:|---:|---:|"])
    for x in a["g2_72hour_capacity_scenarios"]:
        lines.append("| "+ " | ".join([
            str(x["single_period_assumed_s"]), str(x["windows"]),
            f'{x["max_wall_seconds_per_window_for_72h"]:.2f}',
            f'{x["required_relative_speedup"]:.2f}x',
            f'{x["current_89038_projection_days"]:.2f}'])+" |")
    lines.extend(["","## G3发布门槛","",
                  f"- 89038完整160窗口历史基准：{a['g3_reference_gates']['baseline_89038_frozen']}",
                  "- 新候选160窗口：NOT_TESTED",
                  "- 大位移真实FSI：NOT_TESTED",
                  "- 三方持久化restart：UNVERIFIED",
                  "- **不能以历史基准G3通过代替新优化候选或两周期正式计算通过。**",
                  ""])
    for key in ("87186","89038","89270"):
        for e in a["cases"][key]["errors"][:15]:
            lines.append(f"- [{key}] 验收错误：{e}")
    return "\n".join(lines)+"\n"


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base",type=Path,default=Path.home()/"hpcc-fsi")
    p.add_argument("--out",type=Path,
                   help="Create NEW JSON + same-name .md summary outside any frozen run")
    p.add_argument("--self-test",action="store_true")
    a=p.parse_args()
    if a.self_test:
        assert len(CASES)==3
        assert 160*TIME_WINDOW == .02
        assert math.isclose(72*3600/5600,46.2857142857)
        assert math.isclose(120.42472432320938/(72*3600/5600),2.602,abs_tol=.01)
        print("G2_G3_OFFLINE_STATIC_SELF_TEST_PASS")
        return 0
    base=a.base.expanduser().resolve(strict=True)
    x=summarize(base)
    print("G2_G3_OFFLINE_AUDIT_COMPLETED")
    for key,record in x["cases"].items():
        print(f"JOB={key} G3_REFERENCE={record['g3_frozen_acceptance']} "
              f"WINDOWS={record['accepted_windows']} WALL_S={record['wall_s']} "
              f"ITER={record['iterations']}")
        for error in record["errors"][:8]:
            print(f"  ERROR: {error}")
    print("G2_SOLVER_OPTIMIZATION=NOT_VALIDATED")
    print("G3_NEW_CANDIDATE_160=NOT_TESTED")
    print("G1_RESTART=UNVERIFIED")
    if a.out:
        out=a.out.expanduser().resolve()
        protected=[(base/rel).resolve() for rel,n in CASES.values()]
        protected += [(base/"seagrass-implicit-20261111").resolve()]
        if any(out.is_relative_to(prot) for prot in protected):
            raise SystemExit("STOP: report path inside frozen case")
        md=out.with_suffix(".md")
        if out.exists() or md.exists():
            raise SystemExit("STOP: report path exists, no overwrite")
        out.parent.mkdir(parents=True,exist_ok=True)
        with out.open("x",encoding="utf-8") as stream:
            json.dump(x,stream,ensure_ascii=False,indent=2)
            stream.write("\n")
        with md.open("x",encoding="utf-8") as stream:
            stream.write(markdown(x))
        print("JSON_REPORT:",out)
        print("MD_REPORT:",md)
    return 0 if x["g3_reference_gates"]["baseline_89038_frozen"]=="PASS" else 2


if __name__=="__main__":
    sys.exit(main())
