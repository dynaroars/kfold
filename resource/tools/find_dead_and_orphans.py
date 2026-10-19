#!/usr/bin/env python3
"""Dead Code and Orphan Source File Detector for skbuild.

Scans a target codebase for:
1. Unreachable Kbuild target objects (presence condition is provably False/unsat).
2. Orphan source files (.c, .S) on disk that are never referenced in any Kbuild file.
"""

import argparse
import json
import pathlib
import sys
from typing import Any, Dict, List, Set
import z3

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))
sys.path.insert(0, str(ROOT_DIR / "tools"))

from validate_predictions import PredictionValidator


def detect_dead_and_orphans(target_path: pathlib.Path, full_src_dir: pathlib.Path = None) -> Dict[str, Any]:
    target_path = target_path.resolve()
    validator = PredictionValidator(target_path)
    
    # 1. Detect provably unsatisfiable targets
    unsat_objects: List[Dict[str, str]] = []
    satisfiable_objects: Set[str] = set()
    
    for obj, cond in validator.predictions.items():
        if z3.is_false(cond):
            unsat_objects.append({"object": obj, "reason": "Tautologically False"})
            continue
        solver = z3.Solver()
        solver.add(cond)
        if solver.check() != z3.sat:
            unsat_objects.append({"object": obj, "reason": "SMT Unsatisfiable"})
        else:
            satisfiable_objects.add(obj)

    # 2. Detect orphan source files on disk
    src_dir = full_src_dir.resolve() if full_src_dir else target_path
    disk_c_files: Set[str] = set()
    for ext in ["*.c", "*.S", "*.s"]:
        for p in src_dir.rglob(ext):
            if any(parent.name in validator.mysettings.ignore_dirs for parent in p.parents):
                continue
            if p.name in validator.mysettings.ignore_files:
                continue
            try:
                rel = str(p.relative_to(src_dir))
                disk_c_files.add(rel)
            except ValueError:
                pass

    # Normalize predicted object basenames/stems
    predicted_stems = {pathlib.Path(obj).stem for obj in validator.predictions.keys()}
    orphan_files = []
    for f in sorted(disk_c_files):
        stem = pathlib.Path(f).stem
        if stem not in predicted_stems:
            orphan_files.append(f)

    return {
        "target": str(target_path),
        "total_predicted_objects": len(validator.predictions),
        "satisfiable_objects": len(satisfiable_objects),
        "dead_unsat_objects_count": len(unsat_objects),
        "dead_unsat_objects": unsat_objects,
        "disk_source_files_count": len(disk_c_files),
        "orphan_source_files_count": len(orphan_files),
        "orphan_source_files_sample": orphan_files[:25]
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("target", type=pathlib.Path)
    parser.add_argument("--src-dir", type=pathlib.Path, default=None)
    args = parser.parse_args()
    
    res = detect_dead_and_orphans(args.target, args.src_dir)
    print(json.dumps(res, indent=2))
