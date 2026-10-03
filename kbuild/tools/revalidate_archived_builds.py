#!/usr/bin/env python3
"""Read-only comparison of kfold conditions with archived compiler objects.

The earlier validation script regenerates configurations, touches source files,
and replaces object archives. This script leaves both inputs in place and
reports whether each physical object was even in kfold's target universe.
"""

import collections
import hashlib
import json
import os
import pathlib
import sys

import z3
from z3.z3util import get_vars

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from alg import Run
import helpers.zsolver as zsolver


SUBJECTS = (
    ("Barebox", "results/workspaces/barebox/source/barebox-2024.01.0", "evidence/physical_builds/Barebox_Sandbox"),
    ("Das U-Boot", "results/workspaces/uboot/source/u-boot-2024.01", "evidence/physical_builds/Das_U-Boot_Sandbox"),
    ("BusyBox", "results/workspaces/busybox/source/busybox-1.36.1", "evidence/physical_builds/BusyBox"),
    ("coreboot", "results/workspaces/coreboot/source/coreboot-4.22.01/source/coreboot-4.22.01", "evidence/physical_builds/coreboot_QEMU_i440fx"),
)


def physical_objects(archive):
    return {str(path.relative_to(archive)) for path in archive.rglob("*.o") if not path.name.endswith(".mod.o")}


def config_values(config):
    return dict(line.split("=", 1) for line in config.read_text(errors="replace").splitlines()
                if line.startswith("CONFIG_") and "=" in line)


def target_path(word, var_name, parent, source):
    if word.endswith((".c", ".C", ".S", ".s")):
        word = str(pathlib.Path(word).with_suffix(".o"))
    elif not word.endswith((".o", ".a")):
        return None
    try:
        rel = (parent / word).relative_to(source)
    except ValueError:
        rel = pathlib.Path(word)
    stage = var_name.split("-", 1)[0]
    if stage in {"bootblock", "romstage", "ramstage", "postcar", "verstage", "smm", "decompressor"}:
        parts = rel.parts[1:] if rel.parts and rel.parts[0] == "src" else rel.parts
        rel = pathlib.Path("build") / stage / pathlib.Path(*parts)
    return str(rel)


def summarize(name, source, archive):
    config = source / ".config"
    runner = Run(source)
    runner.go()
    targets = {}
    duplicates = collections.Counter()
    for kb in runner.all_kbuilds:
        for var in kb.state.target_files:
            if var.name in runner.mysettings.target_vars:
                continue
            for word, condition in var.valconds.items():
                if not isinstance(word, str):
                    continue
                rel = target_path(word, var.name, kb.makefile.parent, runner.maindir)
                if rel is not None:
                    duplicates[rel] += rel in targets
                    targets[rel] = zsolver.disj(targets[rel], condition) if rel in targets else condition

    solver = zsolver.ZSolver(runner.mysettings)
    configured = config_values(config)
    assignments = {}
    target_variables = {}
    for target, condition in targets.items():
        if not isinstance(condition, z3.ExprRef):
            continue
        variables = get_vars(condition)
        target_variables[target] = variables
        for variable in variables:
            symbol = str(variable)
            if symbol.startswith("CONFIG_") and variable not in assignments:
                zvar, values = solver.get_sort(symbol)
                configured_value = configured.get(symbol, "")
                assignments[zvar] = values.get(configured_value, values[""])
    predicted = set()
    for target, condition in targets.items():
        if condition is True or condition is zsolver.T:
            predicted.add(target)
        elif isinstance(condition, z3.ExprRef):
            substitutions = [(variable, assignments[variable]) for variable in target_variables[target]
                             if variable in assignments]
            result = zsolver.simplify(z3.substitute(condition, substitutions))
            if z3.is_true(result) or str(result) == "y":
                predicted.add(target)

    physical = physical_objects(archive)
    within = physical & set(targets)
    missing_within = within - predicted
    outside = physical - set(targets)
    false_positive = predicted - physical
    by_directory = collections.Counter(path.split("/", 1)[0] for path in outside)
    return {
        "subject": name,
        "source": str(source.relative_to(ROOT)),
        "archive": str(archive.relative_to(ROOT)),
        "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
        "analyzed_makefile_instances": len(runner.all_kbuilds),
        "target_universe": len(targets),
        "duplicate_target_paths": sum(duplicates.values()),
        "predicted": len(predicted),
        "physical": len(physical),
        "true_positive": len(predicted & physical),
        "false_positive": len(false_positive),
        "missing_within_universe": len(missing_within),
        "physical_outside_universe": len(outside),
        "outside_by_top_directory": dict(by_directory.most_common()),
        "false_positive_paths": sorted(false_positive),
        "missing_within_universe_paths": sorted(missing_within),
        "physical_outside_universe_paths": sorted(outside),
    }


def main():
    data = []
    for name, source_name, archive_name in SUBJECTS:
        source, archive = ROOT / source_name, ROOT / archive_name
        if not source.is_dir() or not archive.is_dir():
            print("missing input", name, file=sys.stderr)
            continue
        print("analyzing", name, flush=True)
        data.append(summarize(name, source, archive))
        print(name, {key: data[-1][key] for key in (
            "predicted", "physical", "true_positive", "missing_within_universe", "physical_outside_universe")}, flush=True)
    output = ROOT / "results" / "archived_build_revalidation_20260924.json"
    output.write_text(json.dumps(data, indent=2))
    print("saved", output)


if __name__ == "__main__":
    main()
