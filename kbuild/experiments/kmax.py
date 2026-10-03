#!/usr/bin/env python3
"""Run the Kmax baseline (kmaxall 4.10, as shipped) and score it like kfold.

Usage: experiments/kmax.py [linux|busybox ...]

kmaxall runs on the same analyzed tree as kfold, through
tools/run_kmaxall.py (which only fixes a Python 3 crash in kmaxall's error
reporting). Its conditions are evaluated under the same .config files and
compared with the same inventories as experiments/evaluate.py, in two views:
"local" (each object's own Makefile condition) and "with_dirs" (conjoined
with the conditions of its ancestor directory entries), and records the
kfold kind of each object Kmax misses. Writes
results/kmax/<subject>.json; the raw pickle stays in work/kmax/.
"""
import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from subjects import EVIDENCE, RESULTS, ROOT, SUBJECTS, WORK, analysis_dir, settings_file  # noqa: E402

sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
from kfold_targets import compare, config_values  # noqa: E402
from evaluate_kmax_physical import evaluate, load_conditions  # noqa: E402


def kmax_args(subject):
    if subject == "linux":
        return ["-T", "-DSRCARCH=x86", "Kbuild", "lib"]
    # Other subjects: the top-level directories of their kfold settings.
    for line in settings_file(subject).read_text().splitlines():
        if line.startswith("top_dirs"):
            return [d.split("?")[0].rstrip("/") + "/" for d in line.split("=", 1)[1].split()]
    raise ValueError(subject)


def run(subject):
    tree = analysis_dir(subject)
    pickle_path = WORK / "kmax" / f"{subject}.pickle"
    meta_path = RESULTS / "kmax" / f"{subject}.meta.json"
    pickle_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    if not pickle_path.exists():
        subprocess.run([sys.executable, str(ROOT / "tools" / "run_kmaxall.py"),
                        str(pickle_path), str(meta_path), *kmax_args(subject)],
                       cwd=tree, check=False)
    local, with_dirs, unexpanded = load_conditions(pickle_path)
    out = {"subject": subject, "version": SUBJECTS[subject]["version"],
           "run": json.loads(meta_path.read_text()) if meta_path.exists() else None,
           "objects": len(local), "unexpanded_paths": sorted(unexpanded), "profiles": {}}
    for config, cfg in SUBJECTS[subject]["configs"].items():
        inv = EVIDENCE / "inventories" / subject / f"{config}.txt"
        if cfg.get("build", True) is False or not inv.exists():
            continue
        physical = set(inv.read_text().split())
        configured = config_values(EVIDENCE / "configs" / subject / f"{config}.config")
        out["profiles"][config] = {
            view: compare(evaluate(conds, configured), physical, set(conds))
            for view, conds in (("local", local), ("with_dirs", with_dirs))}
        m = out["profiles"][config]["with_dirs"]
        print(f"kmax {subject} {config}: pred={m['predicted']} tp={m['tp']} fp={m['fp']} "
              f"fn_u={m['fn_within_universe']} overlap={m['overlap_pct']}", flush=True)
    # The kind kfold gives each compiled object that Kmax extracts but does
    # not predict (most are composite members; see the paper's RQ4).
    from cli import cache
    a = cache.load(tree, WORK / "kfold-cache", check=False)
    if a is not None:
        for p in out["profiles"].values():
            for m in p.values():
                kinds = {}
                for path in m["fn_within_universe_paths"]:
                    k = a.kinds.get(path, "not extracted")
                    kinds[k] = kinds.get(k, 0) + 1
                m["fn_kfold_kinds"] = kinds
    (RESULTS / "kmax" / f"{subject}.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")


if __name__ == "__main__":
    for s in sys.argv[1:] or ["busybox", "linux"]:
        run(s)
