#!/usr/bin/env python3
"""Differential Ground-Truth Validation: kfold vs. GNU Make on Linux Kernel.

Evaluates kfold presence conditions against GNU Make expansion under supplied
normalized Linux .config files. It does not synthesize substitute profiles.

For each configuration and each of the 1,565 Makefiles, compares:
- kfold's symbolic condition evaluation (Predicted Active Targets)
- GNU Make's actual target evaluation (Ground Truth Active Targets)

Outputs full TP, FP, FN, TN, Precision, Recall, and discrepancy analysis.
"""

import argparse
import concurrent.futures
import json
import os
import pathlib
import re
import subprocess
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import z3

# Set up PYTHONPATH
ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))
sys.path.insert(0, str(ROOT_DIR))

from alg import Run
import helpers.vcommon as CM
import helpers.zsolver as zsolver
import settings
from tools.validate_linux_configs import parse_kconfig_file
from tools.kfold_targets import target_path


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
        # An option that is unset or "is not set" has kfold's value "undef".
        def eq(env):
            value = env.get(lhs_str, "")
            return (value if value not in ("", "n") else "undef") == rhs_str
        return eq
    return lambda env: False


def extract_gnu_make_objects(
    makefile_path: pathlib.Path,
    config_env: Dict[str, str],
    srctree: Optional[pathlib.Path] = None,
    defines: Optional[Dict[str, str]] = None,
) -> Set[str]:
    """Invoke GNU Make on a single Makefile/Kbuild file to get actual target objects."""
    try:
        content = makefile_path.read_text(errors="ignore")
    except Exception:
        return set()

    symbols = set(re.findall(r"CONFIG_[A-Za-z0-9_]+", content))
    cmd_vars = []
    for s in symbols:
        val = config_env.get(s, "")
        # "# CONFIG_X is not set" leaves the variable undefined in Kbuild.
        if val and val != "n":
            cmd_vars.append(f"{s}={val}")

    # Run as Kbuild does: from the source root, with src/obj naming the
    # Makefile's directory and the project's fixed definitions (SRCARCH, BITS).
    cwd = None
    if srctree is not None:
        cwd = str(srctree)
        rel = os.path.relpath(makefile_path.parent, srctree)
        cmd_vars += [f"src={rel}", f"obj={rel}", "srctree=."]
    for name, value in (defines or {}).items():
        cmd_vars.append(f"{name}={value}")

    wrapper = f"""
-include {makefile_path}
__kfold_objs__:
\t@echo '__OBJS__:' $(obj-y) $(obj-m) $(lib-y) $(lib-m) $(head-y) $(extra-y) $(core-y) $(drivers-y) $(net-y) $(libs-y)
"""
    try:
        res = subprocess.run(
            # Name the goal: otherwise the included Makefile's first rule
            # would become the default goal and nothing would be printed.
            ["make", "-f", "-"] + cmd_vars + ["__kfold_objs__"],
            input=wrapper, cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
        )
        objs = set()
        for line in res.stdout.splitlines():
            if line.startswith("__OBJS__:"):
                words = line[len("__OBJS__:") :].strip().split()
                for w in words:
                    w = w.strip("\"'")
                    if w.endswith(".o") or w.endswith(".a"):
                        objs.add(w)
        return objs
    except Exception:
        return set()


