#!/usr/bin/env python3
"""Compare kfold's evaluated object conditions with archived build inventories.

For each subject and configuration this reports two variants:

  targets   words of target-family variables only (the previous protocol)
  members   targets plus the members of composite objects

Writes results/physical_validation.json. Inputs are read-only.
"""
import argparse
import json
import pathlib
import shutil
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from alg import Run  # noqa: E402
from census import GLOBAL_METRICS  # noqa: E402
from kfold_targets import (compare, object_conditions, physical_objects,  # noqa: E402
                           predicted_objects)

LINUX = "results/workspaces/linux"
SUBJECTS = [
    ("BusyBox", "results/workspaces/busybox/source/busybox-1.36.1", False,
     [("defconfig", None, "evidence/physical_builds/BusyBox")]),
    ("coreboot", "results/workspaces/coreboot/source/coreboot-4.22.01/source/coreboot-4.22.01", False,
     [("qemu-i440fx", None, "evidence/physical_builds/coreboot_QEMU_i440fx")]),
    ("Barebox", "results/workspaces/barebox/source/barebox-2024.01.0", False,
     [("sandbox_defconfig", None, "evidence/physical_builds/Barebox_Sandbox")]),
    ("Das U-Boot", "results/workspaces/uboot/source/u-boot-2024.01", False,
     [("sandbox_defconfig", None, "evidence/physical_builds/Das_U-Boot_Sandbox"),
      # Fresh rebuild: compilation completed, final packaging failed.
      ("sandbox_defconfig_fresh", None, "results/revalidation_builds/uboot")]),
    ("Linux", LINUX, True, [
        ("tinyconfig", "results/revalidation_builds/linux_configs/tinyconfig_i386/.config",
         "evidence/physical_builds/tinyconfig"),
        ("defconfig", "results/revalidation_builds/linux_configs/defconfig/.config",
         "evidence/physical_builds/defconfig"),
        ("debian", LINUX + "/.config", "evidence/physical_builds/debian"),
        ("allmodconfig", "results/revalidation_builds/linux_configs/allmodconfig/.config",
         "evidence/physical_builds/allmodconfig"),
    ]),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--subjects", help="comma-separated subset")
    ap.add_argument("--out", default=str(ROOT / "results" / "physical_validation.json"))
    args = ap.parse_args()
    wanted = set(args.subjects.split(",")) if args.subjects else None

    out = []
    for name, src, tristate, profiles in SUBJECTS:
        if wanted and name not in wanted:
            continue
        source = ROOT / src
        GLOBAL_METRICS.reset()
        t0 = time.monotonic()
        runner = Run(source, use_tristate=tristate) if tristate else Run(source)
        tmpdir = runner.go()
        analysis_s = time.monotonic() - t0
        metrics = GLOBAL_METRICS.summary()
        conds, kinds = object_conditions(runner)
        tops = {p for p, k in kinds.items() if k == "target"}
        entry = {"subject": name, "source": src, "tristate": tristate,
                 "analysis_time_s": round(analysis_s, 2),
                 "makefile_instances": len(runner.all_kbuilds),
                 "peak_rss_mb": round(metrics["peak_rss_kib"] / 1024, 1),
                 "z3_checks": metrics["z3"]["checks"],
                 "census": metrics["construct_census"],
                 "universe_targets": len(tops), "universe_with_members": len(conds),
                 "profiles": {}}
        for pname, config, archive in profiles:
            config = ROOT / (config or (src + "/.config"))
            physical = physical_objects(ROOT / archive)
            predicted = predicted_objects(runner, conds, config)
            # An archive may hold only some top-level directories (the Linux
            # archives omit tools/ and scripts/); predictions elsewhere are
            # reported separately rather than counted as false positives.
            scope = {p.name for p in (ROOT / archive).iterdir()}
            in_scope = lambda paths: {x for x in paths if x.split("/")[0] in scope}
            universe = in_scope(conds)
            entry["profiles"][pname] = {
                "config": str(config.relative_to(ROOT)), "archive": archive,
                "outside_archive_scope": sorted(predicted - in_scope(predicted)),
                "targets": compare(in_scope(predicted & tops), physical, in_scope(tops)),
                "members": compare(in_scope(predicted), physical, universe),
            }
            for variant in ("targets", "members"):
                r = entry["profiles"][pname][variant]
                print(name, pname, variant, {k: r[k] for k in (
                    "universe", "predicted", "tp", "fp", "fn_within_universe",
                    "outside_universe", "precision_pct", "overlap_pct")}, flush=True)
        include_stats = {"spliced": 0, "unresolved": 0, "missing": 0}
        for kb in runner.all_kbuilds:
            for k, v in getattr(kb, "include_stats", {}).items():
                include_stats[k] += v
        entry["include_stats"] = include_stats
        entry["parse_errors"] = sorted({str(kb.makefile.relative_to(source.resolve()))
                                        for kb in runner.all_kbuilds
                                        if getattr(kb, "parse_error", None)})
        out.append(entry)
        shutil.rmtree(str(tmpdir), ignore_errors=True)
    pathlib.Path(args.out).write_text(json.dumps(out, indent=1))
    print("wrote", args.out)


if __name__ == "__main__":
    main()
