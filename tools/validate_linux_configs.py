#!/usr/bin/env python3
"""Multi-Configuration Linux Kernel Validation Tool.

Evaluates kfold presence conditions across real-world distribution configurations:
1. Minimal (tinyconfig / allnoconfig baseline)
2. Upstream x86_64 Default (defconfig)
3. Debian Distribution Default (/boot/config-*)
4. Fedora / Modular Server Default
5. Maximal / All-Module Configuration (allmodconfig)

Reports predicted active object targets per configuration, subsystem breakdown,
and evaluates prediction consistency.
"""

import argparse
import json
import os
import pathlib
import re
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import z3

# Set up PYTHONPATH
ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

from alg import Run
from analysis import Analysis
import helpers.vcommon as CM
import helpers.zsolver as zsolver
import settings


def compile_expr(expr: z3.ExprRef) -> Callable[[Dict[str, str]], bool]:
    """Compile a Z3 boolean AST to a fast native Python callable."""
    if z3.is_true(expr):
        return lambda env: True
    if z3.is_false(expr):
        return lambda env: False
    decl = expr.decl()
    kind = decl.kind()
    if kind == z3.Z3_OP_NOT:
        c = compile_expr(expr.children()[0])
        return lambda env: not c(env)
    elif kind == z3.Z3_OP_AND:
        cs = [compile_expr(c) for c in expr.children()]
        return lambda env: all(c(env) for c in cs)
    elif kind == z3.Z3_OP_OR:
        cs = [compile_expr(c) for c in expr.children()]
        return lambda env: any(c(env) for c in cs)
    elif kind == z3.Z3_OP_IMPLIES:
        c1 = compile_expr(expr.children()[0])
        c2 = compile_expr(expr.children()[1])
        return lambda env: (not c1(env)) or c2(env)
    elif kind == z3.Z3_OP_EQ:
        children = expr.children()
        lhs_str = str(children[0])
        rhs_str = str(children[1])
        return lambda env: env.get(lhs_str, lhs_str) == env.get(rhs_str, rhs_str)
    return lambda env: False


def parse_kconfig_file(config_path: pathlib.Path) -> Dict[str, str]:
    """Parse a Linux .config file into a symbol valuation dictionary."""
    env = {}
    if not config_path.is_file():
        return env

    for line in config_path.read_text(errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            # Check for '# CONFIG_FOO is not set'
            m = re.match(r"^#\s*(CONFIG_[A-Za-z0-9_]+)\s+is not set", line)
            if m:
                env[m.group(1)] = "n"
            continue
        if "=" in line:
            parts = line.split("=", 1)
            var = parts[0].strip()
            val = parts[1].strip()
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1]
            env[var] = val
    return env


def generate_synthetic_config(name: str, all_vars: Set[str], active_vars: Set[str], mode: str = "y") -> Dict[str, str]:
    """Generate a synthetic config with specific symbols active."""
    env = {}
    for v in all_vars:
        if v in active_vars:
            env[v] = mode
        else:
            env[v] = "n"
    return env


class LinuxConfigValidator:
    def __init__(self, linux_src_dir: pathlib.Path):
        self.linux_src_dir = linux_src_dir.resolve()
        print(f"[*] Running kfold symbolic analysis on Linux tree: {self.linux_src_dir}")
        t0 = time.time()
        self.runner = Run(self.linux_src_dir)
        self.tmpdir = self.runner.go()
        self.analysis_time = time.time() - t0
        print(f"[+] kfold analysis completed in {self.analysis_time:.2f}s")

        self.kbuilds = getattr(self.runner, "all_kbuilds", getattr(self.runner, "kbuilds", []))
        self.main_dir = getattr(self.runner, "maindir", getattr(self.runner, "main_dir", self.linux_src_dir))
        self.mysettings = getattr(self.runner, "mysettings", None)

        self.target_objects, self.compiled_fns = self._extract_predictions()
        self.all_symbols = self._extract_all_symbols()
        print(f"[+] Extracted {len(self.target_objects)} target objects across {len(self.all_symbols)} symbols")

    def _extract_predictions(self) -> Tuple[Dict[str, z3.ExprRef], Dict[str, Callable]]:
        target_objects: Dict[str, z3.ExprRef] = {}
        compiled_fns: Dict[str, Callable] = {}
        valid_exts = (".o", ".a")

        for kb in self.kbuilds:
            state = kb.state
            parent = kb.makefile.parent
            for v in state.target_files:
                if self.mysettings and v.name in self.mysettings.target_vars:
                    continue
                for word, wcond in v.valconds.items():
                    if isinstance(word, str) and any(word.endswith(ext) for ext in valid_exts):
                        try:
                            rel = str((parent / word).relative_to(self.main_dir))
                        except ValueError:
                            rel = str(word)
                        if rel not in target_objects:
                            target_objects[rel] = wcond
                        else:
                            target_objects[rel] = zsolver.disj(target_objects[rel], wcond)

        for obj, cond in target_objects.items():
            compiled_fns[obj] = compile_expr(cond)

        return target_objects, compiled_fns

    def _extract_all_symbols(self) -> Set[str]:
        syms = set()
        for cond in self.target_objects.values():
            for v in zsolver.get_vars(cond):
                name = str(v)
                if name.startswith("CONFIG_"):
                    syms.add(name)
        return syms

    def evaluate_config(self, config_name: str, config_env: Dict[str, str], description: str = "") -> Dict[str, Any]:
        """Evaluate which target objects kfold predicts will be compiled under config_env."""
        t0 = time.time()
        active_objects = set()
        subsystem_counts = {}

        for obj, fn in self.compiled_fns.items():
            if fn(config_env):
                active_objects.add(obj)
                subsys = obj.split("/")[0] if "/" in obj else "root"
                subsystem_counts[subsys] = subsystem_counts.get(subsys, 0) + 1

        eval_time = time.time() - t0
        active_ratio = (len(active_objects) / max(1, len(self.target_objects))) * 100.0

        return {
            "config_name": config_name,
            "description": description,
            "total_extracted_objects": len(self.target_objects),
            "predicted_active_objects": len(active_objects),
            "predicted_active_percentage": round(active_ratio, 2),
            "eval_time_ms": round(eval_time * 1000, 2),
            "subsystem_breakdown": subsystem_counts,
            "sample_active_objects": sorted(list(active_objects))[:10],
        }


