#!/usr/bin/env python3
"""Empirical Comparison: kfold vs kmax (M16 / RQ1).

Compares kfold against the latest stable release of kmax (v4.10) across all five
benchmark corpora (Linux Kernel, BusyBox, Barebox, Das U-Boot, and coreboot).
Evaluates:
- Makefile coverage (total files successfully parsed and extracted)
- Target compilation units extracted (.o / .a objects)
- Kconfig configuration symbols tracked
- Analysis wall-clock time
- Semantic dialect compatibility
"""

import json
import os
import pathlib
import re
import subprocess
import sys
import time
import z3

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

from alg import Run
from census import GLOBAL_METRICS
import settings

KMAX_BIN = "/home/tnguyen/.local/bin/kmax"


def run_kfold_on_corpus(corpus_name, corpus_path):
    """Run kfold symbolic execution on a corpus."""
    print(f"[*] Running kfold on {corpus_name} ({corpus_path})...")
    GLOBAL_METRICS.reset()
    st = time.time()
    root_path = pathlib.Path(corpus_path).resolve()
    runner = Run(root_path)
    tmpdir = runner.go()
    elapsed = time.time() - st

    kbuilds = getattr(runner, 'all_kbuilds', getattr(runner, 'kbuilds', []))
    main_dir = getattr(runner, 'maindir', getattr(runner, 'main_dir', root_path))
    mysettings = getattr(runner, 'mysettings', None)

    target_objects = {}
    config_vars = set()

    for kb in kbuilds:
        state = kb.state
        parent = kb.makefile.parent
        for v in state.target_files:
            if mysettings and v.name in mysettings.target_vars:
                continue
            for word, wcond in v.valconds.items():
                if isinstance(word, str) and word.endswith(('.o', '.c', '.s', '.S', '.a', '.ads', '.adb')):
                    try:
                        rel = str((parent / word).relative_to(main_dir))
                    except ValueError:
                        rel = str(word)
                    target_objects[rel] = wcond

                    if isinstance(wcond, z3.ExprRef):
                        def get_syms(e):
                            if z3.is_const(e) and e.decl().kind() == z3.Z3_OP_UNINTERPRETED:
                                return {str(e.decl().name())}
                            res = set()
                            for child in e.children():
                                res.update(get_syms(child))
                            return res
                        config_vars.update(get_syms(wcond))

    summary = GLOBAL_METRICS.summary()
    return {
        "tool": "kfold",
        "corpus": corpus_name,
        "makefiles_analyzed": len(kbuilds),
        "target_objects_count": len(target_objects),
        "config_symbols_count": len(config_vars),
        "wall_time_s": elapsed,
        "peak_rss_mb": summary["peak_rss_kib"] / 1024.0,
        "target_objects": list(target_objects.keys()),
    }


