#!/usr/bin/env python3
"""Adversarial Synthetic Benchmark Suite for kfold (M11.3).

Generates and benchmarks adversarial synthetic Makefiles:
1. Sequential Independent Branches (N in 1..30)
2. Deeply Nested Branches (D in 1..20)
3. Heavy Guarded Variable Overwrites (K in 1..25)
4. Dynamic Variable Name Expansion Combinatorics

Measures analysis time, peak RSS, number of guarded alternatives, and Z3 formula AST size.
"""

import json
import os
import pathlib
import sys
import tempfile
import time
from typing import Dict, List, Tuple

import z3

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

from alg import Run
import settings


def generate_sequential_branches(n: int) -> str:
    """Generate N sequential conditional blocks."""
    lines = ["# Synthetic N sequential branches", "obj-y := base.o"]
    for i in range(1, n + 1):
        lines.append(f"ifeq ($(CONFIG_OPT_{i}),y)")
        lines.append(f"  obj-$(CONFIG_FLAG_{i}) += opt_{i}.o")
        lines.append(f"  obj-y += seq_{i}.o")
        lines.append("endif")
    return "\n".join(lines) + "\n"


def generate_nested_branches(depth: int) -> str:
    """Generate deeply nested conditional blocks."""
    lines = ["# Synthetic nested branches", "obj-y := root.o"]
    indent = ""
    for d in range(1, depth + 1):
        lines.append(f"{indent}ifeq ($(CONFIG_LEVEL_{d}),y)")
        indent += "  "
        lines.append(f"{indent}obj-y += nest_{d}.o")
    for d in range(depth, 0, -1):
        indent = indent[:-2]
        lines.append(f"{indent}endif")
    return "\n".join(lines) + "\n"


def generate_guarded_overwrites(k: int) -> str:
    """Generate chained guarded overwrites of the same target variable."""
    lines = ["# Synthetic guarded overwrites", "obj-y := init.o"]
    for i in range(1, k + 1):
        lines.append(f"obj-$(CONFIG_OVERWRITE_{i}) := ovr_{i}.o")
        lines.append(f"obj-$(CONFIG_APPEND_{i}) += app_{i}.o")
    return "\n".join(lines) + "\n"


def benchmark_snippet(name: str, content: str) -> Dict[str, any]:
    """Run kfold on a synthetic Makefile snippet and measure AST sizes and timings."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = pathlib.Path(tmpdir)
        mk_path = tmp_path / "Makefile"
        mk_path.write_text(content)
        ini_path = tmp_path / "skbuild.ini"
        ini_path.write_text("[COMMON]\nuse_tristate = yes\ntop_dirs = .\n")

        t0 = time.time()
        runner = Run(tmp_path)
        res_dir = runner.go()
        elapsed = time.time() - t0

        kbuilds = getattr(runner, "all_kbuilds", getattr(runner, "kbuilds", []))
        total_targets = 0
        total_ast_nodes = 0
        max_ast_depth = 0

        for kb in kbuilds:
            for v in kb.state.target_files:
                for word, cond in v.valconds.items():
                    if isinstance(word, str) and word.endswith(".o"):
                        total_targets += 1
                        if isinstance(cond, z3.ExprRef):
                            # Count AST nodes
                            nodes = count_ast_nodes(cond)
                            total_ast_nodes += nodes
                            max_ast_depth = max(max_ast_depth, get_ast_depth(cond))

        return {
            "benchmark": name,
            "time_ms": round(elapsed * 1000, 2),
            "target_objects": total_targets,
            "total_ast_nodes": total_ast_nodes,
            "max_ast_depth": max_ast_depth,
        }


def count_ast_nodes(expr: z3.ExprRef) -> int:
    """Recursively count nodes in Z3 AST."""
    count = 1
    for child in expr.children():
        count += count_ast_nodes(child)
    return count


def get_ast_depth(expr: z3.ExprRef) -> int:
    """Recursively compute max depth in Z3 AST."""
    if not expr.children():
        return 1
    return 1 + max(get_ast_depth(c) for c in expr.children())


def main():
    print("[*] Running Adversarial Synthetic Benchmarks (M11.3)")
    benchmarks = []

    # 1. Sequential Branches sweep (Linux max is 21)
    for n in [5, 10, 15, 20, 25]:
        content = generate_sequential_branches(n)
        res = benchmark_snippet(f"Sequential-Branches-N{n}", content)
        benchmarks.append(res)
        print(f"  [+] Sequential N={n:2d}: {res['time_ms']:6.2f} ms, {res['target_objects']:2d} targets, AST Depth: {res['max_ast_depth']:2d}")

    # 2. Nested Branches sweep (Linux max depth is 8)
    for d in [2, 4, 6, 8, 10, 12]:
        content = generate_nested_branches(d)
        res = benchmark_snippet(f"Nested-Branches-D{d}", content)
        benchmarks.append(res)
        print(f"  [+] Nested Depth D={d:2d}: {res['time_ms']:6.2f} ms, {res['target_objects']:2d} targets, AST Depth: {res['max_ast_depth']:2d}")

    # 3. Guarded Overwrites sweep
    for k in [2, 4, 6, 8, 10, 12]:
        content = generate_guarded_overwrites(k)
        res = benchmark_snippet(f"Guarded-Overwrites-K{k}", content)
        benchmarks.append(res)
        print(f"  [+] Overwrites K={k:2d}: {res['time_ms']:6.2f} ms, {res['target_objects']:2d} targets, AST Nodes: {res['total_ast_nodes']:3d}")

    out_file = ROOT_DIR / "results" / "adversarial_benchmarks.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w") as f:
        json.dump(benchmarks, f, indent=2)

    print(f"[+] Adversarial benchmark results saved to {out_file}")


if __name__ == "__main__":
    main()
