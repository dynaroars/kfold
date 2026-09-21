#!/usr/bin/env python3
"""Sufficient CI Matrix Reduction Analyzer for skbuild.

Compares standard developer/CI configurations (defconfig, allnoconfig, allyesconfig)
against skbuild's SMT-derived greedy set-cover witness suite, measuring object coverage
and configuration suite size.
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

from validate_predictions import PredictionValidator, compile_expr


def analyze_ci_matrix(target_path: pathlib.Path, defconfig_path: pathlib.Path = None) -> Dict[str, Any]:
    validator = PredictionValidator(target_path)
    total_objects = len(validator.predictions)
    
    # 1. Compute Greedy Multi-Condition Joint SMT Witness Suite
    uncovered: Set[str] = set(validator.predictions.keys())
    witnesses: List[Dict[str, Any]] = []
    cumulative_covered: Set[str] = set()
    
    iteration = 0
    while uncovered and iteration < 50:
        iteration += 1
        solver = z3.Solver()
        joint_objs = []
        for obj in list(uncovered):
            cond = validator.predictions[obj]
            solver.push()
            solver.add(cond)
            if solver.check() == z3.sat:
                joint_objs.append(obj)
            else:
                solver.pop()
                
        if not joint_objs or solver.check() != z3.sat:
            break
            
        m = solver.model()
        env = {decl.name(): str(m[decl]) for decl in m.decls() if str(m[decl]) in validator.cOptD}
        covered_in_this_env = {obj for obj, fn in validator.compiled_fns.items() if fn(env)}
        newly_covered = covered_in_this_env & uncovered
        if not newly_covered:
            break
                
        uncovered -= newly_covered
        cumulative_covered |= newly_covered
        
        witnesses.append({
            "config_index": iteration,
            "config_name": f"smt_ci_config_{iteration:02d}",
            "newly_covered": len(newly_covered),
            "cumulative_covered": len(cumulative_covered),
            "coverage_pct": round(len(cumulative_covered) / total_objects * 100, 2)
        })
    
    # 2. Evaluate defconfig coverage if provided
    defconfig_covered = 0
    if defconfig_path and defconfig_path.is_file():
        defconfig_env = {}
        for line in defconfig_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or not line:
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                defconfig_env[k.strip()] = v.strip().strip('"')
                
        for obj, fn in validator.compiled_fns.items():
            if fn(defconfig_env):
                defconfig_covered += 1

    return {
        "target": str(target_path),
        "total_objects": total_objects,
        "skbuild_minimal_suite_size": len(witnesses),
        "skbuild_suite_coverage_pct": round(len(cumulative_covered) / total_objects * 100, 2) if total_objects else 0.0,
        "defconfig_covered": defconfig_covered,
        "defconfig_coverage_pct": round(defconfig_covered / total_objects * 100, 2) if total_objects else 0.0,
        "progression": witnesses
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("target", type=pathlib.Path)
    parser.add_argument("--defconfig", type=pathlib.Path, default=None)
    args = parser.parse_args()
    
    res = analyze_ci_matrix(args.target, args.defconfig)
    print(json.dumps(res, indent=2))