def run_kmax_on_corpus(corpus_name, corpus_path):
    """Run kmax on a corpus across all its Makefiles."""
    print(f"[*] Running kmax (v4.10) on {corpus_name} ({corpus_path})...")
    root_path = pathlib.Path(corpus_path).resolve()
    
    # Discover Makefiles / Kbuild files
    candidates = []
    for p in root_path.rglob("*"):
        if p.is_file() and (p.name.startswith("Makefile") or p.name.startswith("Kbuild") or p.name.endswith(".inc")):
            # skip non-makefile text or temporary files
            if not p.name.endswith(".o") and not p.name.endswith(".cmd"):
                candidates.append(p)

    target_objects = set()
    config_vars = set()
    makefiles_success = 0
    makefiles_failed = 0
    
    # Dummy template lines emitted by kmax regardless of makefile content
    dummy_patterns = {
        "$(net-m)", "$(core-m)", "$(drivers-m)", "$(libs-m)", "$(head-m)",
        "$(libs-y)", "$(net-y)", "$(core-y)", "$(drivers-y)", "$(head-y)",
        "$(obj-m)", "$(lib-m)", "$(lib-y)"
    }

    st = time.time()
    
    def process_mk(mk):
        try:
            res = subprocess.run(
                [KMAX_BIN, "-u", "-B", str(mk)],
                capture_output=True,
                text=True,
                timeout=30
            )
            objs = set()
            syms = set()
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    if line.startswith("unit_pc "):
                        parts = line.split(maxsplit=2)
                        if len(parts) >= 2:
                            unit = parts[1]
                            cond = parts[2] if len(parts) > 2 else "1"
                            if any(d in unit for d in dummy_patterns):
                                continue
                            if unit.endswith(".o") or unit.endswith(".a"):
                                try:
                                    rel = str(pathlib.Path(unit).resolve().relative_to(root_path))
                                except Exception:
                                    rel = str(unit)
                                objs.add(rel)
                                sym_matches = re.findall(r'CONFIG_[A-Za-z0-9_]+', cond)
                                syms.update(sym_matches)
                return True, objs, syms
            else:
                return False, set(), set()
        except Exception:
            return False, set(), set()

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as executor:
        futures = {executor.submit(process_mk, mk): mk for mk in candidates}
        for future in concurrent.futures.as_completed(futures):
            success, objs, syms = future.result()
            if success:
                makefiles_success += 1
                target_objects.update(objs)
                config_vars.update(syms)
            else:
                makefiles_failed += 1

    elapsed = time.time() - st
    return {
        "tool": "kmax 4.10",
        "corpus": corpus_name,
        "total_makefiles_found": len(candidates),
        "makefiles_analyzed": makefiles_success,
        "makefiles_failed": makefiles_failed,
        "target_objects_count": len(target_objects),
        "config_symbols_count": len(config_vars),
        "wall_time_s": elapsed,
        "target_objects": sorted(list(target_objects)),
    }


def main():
    corpora = [
        ("BusyBox", "results/workspaces/busybox/source/busybox-1.36.1"),
        ("Barebox", "results/workspaces/barebox/source/barebox-2024.01.0"),
        ("Das U-Boot", "results/workspaces/uboot/source/u-boot-2024.01"),
        ("coreboot", "results/workspaces/coreboot/source/coreboot-4.22.01/source/coreboot-4.22.01"),
        ("Linux Kernel", "tests/linux/linux_orig"),
    ]

    results = {}
    for name, path in corpora:
        if not os.path.exists(path):
            print(f"[-] Path not found: {path}")
            continue

        kfold_res = run_kfold_on_corpus(name, path)
        kmax_res = run_kmax_on_corpus(name, path)

        # Compute overlap
        kfold_set = set(kfold_res["target_objects"])
        kmax_set = set(kmax_res["target_objects"])
        common = kfold_set & kmax_set
        kfold_only = kfold_set - kmax_set
        kmax_only = kmax_set - kfold_set

        results[name] = {
            "corpus": name,
            "kfold": {
                "makefiles": kfold_res["makefiles_analyzed"],
                "objects": kfold_res["target_objects_count"],
                "symbols": kfold_res["config_symbols_count"],
                "time_s": round(kfold_res["wall_time_s"], 2),
            },
            "kmax_4_10": {
                "makefiles": kmax_res["makefiles_analyzed"],
                "objects": kmax_res["target_objects_count"],
                "symbols": kmax_res["config_symbols_count"],
                "time_s": round(kmax_res["wall_time_s"], 2),
                "failed_makefiles": kmax_res["makefiles_failed"],
            },
            "target_comparison": {
                "common_objects": len(common),
                "kfold_only_objects": len(kfold_only),
                "kmax_only_objects": len(kmax_only),
                "kfold_coverage_advantage": len(kfold_set) - len(kmax_set),
            }
        }
        print(f"[+] Finished {name}: kfold={kfold_res['target_objects_count']} objs, kmax={kmax_res['target_objects_count']} objs (Diff: +{len(kfold_only)} kfold-only, +{len(kmax_only)} kmax-only)")

    out_file = ROOT_DIR / "results" / "kfold_vs_kmax_comparison.json"
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n[+] Wrote complete kfold vs kmax comparison to {out_file}")


if __name__ == "__main__":
    main()
