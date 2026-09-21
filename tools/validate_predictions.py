#!/usr/bin/env python3
"""Shared witness generation and build validation tool for skbuild predictions.

Given an skbuild analysis result or target codebase:
1. Extracts predicted object files and their Z3 path conditions.
2. Uses Z3 to generate concrete witness configurations (both positive and negative)
   using greedy set-cover to produce a minimal, sufficient build matrix.
3. Materializes concrete .config files for each witness.
4. Optionally executes real builds in the target workspace and validates predicted
   vs. actual built objects (computing TP, FP, FN, TN and categorizing discrepancies).
"""

import argparse
import dataclasses
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import z3

# Add src to path
ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

from alg import Run
from analysis import Analysis
import helpers.vcommon as CM
import helpers.zsolver as zsolver
import settings


@dataclasses.dataclass
class Witness:
    name: str
    config: Dict[str, str]  # var_name -> 'y' / 'm' / 'undef'
    covered_positive: Set[str]  # objects predicted present
    covered_negative: Set[str]  # objects predicted absent
    kind: str = "positive"  # "positive", "negative", or "joint"


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


class PredictionValidator:
    def __init__(self, target_path: pathlib.Path):
        target_path = target_path.resolve()
        if target_path.is_dir() and (target_path / settings.RESULT_SINFO).is_file():
            self.analysis = Analysis(target_path)
        else:
            res_dir = Run(target_path).go()
            self.analysis = Analysis(res_dir)

        self.mysettings = self.analysis.mysettings
        self.solver = zsolver.ZSolver(self.mysettings)
        self.cOptTyp, self.cOptD = self.solver.get_typ_info(None)
        self.all_vars = sorted(list(self.solver.__config_vars__.keys()))
        self.predictions, self.compiled_fns = self._extract_predictions()

    def _extract_predictions(self) -> Tuple[Dict[str, z3.ExprRef], Dict[str, Callable]]:
        target_objects: Dict[str, z3.ExprRef] = {}
        for kbuild in self.analysis.kbuilds:
            state = kbuild.state
            vals_d = state.vals_d
            for v in state.target_files:
                if v.name in self.mysettings.target_vars:
                    continue
                for word, wcond in v.valconds.items():
                    if not word.endswith(".o"):
                        continue
                    for f, cond in self.analysis.expand(word, wcond, vals_d):
                        rel = (kbuild.makefile.parent / f).relative_to(self.analysis.main_dir)
                        target_objects[str(rel)] = cond

        compiled = {obj: compile_expr(cond) for obj, cond in target_objects.items()}
        return target_objects, compiled

    def solve_witness(self, cond: z3.ExprRef) -> Optional[Dict[str, str]]:
        """Solve for a concrete witness dictionary satisfying cond."""
        s = z3.Solver()
        s.add(cond)
        if s.check() != z3.sat:
            return None
        m = s.model()
        witness = {var_name: "undef" for var_name in self.all_vars}
        for decl in m.decls():
            name = decl.name()
            val = str(m[decl])
            if val in self.cOptD:
                witness[name] = val
        return witness

    def generate_witnesses(
        self,
        strategy: str = "compact",
        include_negative: bool = True,
        max_witnesses: Optional[int] = None,
    ) -> List[Witness]:
        """Generate a minimal set of concrete witness configurations covering all predictions."""
        # 1. Collect unique satisfiable conditions
        unique_conds: Dict[str, z3.ExprRef] = {}
        for obj, cond in self.predictions.items():
            cond_str = str(cond)
            if cond_str not in unique_conds:
                unique_conds[cond_str] = cond

        candidate_witnesses: List[Dict[str, str]] = []
        for cond in unique_conds.values():
            w = self.solve_witness(cond)
            if w is not None:
                candidate_witnesses.append(w)

        # Precompute coverage
        witness_coverage: List[Tuple[Dict[str, str], Set[str], Set[str]]] = []
        all_objs = set(self.predictions.keys())
        for w in candidate_witnesses:
            pos = {obj for obj, fn in self.compiled_fns.items() if fn(w)}
            neg = all_objs - pos
            witness_coverage.append((w, pos, neg))

        selected: List[Witness] = []
        uncovered_pos = set(self.predictions.keys())

        # Greedy set cover for positive coverage
        w_idx = 0
        while uncovered_pos:
            best_idx = -1
            best_gain: Set[str] = set()
            for idx, (w, pos, neg) in enumerate(witness_coverage):
                gain = pos & uncovered_pos
                if len(gain) > len(best_gain):
                    best_gain = gain
                    best_idx = idx
            if not best_gain:
                break
            w, pos, neg = witness_coverage[best_idx]
            w_idx += 1
            selected.append(
                Witness(
                    name=f"witness_pos_{w_idx:03d}",
                    config=w,
                    covered_positive=pos,
                    covered_negative=neg,
                    kind="positive",
                )
            )
            uncovered_pos -= best_gain
            if max_witnesses and len(selected) >= max_witnesses:
                break

        # Optionally add negative witnesses for files that were always present in positive witnesses
        if include_negative and (not max_witnesses or len(selected) < max_witnesses):
            covered_neg_all = set().union(*(w.covered_negative for w in selected)) if selected else set()
            uncovered_neg = all_objs - covered_neg_all
            neg_idx = 0
            for obj in list(uncovered_neg):
                if max_witnesses and len(selected) >= max_witnesses:
                    break
                cond = self.predictions[obj]
                neg_w = self.solve_witness(zsolver.neg(cond))
                if neg_w is not None:
                    pos = {o for o, fn in self.compiled_fns.items() if fn(neg_w)}
                    neg = all_objs - pos
                    neg_idx += 1
                    selected.append(
                        Witness(
                            name=f"witness_neg_{neg_idx:03d}",
                            config=neg_w,
                            covered_positive=pos,
                            covered_negative=neg,
                            kind="negative",
                        )
                    )
                    uncovered_neg -= neg

        return selected

    def materialize_kconfig(self, witness: Witness, config_path: pathlib.Path) -> None:
        """Write a concrete .config file from a witness assignment."""
        lines = [f"# Generated by skbuild PredictionValidator: {witness.name}"]
        for name, val in sorted(witness.config.items()):
            if not self.mysettings.is_copt(name):
                continue
            if val == "y":
                lines.append(f"{name}=y")
            elif val == "m":
                lines.append(f"{name}=m")
            else:
                lines.append(f"# {name} is not set")
        config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def run_build(
        self,
        witness: Witness,
        workspace_dir: pathlib.Path,
        build_cmd: str,
        clean_cmd: Optional[str] = None,
        config_filename: str = ".config",
    ) -> Tuple[int, Set[str], str]:
        """Materialize witness config, run real build, and collect built objects."""
        config_path = workspace_dir / config_filename
        self.materialize_kconfig(witness, config_path)

        if clean_cmd:
            subprocess.run(clean_cmd, shell=True, cwd=workspace_dir, capture_output=True)

        res = subprocess.run(
            build_cmd,
            shell=True,
            cwd=workspace_dir,
            text=True,
            capture_output=True,
        )

        built_objects = set()
        if res.returncode == 0:
            for p in workspace_dir.rglob("*.o"):
                if any(parent.name in self.mysettings.ignore_dirs for parent in p.parents):
                    continue
                if p.name in self.mysettings.ignore_files:
                    continue
                try:
                    rel = p.relative_to(workspace_dir)
                    built_objects.add(str(rel))
                except ValueError:
                    pass

        return res.returncode, built_objects, res.stderr + "\n" + res.stdout


