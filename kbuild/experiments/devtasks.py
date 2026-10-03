#!/usr/bin/env python3
"""Developer-facing tasks on Linux: why, config-for, and blind spots.

Usage: experiments/devtasks.py why|config-for|compile|blindspots [--seed N]

All tasks use kfold's CLI on the prepared Linux tree with the analysis cache
in work/kfold-cache (``kfold analyze`` is run first if the cache is stale).

why         For every built Linux configuration, a seeded random sample of
            SAMPLE objects that the physical build produced and SAMPLE
            objects of kfold's extracted set that it did not produce. For
            each, ``kfold why --json`` gives a verdict; the verdict is
            checked against the inventory, and the first failing part of
            the condition chain is classified (directory route, target-list
            line, composite membership). -> results/devtasks/why.json

config-for  Every commit of the v7.2.7..v7.2.8 stable update that touches a
            .c or .S file (work/stable-7.2.8, see experiments/README.md), as
            a real patch, run through ``kfold config-for PATCH --base
            defconfig --verify --json`` (verify: the fragment is applied
            with ``make olddefconfig`` and every requested symbol checked).
            -> results/devtasks/config_for.json

compile     For a seeded random sample of COMPILE_SAMPLE of those commits
            whose objects are all selectable, applies the verified
            configuration to a copy of the defconfig build tree and compiles
            every touched object with ``make <object>`` (after deleting any
            copy left by the base build).
            -> results/devtasks/config_for_compile.json

blindspots  ``kfold blindspots --configs allmodconfig allyesconfig defconfig
            --json``. -> results/devtasks/blindspots.json
"""
import argparse
import contextlib
import io
import json
import pathlib
import random
import shutil
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from subjects import EVIDENCE, RESULTS, ROOT, SUBJECTS, WORK, analysis_dir, build_dir  # noqa: E402

sys.path.insert(0, str(ROOT / "src"))
from cli import cache, main as cli  # noqa: E402

TREE = analysis_dir("linux")
CACHE = WORK / "kfold-cache"
STABLE = WORK / "stable-7.2.8"
OUT = RESULTS / "devtasks"
CONFIGS = EVIDENCE / "devtasks" / "config_for"   # verified .config per commit
SAMPLE = 50
COMPILE_SAMPLE = 40


