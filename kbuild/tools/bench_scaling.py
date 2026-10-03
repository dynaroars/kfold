#!/usr/bin/env python3
"""Controlled scaling benchmark: kfold vs Kmax on generated Kbuild Makefiles.

Each family has k independent configuration options. For every k, the script
generates one Makefile, runs both tools on it in a fresh process (both under
``python3 -O`` so that neither runs in debug mode), and records wall time,
peak RSS, exit status, and the set of object names each tool reports.

Families:
  append   obj-$(CONFIG_Ai) += ai.o                      (computed-name appends)
  ifeq     ifeq ($(CONFIG_Bi),y) obj-y += bi.o endif     (conditional appends)
  value    ifeq/else sets Vi, then obj-y += ci_$(Vi).o    (guarded value alternatives)
  indirect ifeq appends di.o to OBJS; finally obj-y += $(OBJS)

A third tool, ``kfold_fork``, is kfold as of commit a3c1683, the last version
that forks a path state per conditional (merging identical paths). The script
extracts that commit with ``git archive``; its path count is recorded as
``states``.

Usage: tools/bench_scaling.py [--timeout S] [--out results/bench_scaling.json]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import pathlib

ROOT = Path(__file__).resolve().parent.parent
KFOLD = [sys.executable, "-O", str(ROOT / "src" / "skbuild.py")]
KMAX = [sys.executable, "-O", str(Path.home() / ".local" / "bin" / "kmax")]
KS = [1, 2, 4, 8, 12, 16, 20, 24, 32, 48, 64, 128]
FORK_COMMIT = "a3c1683"
FORK_RUNNER = """
import multiprocessing, runpy, sys
multiprocessing.set_start_method("fork")  # the old code pickles local functions
src = sys.argv[1]
sys.argv = ["skbuild.py", "--nomp", "--rmtmp"] + sys.argv[2:]
sys.path.insert(0, src)
runpy.run_path(src + "/skbuild.py", run_name="__main__")
"""


def extract_fork(dest):
    tar = subprocess.run(["git", "-C", str(ROOT), "archive", FORK_COMMIT, "src"],
                         check=True, capture_output=True).stdout
    subprocess.run(["tar", "-x", "-C", str(dest)], input=tar, check=True)
    return str(pathlib.Path(dest) / "src")


def gen(family, k):
    lines = []
    if family == "append":
        lines = [f"obj-$(CONFIG_A{i}) += a{i}.o" for i in range(k)]
        expected = {f"a{i}.o" for i in range(k)}
    elif family == "ifeq":
        for i in range(k):
            lines += [f"ifeq ($(CONFIG_B{i}),y)", f"obj-y += b{i}.o", "endif"]
        expected = {f"b{i}.o" for i in range(k)}
    elif family == "value":
        for i in range(k):
            lines += [f"ifeq ($(CONFIG_C{i}),y)", f"V{i} := wide", "else",
                      f"V{i} := narrow", "endif", f"obj-y += c{i}_$(V{i}).o"]
        expected = {f"c{i}_{w}.o" for i in range(k) for w in ("wide", "narrow")}
    elif family == "indirect":
        lines = ["OBJS :="]
        for i in range(k):
            lines += [f"ifeq ($(CONFIG_D{i}),y)", f"OBJS += d{i}.o", "endif"]
        lines.append("obj-y += $(OBJS)")
        expected = {f"d{i}.o" for i in range(k)}
    else:
        raise ValueError(family)
    return "\n".join(lines) + "\n", expected


def run_measured(cmd, cwd, timeout):
    """Run via a tiny wrapper so peak RSS belongs to this child only."""
    wrapper = [sys.executable, "-c",
               "import resource,subprocess,sys;"
               "r=subprocess.run(sys.argv[1:]);"
               "sys.stderr.write('MAXRSS_KB=%d\\n'%resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss);"
               "sys.exit(r.returncode)"] + cmd
    t0 = time.monotonic()
    proc = subprocess.Popen(wrapper, cwd=cwd, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True,
                            start_new_session=True)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, 9)
        proc.communicate()
        return {"status": "timeout", "time_s": None, "maxrss_mb": None}, "", ""
    elapsed = time.monotonic() - t0
    m = re.search(r"MAXRSS_KB=(\d+)", err)
    rss = round(int(m.group(1)) / 1024, 1) if m else None
    status = "ok" if proc.returncode == 0 else f"exit{proc.returncode}"
    return {"status": status, "time_s": round(elapsed, 3), "maxrss_mb": rss}, out, err


def kfold_objects(out):
    i = out.find("{")
    if i < 0:
        return None
    try:
        data = json.loads(out[i:])
    except json.JSONDecodeError:
        return None
    return set(data.get("predictions", {}))


def kmax_objects(out):
    objs = set()
    for line in out.splitlines():
        if line.startswith("unit_pc "):
            name = line.split()[1]
            if not name.startswith("$("):
                objs.add(Path(name).name)
    return objs


def kmax_smt_objects(out):
    """Objects in the pickle that ``kmax -z`` writes (as kmaxall uses it)."""
    import pickle
    try:
        data = pickle.loads(out.encode("latin-1"))
    except Exception:
        return None
    return {Path(k).name for k in data
            if k.endswith(".o") and not Path(k).name.startswith("$(")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--out", default=str(ROOT / "results" / "bench_scaling.json"))
    ap.add_argument("--families", default="append,ifeq,value,indirect")
    ap.add_argument("--tools", default="kfold,kmax,kmax_smt,kfold_fork")
    args = ap.parse_args()

    results = {"timeout_s": args.timeout, "python": sys.version.split()[0],
               "fork_commit": FORK_COMMIT, "runs": []}
    fork_dir = tempfile.mkdtemp(prefix="kfold_fork_")
    fork_src = extract_fork(fork_dir)
    fork_cmd = [sys.executable, "-O", "-c", FORK_RUNNER, fork_src]
    tools = set(args.tools.split(","))
    for family in args.families.split(","):
        dead = set()
        for k in KS:
            text, expected = gen(family, k)
            with tempfile.TemporaryDirectory() as d:
                mk = Path(d) / "Makefile"
                mk.write_text(text)
                row = {"family": family, "k": k, "expected": len(expected)}
                for tool, cmd, cwd in (
                        ("kfold", KFOLD + [str(mk), "--json", "--rmtmp"], ROOT),
                        ("kmax", KMAX + ["-u", "-B", "Makefile"], d),
                        ("kmax_smt", KMAX + ["-T", "-z", "Makefile"], d),
                        ("kfold_fork", fork_cmd + [str(mk)], d)):
                    if tool not in tools:
                        continue
                    if tool in dead:
                        row[tool] = {"status": "skipped"}
                        continue
                    res, out, err = run_measured(cmd, cwd, args.timeout)
                    if res["status"] == "ok":
                        if tool == "kfold_fork":
                            m = re.search(r"(\d+) paths", err)
                            res["states"] = int(m.group(1)) if m else None
                        else:
                            parse = {"kfold": kfold_objects, "kmax": kmax_objects,
                                     "kmax_smt": kmax_smt_objects}[tool]
                            objs = parse(out)
                            if objs is not None:
                                res["objects"] = len(objs)
                                res["exact"] = objs == expected
                    if res["status"] == "timeout":
                        dead.add(tool)
                    row[tool] = res
                print(json.dumps(row), flush=True)
                results["runs"].append(row)
    Path(args.out).write_text(json.dumps(results, indent=2))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
