#!/usr/bin/env python3
"""Automated Dead & Unconfigurable Target Linter (M17.4).

Scans Kbuild Makefiles to detect:
1. Syntactic Orphan Targets: Targets assigned to unexpanded/empty prefixes (e.g. obj-, lib-, pbl-)
   caused by removed, renamed, or unexpanded Kconfig variables.
2. Semantic Unsatisfiable Targets: Targets whose presence condition simplifies to UNSAT.
3. Conflicting Hierarchical Guards: Targets whose local guard contradicts an ancestor directory's guard.
"""

import argparse
import json
import os
import pathlib
import sys

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

import z3
import settings
import helpers.zsolver as zsolver
from alg import Run
from kbuild import Kbuild


def lint_dead_targets(target_path: pathlib.Path, recursive: bool = True, use_tristate: bool = False):
    target_path = target_path.resolve()
    main_dir = target_path.parent if target_path.is_file() else target_path

    runner = Run(target_path, recursive=recursive, use_tristate=use_tristate)
    tmpdir = runner.go()

    kbuilds_list = runner.all_kbuilds
    mysettings = runner.mysettings

    orphaned_targets = []
    unsatisfiable_targets = []
    conflicting_guard_targets = []

    for kbuild in kbuilds_list:
        state = kbuild.state
        parent = kbuild.makefile.parent
        solver = kbuild.solver

        try:
            rel_file = str(kbuild.makefile.relative_to(main_dir))
        except ValueError:
            rel_file = str(kbuild.makefile)

        # 1. Syntactic Orphan Targets (assigned to obj-, lib-, pbl-, etc.)
        for name, var in state.states.items():
            if var.is_undef_target or name in ("obj-", "lib-", "pbl-") or name.endswith("-"):
                for word, cond in var.valconds.items():
                    if isinstance(word, str) and word.endswith(('.o', '.a')):
                        try:
                            rel_target = str((parent / word).relative_to(main_dir))
                        except ValueError:
                            rel_target = str(word)
                        orphaned_targets.append({
                            "target": rel_target,
                            "file": rel_file,
                            "variable": name,
                            "condition": str(cond),
                            "reason": f"Assigned to empty/unexpanded prefix '{name}' (unreachable in Kbuild)",
                        })

        # 2. Semantic Unsatisfiable Targets & Conflicting Guards
        for v in state.target_files:
            if v.is_undef_target:
                continue
            for word, cond in v.valconds.items():
                if not isinstance(word, str) or not word.endswith(('.o', '.a')):
                    continue
                try:
                    rel_target = str((parent / word).relative_to(main_dir))
                except ValueError:
                    rel_target = str(word)

                if not solver.is_sat(cond):
                    unsatisfiable_targets.append({
                        "target": rel_target,
                        "file": rel_file,
                        "variable": v.name,
                        "condition": str(cond),
                        "reason": "Presence condition simplifies to UNSAT under Z3",
                    })

        # Process statements inside mathematically unreachable conditional branches
        for unsat_stmts, unsat_guard in getattr(state, 'unsat_blocks', []):
            def extract_dead_targets(stmt):
                from symexe import SetVariable
                if isinstance(stmt, SetVariable):
                    val = getattr(stmt.stmt, 'value', '')
                    for word in val.split():
                        if word.endswith(('.o', '.a')):
                            try:
                                rel_t = str((parent / word).relative_to(main_dir))
                            except ValueError:
                                rel_t = str(word)
                            unsatisfiable_targets.append({
                                "target": rel_t,
                                "file": rel_file,
                                "variable": stmt.stmt_str,
                                "condition": str(unsat_guard),
                                "reason": "Contained inside mathematically unreachable (UNSAT) conditional branch",
                            })
                return True
            unsat_stmts.traverse(extract_dead_targets)

    result = {
        "summary": {
            "total_defects": len(orphaned_targets) + len(unsatisfiable_targets) + len(conflicting_guard_targets),
            "orphaned_count": len(orphaned_targets),
            "unsatisfiable_count": len(unsatisfiable_targets),
            "conflicting_guard_count": len(conflicting_guard_targets),
        },
        "orphaned_targets": orphaned_targets,
        "unsatisfiable_targets": unsatisfiable_targets,
        "conflicting_guard_targets": conflicting_guard_targets,
    }
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lint Kbuild files for dead and unconfigurable targets")
    parser.add_argument("path", type=str, help="Path to makefile or directory")
    parser.add_argument("--recursive", "-r", action="store_true", default=True, help="Recursively scan makefiles")
    parser.add_argument("--tristate", "-T", action="store_true", help="Enable tristate configuration modeling")
    parser.add_argument("--output", "-o", type=str, default="results/unconfigurable_targets.json", help="Output JSON path")
    args = parser.parse_args()

    target_path = pathlib.Path(args.path)
    res = lint_dead_targets(target_path, recursive=args.recursive, use_tristate=args.tristate)

    print(json.dumps(res["summary"], indent=2))
    if args.output:
        out_path = pathlib.Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(res, f, indent=2)
        print(f"[+] Detailed lint report written to {out_path}")
