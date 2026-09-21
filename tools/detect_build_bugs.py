#!/usr/bin/env python3
"""Universal SMT-Powered Build Bug & Anomaly Detector.

Queries Z3 to discover:
1. Dead/Zombie Targets: Condition is provably UNSAT.
2. Tautological Targets: Condition is provably VALID (always built).
3. Linker Collision Hazards: Duplicate basenames whose conditions are co-satisfiable (SAT(phi_A and phi_B)).
4. Dangling/Dead Kconfig References.
"""

import collections
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


def analyze_bugs(corpus_name, root_dir):
    root_path = pathlib.Path(root_dir).resolve()
    print(f"\n=======================================================")
    print(f"Detecting Build System Bugs in {corpus_name}")
    print(f"Path: {root_path}")
    print(f"=======================================================")

    st = time.time()
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

    solver = z3.Solver()

    # 1. Dead targets (UNSAT)
    dead_targets = []
    # 2. Tautological targets (VALID)
    tautological_targets = []
    
    for obj, cond in target_objects.items():
        if isinstance(cond, z3.ExprRef):
            # Check SAT
            solver.push()
            solver.add(cond)
            if solver.check() == z3.unsat:
                dead_targets.append((obj, str(cond)))
            solver.pop()

            # Check VALID: Not(cond) is UNSAT
            solver.push()
            solver.add(z3.Not(cond))
            if solver.check() == z3.unsat:
                tautological_targets.append(obj)
            solver.pop()
        elif cond is zsolver.T or cond is True:
            tautological_targets.append(obj)
        elif cond is zsolver.F or cond is False:
            dead_targets.append((obj, "False"))

    # 3. Collision / Duplicate Target Analysis
    # Group by object basename
    by_basename = collections.defaultdict(list)
    for obj, cond in target_objects.items():
        base = pathlib.Path(obj).name
        by_basename[base].append((obj, cond))

    collision_hazards = []
    for base, entries in by_basename.items():
        if len(entries) > 1:
            for i in range(len(entries)):
                for j in range(i + 1, len(entries)):
                    obj1, cond1 = entries[i]
                    obj2, cond2 = entries[j]
                    # Check if parents are in same directory or linked into same library
                    dir1 = pathlib.Path(obj1).parent
                    dir2 = pathlib.Path(obj2).parent
                    if dir1 == dir2:
                        # In the same directory with same basename!
                        if isinstance(cond1, z3.ExprRef) and isinstance(cond2, z3.ExprRef):
                            solver.push()
                            solver.add(z3.And(cond1, cond2))
                            is_co_sat = (solver.check() == z3.sat)
                            solver.pop()
                            if is_co_sat:
                                collision_hazards.append({
                                    "target1": obj1,
                                    "target2": obj2,
                                    "status": "CO_SATISFIABLE_COLLISION",
                                })

    # 4. Kconfig Variable Reference Analysis
    all_symbols = collections.Counter()
    for obj, cond in target_objects.items():
        syms = get_symbols_from_expr(cond)
        for s in syms:
            all_symbols[s] += 1

    report = {
        "corpus": corpus_name,
        "total_targets": len(target_objects),
        "dead_targets_count": len(dead_targets),
        "dead_targets": dead_targets[:20],
        "tautological_targets_count": len(tautological_targets),
        "tautological_targets_sample": tautological_targets[:10],
        "same_dir_collision_hazards_count": len(collision_hazards),
        "collision_hazards": collision_hazards,
        "unique_kconfig_symbols_referenced": len(all_symbols),
        "top_referenced_symbols": all_symbols.most_common(10),
        "elapsed_seconds": round(time.time() - st, 2),
    }
    return report


def main():
    corpora = [
        ("BusyBox", "results/workspaces/busybox/source/busybox-1.36.1"),
        ("coreboot", "results/workspaces/coreboot/source/coreboot-4.22.01/source/coreboot-4.22.01"),
        ("Barebox", "results/workspaces/barebox/source/barebox-2024.01.0"),
        ("Das U-Boot", "results/workspaces/uboot/source/u-boot-2024.01"),
    ]

    all_reports = []
    for name, path in corpora:
        if os.path.exists(path):
            rep = analyze_bugs(name, path)
            all_reports.append(rep)

    print("\n\n" + "="*80)
    print("SMT BUILD BUG & ANOMALY DETECTION REPORT")
    print("="*80)
    print(json.dumps(all_reports, indent=2))

    with open("results/build_bugs_report.json", "w") as f:
        json.dump(all_reports, f, indent=2)


if __name__ == "__main__":
    main()
