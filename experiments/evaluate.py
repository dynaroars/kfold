#!/usr/bin/env python3
"""Compare kfold's predictions with the physical build inventories.

Usage: experiments/evaluate.py [SUBJECT ...] [--variants full,no_includes,...]

Each (subject, variant) runs kfold in a fresh process on the analyzed tree
(work/src/, or work/prepared/ for subjects with a prepare step), with the settings in experiments/settings/<subject>.ini, and
evaluates every configuration of that subject against
evidence/inventories/<subject>/<config>.txt. Writes
results/agreement/<subject>.<variant>.json.

Variants (ablations switch off one modeling feature through kfold's
KFOLD_* environment switches):
  full               everything on
  no_includes        include directives are not spliced
  no_rules           no rule-prerequisite closure
  no_link_semantics  no need-builtin routes or built-in container suppression
For every variant two views are reported: "members" (all extracted objects)
and "targets" (target-list words only, i.e. without composite members).

The comparison uses the whole inventory: nothing is excluded by directory.
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from subjects import EVIDENCE, RESULTS, ROOT, SUBJECTS, WORK, analysis_dir, build_dir, settings_file  # noqa: E402

VARIANTS = {
    "full": {},
    "no_includes": {"KFOLD_NO_INCLUDES": "1"},
    "no_rules": {"KFOLD_NO_RULES": "1"},
    "no_link_semantics": {"KFOLD_NO_LINK_SEMANTICS": "1"},
}


def worker(subject, variant, out):
    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(0, str(ROOT / "tools"))
    from alg import Run
    from census import GLOBAL_METRICS
    from kfold_targets import compare, object_conditions, predicted_objects

    spec = SUBJECTS[subject]
    tree = analysis_dir(subject)
    GLOBAL_METRICS.reset()
    t0 = time.monotonic()
    runner = Run(tree, use_tristate=spec["tristate"])
    tmpdir = runner.go()
    conds, kinds = object_conditions(runner)
    analysis_s = time.monotonic() - t0
    metrics = GLOBAL_METRICS.summary()
    tops = {p for p, k in kinds.items() if k == "target"}
    kind_counts = {}
    for k in kinds.values():
        kind_counts[k] = kind_counts.get(k, 0) + 1
    entry = {
        "subject": subject, "variant": variant, "version": spec["version"],
        "analysis_seconds": round(analysis_s, 2),
        "peak_rss_mb": round(metrics["peak_rss_kib"] / 1024, 1),
        "z3_checks": metrics["z3"]["checks"],
        "makefile_instances": len(runner.all_kbuilds),
        "objects": len(conds), "kinds": kind_counts,
        "census": metrics["construct_census"],
        "parse_errors": sorted({str(kb.makefile.relative_to(tree.resolve()))
                                for kb in runner.all_kbuilds
                                if getattr(kb, "parse_error", None)}),
        "profiles": {},
    }
    for config in spec["configs"]:
        inv = EVIDENCE / "inventories" / subject / f"{config}.txt"
        if spec["configs"][config].get("build", True) is False or not inv.exists():
            continue
        physical = set(inv.read_text().split())
        failed = set(inv.with_suffix(".failed.txt").read_text().split())
        predicted = predicted_objects(runner, conds, EVIDENCE / "configs" / subject / f"{config}.config")
        views = {"members": compare(predicted, physical, set(conds)),
                 "targets": compare(predicted & tops, physical, tops)}
        pending = still_buildable(subject, config, set(views["members"]["fp_paths"]) - failed)
        for view in views.values():
            # Predicted objects that make failed to compile, or would still
            # build (a prerequisite failed earlier), are toolchain outcomes of
            # an incomplete build, not selection errors; report them apart.
            view["fp_build_failed_paths"] = sorted(set(view["fp_paths"]) & (failed | pending))
            view["fp_build_failed"] = len(view["fp_build_failed_paths"])
        entry["profiles"][config] = views
    pathlib.Path(out).write_text(json.dumps(entry, indent=1, sort_keys=True) + "\n")
    import shutil
    shutil.rmtree(str(tmpdir), ignore_errors=True)


def still_buildable(subject, config, paths):
    """Paths that ``make -n`` in the finished build tree would still build.

    Only consulted for false positives of an incomplete build (a nonzero
    build status), so the dry runs are few."""
    builds = json.loads((RESULTS / "builds.json").read_text())
    rec = builds.get(f"{subject}:{config}")
    if not rec or rec["rc_build"] == 0 or not paths:
        return set()
    base = " ".join(w for w in rec["commands"][-1].split() if w != "-k" and not w.startswith("-j"))
    tree = build_dir(subject, config)
    out = set()
    for p in sorted(paths):
        r = subprocess.run(f"{base} -n {p}", shell=True, cwd=tree, capture_output=True, text=True)
        if r.returncode == 0 and p in r.stdout:
            out.add(p)
    return out


def run(subject, variant):
    out = RESULTS / "agreement" / f"{subject}.{variant}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = WORK / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, KFOLD_SETTINGS_FILE=str(settings_file(subject)),
               SKBUILD_TMP=str(tmp), **VARIANTS[variant])
    subprocess.run([sys.executable, __file__, "--worker", subject, variant, str(out)],
                   env=env, check=True)
    d = json.loads(out.read_text())
    for config, v in d["profiles"].items():
        m = v["members"]
        print(f"{subject} {variant} {config}: pred={m['predicted']} tp={m['tp']} fp={m['fp']} "
              f"fn_u={m['fn_within_universe']} out={m['outside_universe']} "
              f"prec={m['precision_pct']} overlap={m['overlap_pct']}", flush=True)
    print(f"{subject} {variant}: {d['analysis_seconds']}s {d['peak_rss_mb']}MB "
          f"{d['makefile_instances']} instances {d['objects']} objects", flush=True)


def main():
    if sys.argv[1:2] == ["--worker"]:
        worker(*sys.argv[2:5])
        return
    ap = argparse.ArgumentParser()
    ap.add_argument("subjects", nargs="*")
    ap.add_argument("--variants", default="full")
    args = ap.parse_args()
    for s in args.subjects or SUBJECTS:
        for v in args.variants.split(","):
            run(s, v)


if __name__ == "__main__":
    main()
