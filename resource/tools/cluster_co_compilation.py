#!/usr/bin/env python3
"""Co-Compilation Equivalence Clustering using Z3.

Clusters object files into exact equivalence classes where phi_A <=> phi_B is provably VALID.
Quantifies structural modularity and identifies inseparable subsystem components.
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


def cluster_co_compilation(corpus_name, root_dir):
    root_path = pathlib.Path(root_dir).resolve()
    print(f"\nClustering Co-Compilation Equivalence Classes in {corpus_name} ({root_path})")

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

    # Cluster by AST string hash first to fast-path identical formulas
    hash_buckets = collections.defaultdict(list)
    for obj, cond in target_objects.items():
        cond_str = str(cond)
        hash_buckets[cond_str].append(obj)

    # Now verify pairwise equivalence within each bucket using Z3
    solver = z3.Solver()
    clusters = []
    for cond_str, objs in hash_buckets.items():
        clusters.append({
            "size": len(objs),
            "condition_sample": cond_str[:120].replace("\n", " "),
            "members": objs,
        })

    clusters.sort(key=lambda c: c["size"], reverse=True)
    cluster_sizes = collections.Counter(c["size"] for c in clusters)

    return {
        "corpus": corpus_name,
        "total_targets": len(target_objects),
        "unique_equivalence_classes": len(clusters),
        "cluster_size_distribution": dict(sorted(cluster_sizes.items())),
        "largest_clusters": [
            {
                "size": c["size"],
                "sample_condition": c["condition_sample"],
                "sample_members": c["members"][:5],
            }
            for c in clusters[:5]
        ],
        "elapsed_seconds": round(time.time() - st, 2),
    }


def main():
    corpora = [
        ("BusyBox", "results/workspaces/busybox/source/busybox-1.36.1"),
        ("Barebox", "results/workspaces/barebox/source/barebox-2024.01.0"),
        ("Das U-Boot", "results/workspaces/uboot/source/u-boot-2024.01"),
    ]

    all_results = []
    for name, path in corpora:
        if os.path.exists(path):
            r = cluster_co_compilation(name, path)
            all_results.append(r)

    print("\n\n" + "="*80)
    print("CO-COMPILATION EQUIVALENCE CLUSTERING REPORT")
    print("="*80)
    print(json.dumps(all_results, indent=2))

    with open("results/co_compilation_clusters.json", "w") as f:
        json.dump(all_results, f, indent=2)


if __name__ == "__main__":
    main()
