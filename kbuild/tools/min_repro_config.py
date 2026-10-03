#!/usr/bin/env python3
"""Minimal Delta Debugging & Minimal-Weight Configuration Synthesis using Z3 Optimize / MaxSAT.

Given target objects (e.g. a specific buggy driver or subsystem), synthesizes the minimal
.config (fewest active CONFIG_* options) required to build them.
"""

import argparse
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


def get_symbols_from_expr(e):
    if not isinstance(e, z3.ExprRef):
        return set()
    if z3.is_const(e) and e.decl().kind() == z3.Z3_OP_UNINTERPRETED:
        return {str(e.decl().name())}
    res = set()
    for child in e.children():
        res.update(get_symbols_from_expr(child))
    return res


def synthesize_minimal_config(corpus_path, target_names):
    root_path = pathlib.Path(corpus_path).resolve()
    print(f"Analyzing {root_path} to synthesize minimal configuration for: {target_names}")

    runner = Run(root_path)
    tmpdir = runner.go()

    kbuilds = getattr(runner, 'all_kbuilds', getattr(runner, 'kbuilds', []))
    main_dir = getattr(runner, 'maindir', getattr(runner, 'main_dir', root_path))
    mysettings = getattr(runner, 'mysettings', None)

    target_objects = {}
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

    # Match requested targets
    selected_conds = []
    matched_targets = []
    all_syms = set()

    for req in target_names:
        found = False
        for obj, cond in target_objects.items():
            if req == obj or obj.endswith(req) or req in obj:
                selected_conds.append(cond)
                matched_targets.append(obj)
                all_syms.update(get_symbols_from_expr(cond))
                found = True
        if not found:
            print(f"Warning: target '{req}' not found in target graph")

    if not selected_conds:
        print("No valid target conditions found!")
        return None

    # Use Z3 Optimize
    opt = z3.Optimize()
    for cond in selected_conds:
        if isinstance(cond, z3.ExprRef):
            opt.add(cond)
        elif cond is zsolver.F or cond is False:
            print("Error: one or more selected targets are UNSAT!")
            return None

    # Minimize active symbols: soft constraint that each symbol is 'undef'
    # For TwoState/TriState, y is the active value
    zs = zsolver.ZSolver(runner.mysettings)
    copt_vars = {}
    for s in all_syms:
        zvar, optD = zs.get_sort(s)
        copt_vars[s] = (zvar, optD)
        # Soft constraint: prefer undef (weight 1)
        opt.add_soft(zvar == zs.undef_val, 1)

    st = time.time()
    res = opt.check()
    solve_time = time.time() - st

    if res == z3.sat:
        model = opt.model()
        minimal_active = {}
        for s, (zvar, optD) in copt_vars.items():
            val = model.eval(zvar, model_completion=True)
            val_str = str(val).strip('"')
            if val_str and val_str != 'undef':
                minimal_active[s] = val_str

        print(f"\nOptimization successful in {solve_time:.3f}s!")
        print(f"Matched targets ({len(matched_targets)}): {matched_targets}")
        print(f"Minimal active configuration variables ({len(minimal_active)} out of {len(all_syms)} interacting symbols):")
        for s, val in sorted(minimal_active.items()):
            print(f"  {s}={val}")

        return {
            "targets": matched_targets,
            "all_interacting_symbols_count": len(all_syms),
            "minimal_active_symbols_count": len(minimal_active),
            "minimal_config": minimal_active,
            "solve_time_seconds": solve_time,
        }
    else:
        print("Unsatisfiable configuration combination!")
        return None


def main():
    test_cases = [
        ("BusyBox", "results/workspaces/busybox/source/busybox-1.36.1", ["networking/udhcp/dhcpc.o"]),
        ("Barebox", "results/workspaces/barebox/source/barebox-2024.01.0", ["drivers/net/phy/mv88e6xxx.o"]),
        ("Das U-Boot", "results/workspaces/uboot/source/u-boot-2024.01", ["drivers/ram/rockchip/sdram_pctl_px30.o"]),
    ]

    all_results = []
    for name, path, targets in test_cases:
        if os.path.exists(path):
            r = synthesize_minimal_config(path, targets)
            if r:
                r["corpus"] = name
                all_results.append(r)

    print("\n\n" + "="*80)
    print("MINIMAL CONFIGURATION SYNTHESIS REPORT")
    print("="*80)
    print(json.dumps(all_results, indent=2))

    with open("results/min_repro_config_report.json", "w") as f:
        json.dump(all_results, f, indent=2)


if __name__ == "__main__":
    main()
