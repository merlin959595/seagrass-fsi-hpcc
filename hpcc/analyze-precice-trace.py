#!/usr/bin/env python3
"""Read-only per-rank preCICE 3.3+ profiling TXT analyzer; standard library only.

Usage:
python3 analyze-precice-trace.py /path/to/production/runs/hpcc-implicit-002
Never modifies original case files or launches simulation jobs.
"""
import collections
import json
import lzma
import statistics
import sys
from pathlib import Path


def parse(path):
    names = {}
    stack = []  # each item: [event_id, start_us, nested_child_us]
    totals = collections.defaultdict(lambda: [0, 0, 0])
    with path.open("rb") as stream:
        meta = json.loads(stream.readline())
        assert meta["file_version"] == 2, f"Unsupported preCICE format: {path}"
        lines = lzma.LZMAFile(stream) if meta["compression"] else stream
        for line_number, raw in enumerate(lines, 2):
            line = raw.decode().strip()
            if not line:
                continue
            kind = line[0]
            if kind == "N":
                n, label = line[1:].split(":", 1)
                names[int(n)] = label
            elif kind == "B":
                event_id, ts = map(int, line[1:].split(":", 1))
                assert event_id in names, (path, line_number, line)
                stack.append([event_id, ts, 0])
            elif kind == "E":
                event_id, ts = map(int, line[1:].split(":", 1))
                assert stack and stack[-1][0] == event_id, (path, line_number, line)
                _, started, children = stack.pop()
                duration = ts - started
                exclusive = duration - children
                assert duration >= 0 and exclusive >= 0, (path, line_number, line)
                label = "/".join(
                    [names[e[0]] for e in stack if names[e[0]] != "_GLOBAL"] + [names[event_id]]
                )
                count, inclusive, excl = totals[label]
                totals[label] = [count + 1, inclusive + duration, excl + exclusive]
                if stack:
                    stack[-1][2] += duration
            elif kind == "D":
                continue
            else:
                raise ValueError(f"Invalid record {path}:{line_number}: {line[:100]}")
    if stack:
        print(f"WARNING: incomplete trace {path}: {len(stack)} unclosed events", file=sys.stderr)
    return meta, totals


def main():
    if len(sys.argv) != 2:
        sys.exit("Usage: python3 analyze-precice-trace.py RUN_DIRECTORY")
    run = Path(sys.argv[1]).expanduser().resolve(strict=True)
    paths = sorted(run.glob("*/precice-profiling/*.txt"))
    if not paths:
        sys.exit(f"No preCICE profiling TXT rank files in {run}")
    traces = {}
    print(f"Found {len(paths)} rank files. READ-ONLY.")
    for p in paths:
        meta, counters = parse(p)
        k = (str(meta["name"]), int(meta["rank"]))
        if k in traces:
            raise ValueError(f"Duplicate participant/rank {k}")
        traces[k] = counters
        global_us = counters.get("_GLOBAL", [0, 0, 0])[1]
        print(f"{k[0]} rank {k[1]}/{meta['size']}: global={global_us/1e6:.1f}s, "
              f"event_types={len(counters)}, mode={meta['mode']}")
    for participant in sorted({k[0] for k in traces}):
        ranks = sorted(r for p, r in traces if p == participant)
        rank0 = traces[(participant, ranks[0])]
        print(f"\n=== {participant} rank {ranks[0]}: top 25 exclusive event times ===")
        for name, (count, inclusive, exclusive) in sorted(
            rank0.items(), key=lambda row: row[1][2], reverse=True
        )[:25]:
            print(f"  exclusive={exclusive/1e6:9.1f}s  inclusive={inclusive/1e6:9.1f}s"
                  f"  calls={count:6}  {name}")
        print(f"\n=== {participant}: key events across {len(ranks)} ranks (inclusive min/median/max seconds) ===")
        keys = set().union(*(traces[(participant, r)].keys() for r in ranks))
        chosen = [name for name in keys if any(x in name.lower() for x in (
            "map", "accelerat", "solver", "communicat", "m2n", "advance", "wait", "initialize"
        ))]
        rows = []
        for name in chosen:
            values = [traces[(participant, r)].get(name, [0, 0, 0])[1]/1e6 for r in ranks]
            rows.append((max(values), statistics.median(values), min(values), name))
        for maximum, median, minimum, name in sorted(rows, reverse=True)[:25]:
            print(f"  {minimum:9.1f} / {median:9.1f} / {maximum:9.1f}  {name}")
    print("\nInterpretation: ranks run concurrently; don't sum times across ranks.")
    print("Nested inclusive events overlap. Exclusive time subtracts nested event durations.")
    print("Solver events may contain blocking, so compare Fluid and Solid, not only one rank.")


if __name__ == "__main__":
    main()