class LinuxDifferentialValidator:
    def __init__(self, linux_src_dir: pathlib.Path, use_tristate: bool = True):
        self.linux_src_dir = linux_src_dir.resolve()
        print(f"[*] Running kfold symbolic analysis on Linux tree: {self.linux_src_dir}")
        t0 = time.time()
        self.runner = Run(self.linux_src_dir, use_tristate=use_tristate)
        self.tmpdir = self.runner.go()
        self.analysis_time = time.time() - t0
        print(f"[+] kfold analysis completed in {self.analysis_time:.2f}s")

        self.kbuilds = getattr(self.runner, "all_kbuilds", getattr(self.runner, "kbuilds", []))
        self.main_dir = getattr(self.runner, "maindir", getattr(self.runner, "main_dir", self.linux_src_dir))
        self.mysettings = getattr(self.runner, "mysettings", None)

        # Precompile local expressions per Kbuild
        self.kb_target_fns = []
        self.all_symbols = set()
        self.total_target_count = 0
        valid_exts = (".o", ".a")

        # GNU Make evaluates each file on its own, so compare with each
        # Makefile's local (unrestricted) state rather than the instances
        # restricted by directory reachability.
        print("[*] Indexing target objects and AST conditions...")
        from kbuild import Kbuild
        unique = {}
        for kb in self.kbuilds:
            if kb.makefile not in unique:
                local = Kbuild(kb.makefile, self.mysettings)
                local.preprocess()
                local.symexe()
                unique[kb.makefile] = local
        for kb in unique.values():
            state = kb.state
            parent = kb.makefile.parent
            mf = kb.makefile
            local_targets = []

            for v in state.target_files:
                if self.mysettings and v.name in self.mysettings.target_vars:
                    continue
                for word, wcond in v.valconds.items():
                    if isinstance(word, str) and any(word.endswith(ext) for ext in valid_exts):
                        rel = target_path(word, v.name, parent, self.main_dir)
                        fn = compile_expr(wcond)
                        local_targets.append((word, rel, fn))
                        self.total_target_count += 1

            # Extract symbols from file content
            try:
                content = mf.read_text(errors="ignore")
                self.all_symbols.update(re.findall(r"CONFIG_[A-Za-z0-9_]+", content))
            except Exception:
                pass

            self.kb_target_fns.append((kb, local_targets))

        print(f"[+] Extracted {self.total_target_count} target objects across {len(self.all_symbols)} symbols from {len(self.kbuilds)} Kbuild files")

    def fixed_defines(self, config_env):
        """Settings defines with guarded values resolved under a .config."""
        d = dict(self.mysettings.defines) if self.mysettings else {}
        for name, entries in (getattr(self.mysettings, "define_guards", {}) or {}).items():
            for value, sym in entries:
                if config_env.get(sym) == "y":
                    d[name] = value
        return d

    def evaluate_ground_truth(
        self,
        config_name: str,
        config_env: Dict[str, str],
        description: str = "",
        max_workers: int = 16,
    ) -> Dict[str, Any]:
        """Compare kfold predictions vs GNU Make actual evaluation across all Makefiles."""
        print(f"\n[*] Evaluating ground truth for: {config_name}")
        t0 = time.time()

        global_kfold_active = set()
        global_gmake_active = set()
        global_all_targets = set()
        subsystem_tp = {}
        subsystem_fp = {}
        subsystem_fn = {}

        def process_kb(entry):
            kb, local_targets = entry
            mf = kb.makefile
            parent = mf.parent

            # 1. kfold predicted active
            k_active = set()
            all_local = set()
            for word, rel, fn in local_targets:
                all_local.add(rel)
                if fn(config_env):
                    k_active.add(rel)

            # 2. GNU Make actual active
            g_raw = extract_gnu_make_objects(mf, config_env, self.main_dir,
                                             self.fixed_defines(config_env))
            g_active = set()
            for word in g_raw:
                rel = target_path(word, "obj-y", parent, self.main_dir)
                if rel is not None:
                    g_active.add(rel)

            return (all_local, k_active, g_active)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            results = list(pool.map(process_kb, self.kb_target_fns))

        for all_local, k_active, g_active in results:
            global_all_targets.update(all_local)
            global_kfold_active.update(k_active)
            global_gmake_active.update(g_active)

        eval_time = time.time() - t0

        # Calculate metrics within the universe of targets
        relevant_gmake = global_gmake_active & global_all_targets
        tp = global_kfold_active & global_gmake_active
        fp = global_kfold_active - global_gmake_active
        fn = relevant_gmake - global_kfold_active
        tn = (global_all_targets - global_kfold_active) - global_gmake_active

        precision = (len(tp) / max(1, len(tp) + len(fp))) * 100.0
        recall = (len(tp) / max(1, len(tp) + len(fn))) * 100.0
        f1 = (2 * precision * recall / max(1e-6, precision + recall))
        accuracy = ((len(tp) + len(tn)) / max(1, len(global_all_targets))) * 100.0

        print(f"    Evaluation Time:     {eval_time:.2f}s")
        print(f"    Total Targets:       {len(global_all_targets)}")
        print(f"    kfold Active:        {len(global_kfold_active)}")
        print(f"    GNU Make Active:     {len(relevant_gmake)}")
        print(f"    True Positives (TP): {len(tp)}")
        print(f"    False Positives(FP): {len(fp)}")
        print(f"    False Negatives(FN): {len(fn)}")
        print(f"    True Negatives (TN): {len(tn)}")
        print(f"    Precision:           {precision:.2f}%")
        print(f"    Recall:              {recall:.2f}%")
        print(f"    F1-Score:            {f1:.2f}%")
        print(f"    Accuracy:            {accuracy:.2f}%")

        return {
            "config_name": config_name,
            "description": description,
            "eval_time_s": round(eval_time, 2),
            "total_targets": len(global_all_targets),
            "kfold_predicted_active": len(global_kfold_active),
            "gmake_ground_truth_active": len(relevant_gmake),
            "tp": len(tp),
            "fp": len(fp),
            "fn": len(fn),
            "tn": len(tn),
            "precision": round(precision, 2),
            "recall": round(recall, 2),
            "f1_score": round(f1, 2),
            "accuracy": round(accuracy, 2),
            "sample_fp": sorted(list(fp))[:10],
            "sample_fn": sorted(list(fn))[:10],
        }


def main():
    parser = argparse.ArgumentParser(description="Differential Ground-Truth Validation vs GNU Make")
    parser.add_argument("--linux-dir", type=pathlib.Path, default=pathlib.Path("tests/linux/linux_orig"))
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("results/linux_ground_truth_validation.json"))
    parser.add_argument("--config", type=pathlib.Path, action="append",
                        help="Normalized .config file; repeat for multiple profiles. Defaults to --linux-dir/.config.")
    args = parser.parse_args()

    validator = LinuxDifferentialValidator(args.linux_dir)
    config_paths = args.config or [args.linux_dir / ".config"]
    for path in config_paths:
        if not path.is_file():
            parser.error(f"configuration does not exist: {path}")

    results = []
    print("\n" + "=" * 80)
    print("RUNNING DIFFERENTIAL GROUND-TRUTH VALIDATION (kfold vs GNU Make)")
    print("=" * 80)

    for path in config_paths:
        env = parse_kconfig_file(path)
        res = validator.evaluate_ground_truth(path.parent.name, env, f"Normalized configuration from {path}")
        res["config_path"] = str(path)
        results.append(res)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as f:
        json.dump({
            "linux_src_dir": str(args.linux_dir),
            "kfold_analysis_time_s": round(validator.analysis_time, 2),
            "total_target_objects": validator.total_target_count,
            "total_config_symbols": len(validator.all_symbols),
            "configurations": results,
        }, f, indent=2)

    print(f"\n[+] Ground-truth validation results saved to {args.out}")


if __name__ == "__main__":
    main()
