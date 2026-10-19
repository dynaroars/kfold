#!/usr/bin/env python3
"""Time kfold's whole-tree analysis on an idle machine.

Usage: experiments/timing.py [SUBJECT ...] [--repeat N] [--max-load L]

Each run is a fresh ``python3 -O`` process that analyzes the prepared tree
and extracts every object condition (the same work as experiments/evaluate.py
before configurations are evaluated). The script waits until the 1-minute
load average is below --max-load before each run and records it. Writes
results/timing.json with every run and the median per subject.
"""
import argparse
import json
import os
import pathlib
import statistics
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from subjects import RESULTS, ROOT, SUBJECTS, WORK, analysis_dir  # noqa: E402

CHILD = """
import json, sys, time
sys.path[:0] = [{src!r}, {tools!r}]
from alg import Run
from census import GLOBAL_METRICS
from kfold_targets import object_conditions
t0 = time.monotonic()
r = Run(__import__("pathlib").Path({tree!r}), use_tristate={tristate})
r.go()
conds, kinds = object_conditions(r)
m = GLOBAL_METRICS.summary()
print(json.dumps({{"seconds": time.monotonic() - t0, "peak_rss_mb": m["peak_rss_kib"] / 1024,
                  "z3_checks": m["z3"]["checks"], "makefile_instances": len(r.all_kbuilds),
                  "objects": len(conds)}}))
"""


def wait_idle(max_load):
    while os.getloadavg()[0] > max_load:
        time.sleep(30)
    return os.getloadavg()[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("subjects", nargs="*")
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--max-load", type=float, default=1.0)
    args = ap.parse_args()
    path = RESULTS / "timing.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    tmp = WORK / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    for s in args.subjects or SUBJECTS:
        code = CHILD.format(src=str(ROOT / "src"), tools=str(ROOT / "tools"),
                            tree=str(analysis_dir(s)), tristate=SUBJECTS[s]["tristate"])
        runs = []
        for _ in range(args.repeat):
            load = wait_idle(args.max_load)
            out = subprocess.run([sys.executable, "-O", "-c", code], capture_output=True, text=True,
                                 env=dict(os.environ, SKBUILD_TMP=str(tmp)), check=True).stdout
            run = json.loads(out.strip().splitlines()[-1])
            run["load_before"] = round(load, 2)
            runs.append(run)
            print(s, {k: round(v, 2) if isinstance(v, float) else v for k, v in run.items()}, flush=True)
        data[s] = {"runs": runs,
                   "median_seconds": round(statistics.median(r["seconds"] for r in runs), 2),
                   "max_peak_rss_mb": round(max(r["peak_rss_mb"] for r in runs), 1),
                   "cpu": open("/proc/cpuinfo").read().split("model name")[1].split(":")[1].split("\n")[0].strip(),
                   "python": sys.version.split()[0]}
        path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
