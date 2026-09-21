#!/usr/bin/env python3
"""Configuration Complexity & Feature Interaction Analysis for Kbuild.

Analyzes AST depth, node size, interaction degree (number of distinct CONFIG_* variables),
and identifies configuration hotspots across projects.
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


def get_ast_metrics(e):
    if not isinstance(e, z3.ExprRef):
        return {"depth": 1, "nodes": 1, "symbols": set()}
    
    symbols = set()
    if z3.is_const(e) and e.decl().kind() == z3.Z3_OP_UNINTERPRETED:
        symbols.add(str(e.decl().name()))
        return {"depth": 1, "nodes": 1, "symbols": symbols}
    
    depths = []
    total_nodes = 1
    for child in e.children():
        c_met = get_ast_metrics(child)
        depths.append(c_met["depth"])
        total_nodes += c_met["nodes"]
        symbols.update(c_met["symbols"])
    
    max_depth = 1 + (max(depths) if depths else 0)
    return {"depth": max_depth, "nodes": total_nodes, "symbols": symbols}


def analyze_complexity(corpus_name, root_dir):
    root_path = pathlib.Path(root_dir).resolve()
    print(f"\nAnalyzing Complexity & Interactions in {corpus_name} ({root_path})")

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

    object_metrics = []
    interaction_degree_counts = collections.Counter()
    depth_counts = collections.Counter()

    for obj, cond in target_objects.items():
        m = get_ast_metrics(cond)
        k = len(m["symbols"])
        depth = m["depth"]
        nodes = m["nodes"]
        interaction_degree_counts[k] += 1
        depth_counts[depth] += 1
        object_metrics.append({
            "target": obj,
            "degree_k": k,
            "depth": depth,
            "nodes": nodes,
            "symbols": sorted(list(m["symbols"])),
        })

    object_metrics.sort(key=lambda x: (x["degree_k"], x["depth"], x["nodes"]), reverse=True)

    degrees = [m["degree_k"] for m in object_metrics]
    depths = [m["depth"] for m in object_metrics]
    avg_k = sum(degrees) / max(1, len(degrees))
    max_k = max(degrees) if degrees else 0
    avg_depth = sum(depths) / max(1, len(depths))
    max_depth = max(depths) if depths else 0

    return {
        "corpus": corpus_name,
        "total_targets": len(target_objects),
        "avg_interaction_degree_k": round(avg_k, 2),
        "max_interaction_degree_k": max_k,
        "avg_ast_depth": round(avg_depth, 2),
        "max_ast_depth": max_depth,
        "interaction_distribution": dict(sorted(interaction_degree_counts.items())),
        "top_complex_targets": object_metrics[:10],
    }


def main():
    corpora = [
        ("BusyBox", "results/workspaces/busybox/source/busybox-1.36.1"),
        ("Barebox", "results/workspaces/barebox/source/barebox-2024.01.0"),
        ("Das U-Boot", "results/workspaces/uboot/source/u-boot-2024.01"),
    ]

    results = []
    for name, path in corpora:
        if os.path.exists(path):
            res = analyze_complexity(name, path)
            results.append(res)

    print("\n\n" + "="*80)
    print("FEATURE INTERACTION & COMPLEXITY REPORT")
    print("="*80)
    print(json.dumps(results, indent=2))

    with open("results/feature_interactions_report.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
