#!/usr/bin/env python3
"""Automated Kconfig-Kbuild Consistency & Zombie Symbol Linter.

Extracts all declared `config SYMBOL` from Kconfig files and cross-checks with
all `CONFIG_SYMBOL` referenced across Kbuild Makefiles to discover:
1. Orphan Makefile References: CONFIG_* in Makefiles not in Kconfig.
2. Unreferenced Kconfig Symbols: Kconfig options that gate zero Makefile targets.
"""

import collections
import json
import os
import pathlib
import re
import sys
import time
import z3

# Set up PYTHONPATH
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import helpers.vcommon as CM
import helpers.zsolver as zsolver
import settings
from alg import Run


def extract_kconfig_declared_symbols(root_dir):
    root_path = pathlib.Path(root_dir).resolve()
    kconfig_files = []
    for p in root_path.rglob("*"):
        if p.is_file() and ("Kconfig" in p.name or "Config." in p.name or p.name.endswith(".kconfig") or p.name.endswith(".in") or p.name.endswith(".src")):
            kconfig_files.append(p)

    declared_symbols = set()
    for kf in kconfig_files:
        try:
            content = kf.read_text(errors='ignore')
            # Match 'config FOO' or 'menuconfig FOO'
            for match in re.finditer(r"^[ \t]*(?:config|menuconfig)[ \t]+([a-zA-Z0-9_]+)", content, re.MULTILINE):
                sym = match.group(1).strip()
                declared_symbols.add("CONFIG_" + sym)
        except Exception:
            pass

    return declared_symbols, len(kconfig_files)


def lint_kconfig_consistency(corpus_name, root_dir):
    root_path = pathlib.Path(root_dir).resolve()
    print(f"\n=======================================================")
    print(f"Linting Kconfig-Kbuild Consistency: {corpus_name}")
    print(f"=======================================================")

    st = time.time()
    # 1. Parse Kconfig
    declared_symbols, kconfig_count = extract_kconfig_declared_symbols(root_path)

    # 2. Extract Makefile referenced symbols via skbuild
    runner = Run(root_path)
    tmpdir = runner.go()

    kbuilds = getattr(runner, 'all_kbuilds', getattr(runner, 'kbuilds', []))
    main_dir = getattr(runner, 'maindir', getattr(runner, 'main_dir', root_path))
    mysettings = getattr(runner, 'mysettings', None)

    def get_symbols_from_expr(e):
        if not isinstance(e, z3.ExprRef):
            return set()
        if z3.is_const(e) and e.decl().kind() == z3.Z3_OP_UNINTERPRETED:
            return {str(e.decl().name())}
        res = set()
        for child in e.children():
            res.update(get_symbols_from_expr(child))
        return res

    makefile_symbols = collections.Counter()
    for kb in kbuilds:
        for name, v in kb.state.states.items():
            if name.startswith("CONFIG_"):
                makefile_symbols[name] += 1
            for word, cond in v.valconds.items():
                for s in get_symbols_from_expr(cond):
                    if s.startswith("CONFIG_"):
                        makefile_symbols[s] += 1

    makefile_sym_set = set(makefile_symbols.keys())

    # Cross-reference
    orphan_makefile_symbols = sorted(list(makefile_sym_set - declared_symbols))
    unreferenced_kconfig_symbols = sorted(list(declared_symbols - makefile_sym_set))
    co_occurring_symbols = makefile_sym_set & declared_symbols

    print(f"Kconfig Files: {kconfig_count} | Declared Symbols: {len(declared_symbols)}")
    print(f"Makefiles Analyzed: {len(kbuilds)} | Makefile Referenced Symbols: {len(makefile_sym_set)}")
    print(f"Co-occurring Valid Symbols: {len(co_occurring_symbols)}")
    print(f"Orphan Makefile Symbols (in Makefiles, not in Kconfig): {len(orphan_makefile_symbols)}")
    print(f"Unused in Makefile Kconfig Symbols (pure C preprocessor / ghost flags): {len(unreferenced_kconfig_symbols)}")

    return {
        "corpus": corpus_name,
        "kconfig_files_count": kconfig_count,
        "kconfig_declared_symbols_count": len(declared_symbols),
        "makefile_referenced_symbols_count": len(makefile_sym_set),
        "co_occurring_symbols_count": len(co_occurring_symbols),
        "orphan_makefile_symbols_count": len(orphan_makefile_symbols),
        "orphan_makefile_symbols_sample": orphan_makefile_symbols[:15],
        "unused_in_makefile_kconfig_symbols_count": len(unreferenced_kconfig_symbols),
        "elapsed_seconds": round(time.time() - st, 2),
    }


def main():
    corpora = [
        ("BusyBox 1.36.1", "results/workspaces/busybox/source/busybox-1.36.1"),
        ("Barebox 2024.01.0", "results/workspaces/barebox/source/barebox-2024.01.0"),
        ("Das U-Boot 2024.01", "results/workspaces/uboot/source/u-boot-2024.01"),
    ]

    all_reports = []
    for name, path in corpora:
        if os.path.exists(path):
            rep = lint_kconfig_consistency(name, path)
            all_reports.append(rep)

    print("\n\n" + "="*80)
    print("KCONFIG-KBUILD CONSISTENCY LINTER REPORT")
    print("="*80)
    print(json.dumps(all_reports, indent=2))

    with open("results/kconfig_consistency_report.json", "w") as f:
        json.dump(all_reports, f, indent=2)


if __name__ == "__main__":
    main()
