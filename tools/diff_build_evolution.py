#!/usr/bin/env python3
"""Differential Build Evolution Analysis Across Releases.

Uses Z3 SMT queries to analyze changes in build logic and presence conditions
between system versions:
1. Target Added: Object newly introduced in version V2.
2. Target Retired: Object removed in version V2.
3. Target Unchanged: Object preserved with provably equivalent condition (UNSAT(phi_v1 != phi_v2)).
4. Target Altered: Condition modified between releases:
   - Generalized (phi_v1 => phi_v2 is VALID): Builds under wider configuration space.
   - Restricted (phi_v2 => phi_v1 is VALID): Builds under narrower configuration space.
   - Diverged: Configuration space shifted in non-subsumptive ways.
   - Synthesizes differential witness configurations demonstrating the behavioral change.
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


def extract_targets_and_conditions(root_dir):
    root_path = pathlib.Path(root_dir).resolve()
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

    return target_objects


def model_to_dict(model):
    res = {}
    for decl in model.decls():
        val = model[decl]
        res[str(decl.name())] = bool(z3.is_true(val))
    return res


def analyze_evolution(corpus_name, v1_name, v1_dir, v2_name, v2_dir):
    print(f"\n=======================================================")
    print(f"Differential Build Evolution: {corpus_name} ({v1_name} -> {v2_name})")
    print(f"=======================================================")

    st = time.time()
    targets_v1 = extract_targets_and_conditions(v1_dir)
    targets_v2 = extract_targets_and_conditions(v2_dir)

    set_v1 = set(targets_v1.keys())
    set_v2 = set(targets_v2.keys())

    added_targets = sorted(list(set_v2 - set_v1))
    retired_targets = sorted(list(set_v1 - set_v2))
    common_targets = sorted(list(set_v1 & set_v2))

    unchanged_targets = []
    altered_targets = []

    solver = z3.Solver()

    for obj in common_targets:
        phi1 = targets_v1[obj]
        phi2 = targets_v2[obj]

        # Fast path: identical string representation
        if str(phi1) == str(phi2):
            unchanged_targets.append(obj)
            continue

        # Check equivalence: phi1 != phi2
        solver.push()
        solver.add(phi1 != phi2)
        diff_sat = solver.check()
        diff_model = None
        if diff_sat == z3.sat:
            diff_model = solver.model()
        solver.pop()

        if diff_sat == z3.unsat:
            unchanged_targets.append(obj)
        else:
            # Condition changed! Classify nature of alteration
            # 1. Check if phi1 => phi2 is valid (i.e. Not(phi1 => phi2) is unsat)
            solver.push()
            solver.add(z3.Not(z3.Implies(phi1, phi2)))
            gen_unsat = (solver.check() == z3.unsat)
            solver.pop()

            # 2. Check if phi2 => phi1 is valid
            solver.push()
            solver.add(z3.Not(z3.Implies(phi2, phi1)))
            res_unsat = (solver.check() == z3.unsat)
            solver.pop()

            if gen_unsat and not res_unsat:
                classification = "generalized (widened)"
            elif res_unsat and not gen_unsat:
                classification = "restricted (tightened)"
            elif gen_unsat and res_unsat:
                classification = "equivalent (simplification)"
                unchanged_targets.append(obj)
                continue
            else:
                classification = "diverged"

            witness = model_to_dict(diff_model) if diff_model else {}

            altered_targets.append({
                "target": obj,
                "classification": classification,
                "condition_v1": str(phi1)[:120].replace("\n", " "),
                "condition_v2": str(phi2)[:120].replace("\n", " "),
                "witness_diff_config": witness
            })

    elapsed = round(time.time() - st, 2)

    report = {
        "corpus": corpus_name,
        "v1": v1_name,
        "v2": v2_name,
        "v1_total_targets": len(targets_v1),
        "v2_total_targets": len(targets_v2),
        "common_targets_count": len(common_targets),
        "unchanged_targets_count": len(unchanged_targets),
        "altered_targets_count": len(altered_targets),
        "added_targets_count": len(added_targets),
        "retired_targets_count": len(retired_targets),
        "altered_targets_breakdown": collections.Counter(a["classification"] for a in altered_targets),
        "sample_added_targets": added_targets[:10],
        "sample_retired_targets": retired_targets[:10],
        "sample_altered_targets": altered_targets[:10],
        "elapsed_seconds": elapsed,
    }

    print(f"Results for {corpus_name}:")
    print(f"  V1 Targets: {len(targets_v1)} | V2 Targets: {len(targets_v2)}")
    print(f"  Unchanged: {len(unchanged_targets)} | Altered: {len(altered_targets)}")
    print(f"  Added: {len(added_targets)} | Retired: {len(retired_targets)}")
    print(f"  Altered breakdown: {dict(report['altered_targets_breakdown'])}")
    print(f"  Elapsed: {elapsed}s")

    return report


def main():
    comparisons = [
        (
            "BusyBox",
            "1.35.0",
            "results/workspaces/diff_evolution/busybox-1.35.0",
            "1.36.1",
            "results/workspaces/busybox/source/busybox-1.36.1"
        ),
        (
            "Das U-Boot",
            "2023.01",
            "results/workspaces/diff_evolution/u-boot-2023.01",
            "2024.01",
            "results/workspaces/uboot/source/u-boot-2024.01"
        ),
    ]

    all_reports = []
    for corpus_name, v1_name, v1_dir, v2_name, v2_dir in comparisons:
        if os.path.exists(v1_dir) and os.path.exists(v2_dir):
            rep = analyze_evolution(corpus_name, v1_name, v1_dir, v2_name, v2_dir)
            all_reports.append(rep)

    print("\n" + "="*80)
    print("SAVING DIFFERENTIAL BUILD EVOLUTION REPORT")
    print("="*80)
    with open("results/build_evolution_report.json", "w") as f:
        json.dump(all_reports, f, indent=2)
    print("Saved to results/build_evolution_report.json")


if __name__ == "__main__":
    main()
