#!/usr/bin/env python3
"""3-Way Triangulation: Physical GCC Compiler Build vs GNU Make vs kfold.

This script executes live physical GCC kernel builds and validates kfold's symbolic
presence conditions against both physical object artifacts on disk and GNU Make
target evaluations.

Configurations evaluated:
1. Minimal profile (`tinyconfig`)
2. Upstream standard profile (`defconfig`)
3. Production host profile (`localconfig` / Debian default)

Triangulation comparison:
- Ground Truth A: Physical GCC Build (.o artifacts created in source tree)
- Ground Truth B: GNU Make Evaluation (expanded target lists via GNU Make)
- Evaluator:      kfold SMT Valuation (symbolic presence conditions)
"""

import argparse
import concurrent.futures
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))
sys.path.insert(0, str(ROOT_DIR))

from alg import Run
import helpers.vcommon as CM
import settings
from tools.compare_kfold_with_gnu_make import (
    LinuxDifferentialValidator,
    compile_expr,
    extract_gnu_make_objects,
)
from tools.validate_linux_configs import parse_kconfig_file


def get_physical_objects(build_dir: pathlib.Path) -> Set[str]:
    """Find all .o files created during physical kernel compilation, excluding build tools."""
    objs = set()
    for root, dirs, files in os.walk(build_dir):
        rel_root = os.path.relpath(root, build_dir)
        if any(rel_root.startswith(p) for p in ["scripts", "tools", ".git", "Documentation"]):
            continue
        for f in files:
            if f.endswith(".o") and not f.endswith(".mod.o") and not f.endswith(".cmd"):
                rel_path = os.path.normpath(os.path.join(rel_root, f))
                if rel_path.startswith("./"):
                    rel_path = rel_path[2:]
                objs.add(rel_path)
    return objs