def validate_predictions(
    target_path: pathlib.Path,
    workspace_dir: Optional[pathlib.Path] = None,
    build_cmd: Optional[str] = None,
    clean_cmd: Optional[str] = None,
    output_dir: Optional[pathlib.Path] = None,
    strategy: str = "compact",
    include_negative: bool = True,
    max_witnesses: Optional[int] = None,
) -> Dict[str, Any]:
    validator = PredictionValidator(target_path)
    witnesses = validator.generate_witnesses(
        strategy=strategy,
        include_negative=include_negative,
        max_witnesses=max_witnesses,
    )

    report: Dict[str, Any] = {
        "target": str(target_path),
        "total_predicted_objects": len(validator.predictions),
        "witness_count": len(witnesses),
        "witnesses": [],
    }

    if output_dir:
        output_dir = output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"Generated {len(witnesses)} witnesses covering {len(validator.predictions)} objects."
    )

    for w in witnesses:
        w_entry: Dict[str, Any] = {
            "name": w.name,
            "kind": w.kind,
            "predicted_present_count": len(w.covered_positive),
            "predicted_absent_count": len(w.covered_negative),
        }

        if output_dir:
            config_file = output_dir / f"{w.name}.config"
            validator.materialize_kconfig(w, config_file)
            w_entry["config_file"] = str(config_file)

        if workspace_dir and build_cmd:
            ret, built_objects, log = validator.run_build(
                w, workspace_dir, build_cmd, clean_cmd
            )
            w_entry["exit_code"] = ret
            w_entry["build_status"] = "success" if ret == 0 else "build-failed"

            if ret == 0:
                tp = w.covered_positive & built_objects
                fp = w.covered_positive - built_objects
                fn = built_objects - w.covered_positive
                tn = w.covered_negative - built_objects

                w_entry["true_positives"] = len(tp)
                w_entry["false_positives"] = len(fp)
                w_entry["false_negatives"] = len(fn)
                w_entry["true_negatives"] = len(tn)
                w_entry["fp_details"] = sorted(list(fp))
                w_entry["fn_details"] = sorted(list(fn))

        report["witnesses"].append(w_entry)

    if output_dir:
        (output_dir / "validation_report.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )

    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=pathlib.Path, help="Target codebase or analysis dir")
    parser.add_argument("--workspace", type=pathlib.Path, help="Target build workspace directory")
    parser.add_argument("--build-cmd", type=str, help="Shell command to run real build")
    parser.add_argument("--clean-cmd", type=str, help="Shell command to clean workspace")
    parser.add_argument("--output-dir", type=pathlib.Path, help="Directory to save configs and report")
    parser.add_argument(
        "--strategy",
        choices=["compact", "per-condition"],
        default="compact",
        help="Witness generation strategy",
    )
    parser.add_argument(
        "--no-negative",
        action="store_true",
        help="Skip negative witness generation",
    )
    parser.add_argument(
        "--max-witnesses",
        type=int,
        default=None,
        help="Maximum number of witnesses to evaluate",
    )
    args = parser.parse_args()

    report = validate_predictions(
        target_path=args.target,
        workspace_dir=args.workspace,
        build_cmd=args.build_cmd,
        clean_cmd=args.clean_cmd,
        output_dir=args.output_dir,
        strategy=args.strategy,
        include_negative=not args.no_negative,
        max_witnesses=args.max_witnesses,
    )

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