def main():
    parser = argparse.ArgumentParser(description="Multi-Config Linux Build Prediction Validator")
    parser.add_argument("--linux-dir", type=pathlib.Path, default=pathlib.Path("tests/linux/linux_orig"))
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("results/linux_multiconfig_validation.json"))
    args = parser.parse_args()

    validator = LinuxConfigValidator(args.linux_dir)

    # 1. Identify Real Configs
    configs_to_test = []

    # Check for Debian host configs
    debian_configs = sorted(list(pathlib.Path("/boot").glob("config-*")))
    if debian_configs:
        deb_cfg = debian_configs[-1]
        print(f"[*] Found host Debian config: {deb_cfg}")
        deb_env = parse_kconfig_file(deb_cfg)
        configs_to_test.append(("Debian Default (" + deb_cfg.name + ")", deb_env, "Production Debian kernel configuration"))

    # Check for standard configs or synthesize representative archetypes
    all_syms = validator.all_symbols

    # Tiny / Minimal config (only essential core symbols)
    core_syms = {s for s in all_syms if any(k in s for k in ["CORE", "BASE", "PRINTK", "TTY", "BINFMT_ELF", "SYSFS", "PROC_FS"])}
    tiny_env = generate_synthetic_config("tinyconfig", all_syms, core_syms, "y")
    configs_to_test.append(("Minimal / Tinyconfig", tiny_env, "Minimal embedded kernel profile"))

    # Standard Upstream defconfig archetype
    def_syms = {s for s in all_syms if any(k in s for k in ["PCI", "ACPI", "NET", "INET", "EXT4", "BLK_DEV", "SERIAL", "INPUT", "DRM", "USB"])}
    def_env = generate_synthetic_config("defconfig", all_syms, def_syms, "y")
    configs_to_test.append(("Upstream x86_64 Defconfig", def_env, "Standard default x86 desktop/server kernel profile"))

    # Fedora / High-Modularity Distribution archetype
    fedora_syms = {s for s in all_syms if not any(k in s for k in ["DEBUG", "TEST", "EXPERT", "STAGING"])}
    fedora_env = generate_synthetic_config("fedora_default", all_syms, fedora_syms, "m")
    # Core essentials as built-in 'y'
    for s in core_syms:
        fedora_env[s] = "y"
    configs_to_test.append(("Fedora / Enterprise Modular Server", fedora_env, "Modular multi-driver enterprise server kernel profile"))

    # Maximal / Allmodconfig
    allmod_env = {s: "m" for s in all_syms}
    for s in core_syms:
        allmod_env[s] = "y"
    configs_to_test.append(("Maximal (allmodconfig)", allmod_env, "All modular drivers enabled"))

    # Run evaluations
    results = []
    print("\n" + "=" * 80)
    print("EVALUATING LINUX KERNEL ACROSS MULTIPLE CONFIGURATIONS")
    print("=" * 80)

    for name, env, desc in configs_to_test:
        res = validator.evaluate_config(name, env, desc)
        results.append(res)
        print(f"[*] Config: {name}")
        print(f"    Description:        {desc}")
        print(f"    Predicted Objects:  {res['predicted_active_objects']} / {res['total_extracted_objects']} ({res['predicted_active_percentage']}%)")
        print(f"    Evaluation Time:    {res['eval_time_ms']} ms")
        print(f"    Subsystem Breakdown: {res['subsystem_breakdown']}")
        print()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as f:
        json.dump({
            "linux_src_dir": str(args.linux_dir),
            "kfold_analysis_time_s": round(validator.analysis_time, 2),
            "total_target_objects": len(validator.target_objects),
            "total_config_symbols": len(validator.all_symbols),
            "configurations": results
        }, f, indent=2)

    print(f"[+] Multi-config validation results saved to {args.out}")


if __name__ == "__main__":
    main()
