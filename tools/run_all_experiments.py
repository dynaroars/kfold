#!/usr/bin/env python3
"""Run full experimental pipeline on BusyBox, coreboot, Linux, U-Boot, and Barebox."""

import json
import os
import pathlib
import sys
import time
import z3

# Set up PYTHONPATH
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import helpers.vcommon as CM
import helpers.zsolver as zsolver
import settings
from alg import Run
from census import GLOBAL_METRICS


def evaluate_corpus(name, version, dialect, root_dir, ini_file=None):
    root_path = pathlib.Path(root_dir).resolve()
    print(f"\n=======================================================")
    print(f"Evaluating {name} ({version}) [{dialect}]")
    print(f"Path: {root_path}")
    print(f"=======================================================")

    GLOBAL_METRICS.reset()
    st = time.time()
    runner = Run(root_path)
    tmpdir = runner.go()
    wall_time = time.time() - st

    summary = GLOBAL_METRICS.summary()
    kbuilds = getattr(runner, 'all_kbuilds', getattr(runner, 'kbuilds', []))
    main_dir = getattr(runner, 'maindir', getattr(runner, 'main_dir', root_path))
    mysettings = getattr(runner, 'mysettings', None)

    # Extract target objects and conditions
    target_objects = {}
    config_vars = set()

    for kb in kbuilds:
        state = kb.state
        parent = kb.makefile.parent
        for v in state.target_files:
            if mysettings and v.name in mysettings.target_vars:
                continue
            for word, wcond in v.valconds.items():
                if isinstance(word, str) and (word.endswith('.o') or word.endswith('.a')):
                    try:
                        rel = str((parent / word).relative_to(main_dir))
                    except ValueError:
                        rel = str(word)
                    target_objects[rel] = wcond
                    
                    # collect symbols
                    if isinstance(wcond, z3.ExprRef):
                        def get_syms(e):
                            if z3.is_const(e) and e.decl().kind() == z3.Z3_OP_UNINTERPRETED:
                                return {str(e.decl().name())}
                            res = set()
                            for child in e.children():
                                res.update(get_syms(child))
                            return res
                        config_vars.update(get_syms(wcond))

    # Count source LOC
    loc = 0
    src_exts = {".c", ".h", ".S", ".s"}
    source_files_on_disk = []
    for p in root_path.rglob("*"):
        if p.is_file() and p.suffix in src_exts:
            source_files_on_disk.append(p)
            try:
                loc += sum(1 for _ in p.open(errors='ignore'))
            except Exception:
                pass

    # Dead code & Orphan analysis
    solver = z3.Solver()
    dead_targets = []
    for obj, cond in target_objects.items():
        if isinstance(cond, z3.ExprRef):
            solver.push()
            solver.add(cond)
            if solver.check() == z3.unsat:
                dead_targets.append(obj)
            solver.pop()

    # CI Matrix Greedy Set-Cover
    uncovered = set(target_objects.keys())
    witness_configs = []
    while uncovered:
        best_model = None
        best_covered = set()
        
        # Test targets for satisfying model
        for obj in list(uncovered)[:30]:
            cond = target_objects[obj]
            if not isinstance(cond, z3.ExprRef):
                continue
            solver.push()
            solver.add(cond)
            if solver.check() == z3.sat:
                model = solver.model()
                covered_by_model = set()
                for target, tcond in target_objects.items():
                    if isinstance(tcond, z3.ExprRef):
                        val = model.eval(tcond, model_completion=True)
                        if z3.is_true(val):
                            covered_by_model.add(target)
                if len(covered_by_model & uncovered) > len(best_covered & uncovered):
                    best_covered = covered_by_model
                    best_model = model
            solver.pop()
            if len(best_covered & uncovered) >= len(uncovered) or len(best_covered & uncovered) >= 100:
                break
        
        if not best_model or not (best_covered & uncovered):
            break
        witness_configs.append(best_model)
        uncovered -= best_covered

    census_totals = summary["construct_census"]["totals"]
    peak_rss_mb = summary["peak_rss_kib"] / 1024.0

    res = {
        "name": name,
        "version": version,
        "dialect": dialect,
        "loc": loc,
        "makefiles_count": len(kbuilds),
        "objects_count": len(target_objects),
        "unique_vars": len(config_vars),
        "wall_time": wall_time,
        "peak_rss_mb": peak_rss_mb,
        "set_var_count": summary["state_operations"]["set_var_calls"],
        "is_sat_count": summary["z3"]["is_sat_calls"],
        "modeled_constructs": census_totals["modeled"],
        "out_of_scope_constructs": census_totals["out_of_scope"],
        "unsupported_constructs": census_totals["unsupported"],
        "dead_objects": len(dead_targets),
        "ci_matrix_size": len(witness_configs),
        "ci_matrix_coverage_pct": 100.0 * (len(target_objects) - len(uncovered)) / max(1, len(target_objects)),
    }
    return res


def main():
    corpora = [
        ("BusyBox", "1.36.1", "Standard (obj-y, lib-y)", "results/workspaces/busybox/source/busybox-1.36.1"),
        ("coreboot", "4.22.01", "Stage-based (Makefile.inc)", "results/workspaces/coreboot/source/coreboot-4.22.01/source/coreboot-4.22.01"),
        ("Barebox", "2024.01.0", "Embedded Kbuild (obj-y, pbl-y)", "results/workspaces/barebox/source/barebox-2024.01.0"),
        ("Das U-Boot", "2024.01", "Universal Bootloader Kbuild", "results/workspaces/uboot/source/u-boot-2024.01"),
    ]

    all_results = []
    for name, ver, dialect, path in corpora:
        if os.path.exists(path):
            r = evaluate_corpus(name, ver, dialect, path)
            all_results.append(r)

    print("\n\n" + "="*80)
    print("FINAL CONSOLIDATED RESULTS ACROSS ALL CORPORA")
    print("="*80)
    print(json.dumps(all_results, indent=2))

    with open("results/all_corpora_results.json", "w") as f:
        json.dump(all_results, f, indent=2)


if __name__ == "__main__":
    main()