def kfold_json(*args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = cli.main([*args, "--tree", str(TREE), "--cache-dir", str(CACHE), "--json", "--no-analyze"])
    text = buf.getvalue()
    try:
        return rc, json.loads(text)
    except json.JSONDecodeError:
        return rc, {"raw": text}


def ensure_cache():
    cli.main(["analyze", str(TREE), "--cache-dir", str(CACHE)])


def classify(label):
    if label is None:
        return None
    if label.startswith("reached"):
        return "directory route"
    if label.startswith("member of"):
        return "composite membership"
    return "target-list line"


def task_why(seed):
    ensure_cache()
    a = cache.load(TREE, CACHE)
    universe = sorted(a.conds)
    rng = random.Random(seed)
    out = {"seed": seed, "sample_per_side": SAMPLE, "configs": {}}
    for config, cfg in SUBJECTS["linux"]["configs"].items():
        inv = EVIDENCE / "inventories" / "linux" / f"{config}.txt"
        if cfg.get("build", True) is False or not inv.exists():
            continue
        built = set(inv.read_text().split())
        cfgpath = EVIDENCE / "configs" / "linux" / f"{config}.config"
        on = [p for p in universe if p in built]
        off = [p for p in universe if p not in built]
        cases = [(p, True) for p in rng.sample(on, min(SAMPLE, len(on)))] + \
                [(p, False) for p in rng.sample(off, min(SAMPLE, len(off)))]
        rows = []
        for path, truth in cases:
            rc, d = kfold_json("why", path, "--config", str(cfgpath))
            c = d.get("config", {})
            rows.append({"object": path, "built": truth, "verdict": c.get("built"),
                         "correct": c.get("built") == truth,
                         "first_failing": c.get("first_failing_conjunct"),
                         "failing_kind": classify(c.get("first_failing_conjunct")),
                         "pivotal_symbols": [s["symbol"] for s in c.get("pivotal_symbols", [])],
                         "kconfig_error": c.get("kconfig_error")})
        kinds = {}
        for r in rows:
            if r["failing_kind"]:
                kinds[r["failing_kind"]] = kinds.get(r["failing_kind"], 0) + 1
        out["configs"][config] = {
            "cases": len(rows), "correct": sum(r["correct"] for r in rows),
            "failing_kinds": kinds,
            "kconfig_errors": sum(bool(r["kconfig_error"]) for r in rows),
            "rows": rows}
        print(config, out["configs"][config]["correct"], "/", len(rows), kinds, flush=True)
    write("why.json", out)


def stable_commits():
    lines = subprocess.run(["git", "-C", str(STABLE), "log", "--format=%H%x09%s", "v7.2.8"],
                           capture_output=True, text=True, check=True).stdout.splitlines()
    commits = []
    for line in lines[1:]:  # the first is the "Linux 7.2.8" version bump
        h, subject = line.split("\t", 1)
        files = subprocess.run(["git", "-C", str(STABLE), "diff-tree", "--no-commit-id", "--name-only",
                                "-r", h], capture_output=True, text=True, check=True).stdout.split()
        if any(f.endswith((".c", ".S")) for f in files):
            commits.append((h, subject, files))
    return commits


def task_config_for(seed):
    ensure_cache()
    base = EVIDENCE / "configs" / "linux" / "defconfig.config"
    patches = WORK / "stable-patches"
    patches.mkdir(exist_ok=True)
    rows = []
    for h, subject, files in stable_commits():
        patch = patches / f"{h[:12]}.patch"
        if not patch.exists():
            patch.write_text(subprocess.run(["git", "-C", str(STABLE), "format-patch", "-1", h, "--stdout"],
                                            capture_output=True, text=True, check=True).stdout)
        t0 = time.monotonic()
        rc, d = kfold_json("config-for", str(patch), "--base", str(base), "--verify")
        final = (d.get("verify") or {}).get("final_config")
        if final and pathlib.Path(final).exists():  # overwritten by the next run
            keep = CONFIGS / f"{h[:12]}.config"
            keep.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(final, keep)
            d["verify"]["final_config"] = str(keep.relative_to(ROOT))
        rows.append({"commit": h, "subject": subject, "files": files, "rc": rc,
                     "seconds": round(time.monotonic() - t0, 2), "result": d})
        print(h[:12], rc, round(time.monotonic() - t0, 1), subject[:60], flush=True)
    write("config_for.json", {"base": "defconfig", "commits": len(rows), "rows": rows})


def write(name, data):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")


def task_blindspots(seed):
    ensure_cache()
    rc, d = kfold_json("blindspots", "--configs", "allmodconfig", "allyesconfig", "defconfig")
    write("blindspots.json", {"rc": rc, "result": d})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("task", choices=["why", "config-for", "compile", "blindspots"])
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    {"why": task_why, "config-for": task_config_for, "blindspots": task_blindspots,
     "compile": task_compile}[args.task](args.seed)


def compilable(row):
    d = row["result"]
    v = d.get("verify") or {}
    return (row["rc"] == 0 and d.get("objects") and not d.get("predicted_not_built")
            and not d.get("excluded") and v.get("olddefconfig_rc") == 0 and not v.get("lost")
            and v.get("kfold_predicted_all_built"))


def task_compile(seed):
    rows = json.loads((OUT / "config_for.json").read_text())["rows"]
    eligible = [r for r in rows if compilable(r)]
    sample = random.Random(seed).sample(eligible, min(COMPILE_SAMPLE, len(eligible)))
    scratch = WORK / "build" / "linux-config-for-scratch"
    if scratch.exists():
        subprocess.run(["chmod", "-R", "u+w", str(scratch)], check=True)
        shutil.rmtree(scratch)
    subprocess.run(["cp", "-a", "--reflink=auto", str(build_dir("linux", "defconfig")), str(scratch)], check=True)
    out = []
    for r in sample:
        cfg = ROOT / r["result"]["verify"]["final_config"]
        objs = r["result"]["objects"]
        shutil.copyfile(cfg, scratch / ".config")
        for o in objs:  # objects the base build already has must be rebuilt too
            (scratch / o).unlink(missing_ok=True)
        t0 = time.time()
        rc_cfg = subprocess.run("make ARCH=x86_64 olddefconfig", shell=True, cwd=scratch,
                                capture_output=True).returncode
        mk = subprocess.run(f"make ARCH=x86_64 -j{__import__('os').cpu_count()} {' '.join(objs)}",
                            shell=True, cwd=scratch, capture_output=True, text=True)
        fresh = {o: (scratch / o).exists() and (scratch / o).stat().st_mtime >= t0 for o in objs}
        out.append({"commit": r["commit"], "subject": r["subject"], "objects": objs,
                    "fragment": r["result"]["fragment"], "rc_olddefconfig": rc_cfg,
                    "rc_make": mk.returncode, "compiled": fresh, "all_compiled": all(fresh.values()),
                    "seconds": round(time.time() - t0, 1),
                    "stderr_tail": mk.stderr[-2000:] if mk.returncode else ""})
        print(r["commit"][:12], mk.returncode, sum(fresh.values()), "/", len(objs), flush=True)
    write("config_for_compile.json", {"seed": seed, "eligible": len(eligible),
                                      "sampled": len(out), "all_compiled": sum(o["all_compiled"] for o in out),
                                      "rows": out})


if __name__ == "__main__":
    main()