class PhysicalBuildTriangulator:
    def __init__(self, kernel_dir: pathlib.Path, makefile_dir: Optional[pathlib.Path] = None):
        self.kernel_dir = kernel_dir.resolve()
        self.makefile_dir = (makefile_dir or kernel_dir).resolve()
        self.validator = LinuxDifferentialValidator(self.makefile_dir)

    def run_configuration(
        self,
        config_name: str,
        jobs: int = 8,
        compile_kernel: bool = True,
        cc: Optional[str] = None,
    ) -> Dict[str, Any]:
        print(f"\n{'='*70}\n[+] Triangulating Configuration: {config_name}\n{'='*70}")

        # 1. Clean workspace
        print(f"[*] Cleaning kernel build directory: {self.kernel_dir}")
        subprocess.run(["make", "clean"], cwd=self.kernel_dir, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # 2. Set up config
        if config_name == "tinyconfig":
            print("[*] Generating tinyconfig...")
            subprocess.run(["make", "tinyconfig"], cwd=self.kernel_dir, check=True)
        elif config_name == "defconfig":
            print("[*] Generating defconfig...")
            subprocess.run(["make", "defconfig"], cwd=self.kernel_dir, check=True)
        elif config_name in ("localconfig", "debian"):
            boot_configs = list(pathlib.Path("/boot").glob("config-*"))
            if boot_configs:
                print(f"[*] Using host boot config: {boot_configs[0]}")
                shutil.copy(boot_configs[0], self.kernel_dir / ".config")
                subprocess.run(["make", "olddefconfig"], cwd=self.kernel_dir, check=True)
            else:
                print("[*] Fallback to defconfig...")
                subprocess.run(["make", "defconfig"], cwd=self.kernel_dir, check=True)
        elif config_name == "allmodconfig":
            print("[*] Generating allmodconfig...")
            subprocess.run(["make", "allmodconfig"], cwd=self.kernel_dir, check=True)

        config_path = self.kernel_dir / ".config"
        config_env = parse_kconfig_file(config_path) if config_path.exists() else {}
        print(f"[+] Active configuration: {len(config_env)} Kconfig symbols")

        # 3. Physical Compilation
        t_build_elapsed = 0.0
        physical_objs = set()
        if compile_kernel:
            # Linux distinguishes CC (target compiler) from HOSTCC (host-tool compiler,
            # e.g. tools/bpf/resolve_btfids); overriding only CC leaves host tools built
            # with the system default compiler, so both need to be set together.
            cc_args = [f"CC={cc}", f"HOSTCC={cc}"] if cc else []
            print(f"[+] Starting physical GCC build (`make -j{jobs} {' '.join(cc_args)}`)...")
            t_start = time.time()
            build_res = subprocess.run(
                ["make", f"-j{jobs}"] + cc_args,
                cwd=self.kernel_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            t_build_elapsed = time.time() - t_start
            physical_objs = get_physical_objects(self.kernel_dir)
            print(f"[+] Physical build completed in {t_build_elapsed:.2f}s (Exit code: {build_res.returncode})")
            print(f"[+] Physical .o objects produced: {len(physical_objs)}")

            # Archive the physical .o artifacts for this config before the next `make clean`.
            evidence_dir = ROOT_DIR / "evidence" / "physical_builds" / config_name
            if evidence_dir.exists():
                shutil.rmtree(evidence_dir)
            evidence_dir.mkdir(parents=True, exist_ok=True)
            for rel in physical_objs:
                src = self.kernel_dir / rel
                dst = evidence_dir / rel
                try:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                except OSError:
                    pass
            print(f"[+] Archived {len(physical_objs)} .o artifacts to {evidence_dir}")

        # 4. GNU Make & kfold Evaluations
        t_eval_start = time.time()
        global_kfold_active = set()
        global_gmake_active = set()
        global_all_targets = set()

        def process_kb(entry):
            kb, local_targets = entry
            mf = kb.makefile
            parent = mf.parent

            k_active = set()
            all_local = set()
            for word, rel, fn in local_targets:
                all_local.add(rel)
                if fn(config_env):
                    k_active.add(rel)

            g_raw = extract_gnu_make_objects(mf, config_env)
            g_active = set()
            for word in g_raw:
                try:
                    rel = str((parent / word).relative_to(self.validator.main_dir))
                except ValueError:
                    rel = str(word)
                g_active.add(rel)

            return (all_local, k_active, g_active)

        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(process_kb, self.validator.kb_target_fns))

        for all_local, k_active, g_active in results:
            global_all_targets.update(all_local)
            global_kfold_active.update(k_active)
            global_gmake_active.update(g_active)

        t_eval_elapsed = time.time() - t_eval_start
        print(f"[+] GNU Make & kfold evaluations completed in {t_eval_elapsed:.2f}s")
        print(f"[+] GNU Make active objects: {len(global_gmake_active)}")
        print(f"[+] kfold predicted active objects: {len(global_kfold_active)}")

        # 5. Triangulation Metrics
        # (A) kfold vs GNU Make
        relevant_gmake = global_gmake_active & global_all_targets
        tp_km = global_kfold_active & global_gmake_active
        fp_km = global_kfold_active - global_gmake_active
        fn_km = relevant_gmake - global_kfold_active
        tn_km = (global_all_targets - global_kfold_active) - global_gmake_active
        prec_km = (len(tp_km) / max(1, len(tp_km) + len(fp_km))) * 100.0
        rec_km = (len(tp_km) / max(1, len(tp_km) + len(fn_km))) * 100.0
        acc_km = ((len(tp_km) + len(tn_km)) / max(1, len(global_all_targets))) * 100.0

        # (B) kfold vs Physical Build
        relevant_phys = physical_objs & global_all_targets
        tp_kp = global_kfold_active & physical_objs
        fp_kp = global_kfold_active - physical_objs
        fn_kp = relevant_phys - global_kfold_active
        prec_kp = (len(tp_kp) / max(1, len(tp_kp) + len(fp_kp))) * 100.0 if len(physical_objs) > 0 else 0.0
        rec_kp = (len(tp_kp) / max(1, len(tp_kp) + len(fn_kp))) * 100.0 if len(relevant_phys) > 0 else 0.0

        # (C) GNU Make vs Physical Build
        tp_mp = global_gmake_active & physical_objs
        fp_mp = global_gmake_active - physical_objs
        fn_mp = relevant_phys - global_gmake_active
        prec_mp = (len(tp_mp) / max(1, len(tp_mp) + len(fp_mp))) * 100.0 if len(physical_objs) > 0 else 0.0
        rec_mp = (len(tp_mp) / max(1, len(tp_mp) + len(fn_mp))) * 100.0 if len(relevant_phys) > 0 else 0.0

        print(f"\n--- Triangulation Summary for {config_name} ---")
        print(f"kfold vs GNU Make:      Prec={prec_km:.2f}%, Rec={rec_km:.2f}%, Acc={acc_km:.2f}% (TP={len(tp_km)}, FP={len(fp_km)}, FN={len(fn_km)})")
        if compile_kernel:
            print(f"kfold vs Physical GCC:  Prec={prec_kp:.2f}%, Rec={rec_kp:.2f}% (TP={len(tp_kp)}, FP={len(fp_kp)}, FN={len(fn_kp)})")
            print(f"GNU Make vs Phys GCC:   Prec={prec_mp:.2f}%, Rec={rec_mp:.2f}% (TP={len(tp_mp)}, FP={len(fp_mp)}, FN={len(fn_mp)})")

        return {
            "config_name": config_name,
            "config_symbols": len(config_env),
            "compiler": cc or "default (gcc)",
            "build_exit_code": build_res.returncode if compile_kernel else None,
            "build_time_s": round(t_build_elapsed, 2),
            "eval_time_s": round(t_eval_elapsed, 2),
            "counts": {
                "total_targets": len(global_all_targets),
                "physical_objects": len(physical_objs),
                "gmake_active": len(global_gmake_active),
                "kfold_active": len(global_kfold_active),
            },
            "kfold_vs_gmake": {
                "tp": len(tp_km), "fp": len(fp_km), "fn": len(fn_km), "tn": len(tn_km),
                "precision": round(prec_km, 2), "recall": round(rec_km, 2), "accuracy": round(acc_km, 2),
            },
            "kfold_vs_physical": {
                "tp": len(tp_kp), "fp": len(fp_kp), "fn": len(fn_kp),
                "precision": round(prec_kp, 2), "recall": round(rec_kp, 2),
            },
            "gmake_vs_physical": {
                "tp": len(tp_mp), "fp": len(fp_mp), "fn": len(fn_mp),
                "precision": round(prec_mp, 2), "recall": round(rec_mp, 2),
            },
            "discrepancies": {
                "kfold_only": sorted(list(fp_km))[:20],
                "gmake_only": sorted(list(fn_km))[:20],
                "physical_only": sorted(list(physical_objs - global_kfold_active))[:20] if compile_kernel else [],
            }
        }


def main():
    parser = argparse.ArgumentParser(description="3-Way Physical Build Triangulation")
    parser.add_argument("--kernel-dir", type=pathlib.Path, default=ROOT_DIR / "results" / "workspaces" / "linux")
    parser.add_argument("--makefile-dir", type=pathlib.Path, default=ROOT_DIR / "tests" / "linux" / "linux_orig")
    parser.add_argument("--configs", nargs="+", default=["tinyconfig", "defconfig"])
    parser.add_argument("--output", type=pathlib.Path, default=ROOT_DIR / "results" / "linux_physical_build_validation.json")
    parser.add_argument("-j", "--jobs", type=int, default=8)
    parser.add_argument("--skip-compile", action="store_true")
    parser.add_argument("--cc", type=str, default=None, help="Override compiler (e.g. gcc-12)")
    args = parser.parse_args()

    triangulator = PhysicalBuildTriangulator(args.kernel_dir, args.makefile_dir)
    results = {}
    for cfg in args.configs:
        res = triangulator.run_configuration(cfg, jobs=args.jobs, compile_kernel=not args.skip_compile, cc=args.cc)
        results[cfg] = res

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n[+] Wrote complete triangulation results to {args.output}")


if __name__ == "__main__":
    main()
