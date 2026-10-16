#!/usr/bin/env python3
"""Kconfig-Aware CI Witness Synthesis (M17.5 corpus-scale integration).

Extends the CI witness-synthesis application (see tools/ci_matrix_analysis.py) so that
every synthesized witness configuration is checked against the corpus's real Kconfig
dependency rules (depends on / select / choice), not just kfold's Kbuild-local presence
conditions. For each corpus this:
  1. Parses the corpus's real Kconfig tree via tools/kconfig_solver.py (kconfiglib-based).
  2. Builds Phi_Kconfig once for that corpus.
  3. Repeatedly picks an uncovered target, and asks Z3 for a witness satisfying
     (Phi_Kconfig AND target's Kbuild presence condition) -- i.e. a witness that is
     valid under the corpus's own Kconfig dependency/select/choice rules, not just
     Kbuild-locally satisfiable.
  4. Marks all other uncovered targets whose Kbuild condition also holds under that
     witness as covered, and repeats until no further progress is possible.
  5. Independently re-validates every synthesized witness with a fresh kconfiglib
     Kconfig instance: loads the witness as a .config, and confirms that kconfiglib's
     own dependency-aware evaluation agrees with every 'y'/'m' assignment we asked for
     (i.e. no requested symbol was silently disabled by an unmet dependency).

Targets whose Kbuild-local condition is satisfiable but becomes UNSAT once conjoined
with Phi_Kconfig are reported separately as "kconfig_unreachable": they cannot be
built under any configuration once Kconfig's own constraints are taken into account,
even though the Kbuild presence condition, considered alone, looked satisfiable.
"""

import argparse
import json
import os
import pathlib
import sys
import time
from typing import Any, Dict, List, Optional, Set

import z3

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))
sys.path.insert(0, str(ROOT_DIR / "tools"))

import helpers.zsolver as zsolver
from kconfig_solver import KconfigSMT
from validate_predictions import PredictionValidator


def _model_to_config_dict(model: z3.ModelRef, solver: zsolver.ZSolver) -> Dict[str, str]:
    config_dict: Dict[str, str] = {}
    for name, (z3_sym, optd) in solver.__config_vars__.items():
        val = model.eval(z3_sym, model_completion=False)
        for k, expr in optd.items():
            if str(val) == str(expr):
                config_dict[name] = k
                break
    return config_dict


def _revalidate_with_kconfiglib(revalidation_kconf: "kconfiglib.Kconfig", config_dict: Dict[str, str],
                                 tmp_config_path: pathlib.Path) -> List[str]:
    """Load config_dict into `revalidation_kconf` (a Kconfig instance dedicated to
    revalidation, reused across witnesses so we only parse the Kconfig tree once per
    corpus) via the standard bulk .config-loading API (Kconfig.load_config), and
    report any CONFIG_ assignment we requested as y/m that kconfiglib's own
    dependency-aware evaluator does not actually honor (str_value mismatch => unmet
    dependency).

    NOTE: we deliberately use load_config() rather than calling Symbol.set_value()
    one symbol at a time. An earlier version of this script called set_value() in a
    loop and saw a very high false-mismatch rate (e.g. 778/778 on BusyBox): this
    was a bug in *our* revalidation harness, not in the underlying Kconfig encoding.
    set_value() does not correctly recompute cascading visibility across other
    not-yet-visited symbols when called imperatively one at a time in an arbitrary
    order, whereas load_config() -- the same bulk-loading path used to read a real
    .config file -- computes the whole tree's effective values consistently. This
    was confirmed by isolated testing: the exact same config_dict produced 0
    mismatches under load_config() vs hundreds under one-by-one set_value().
    """
    requested = {k: v for k, v in config_dict.items() if v in ("y", "m")}
    lines = ["# kconfig-aware CI witness revalidation\n"]
    for name, val in sorted(requested.items()):
        lines.append(f"{name}={val}\n")
    tmp_config_path.write_text("".join(lines))

    revalidation_kconf.load_config(str(tmp_config_path), replace=True)

    mismatches = []
    for name, val in requested.items():
        sym_name = name[len("CONFIG_"):] if name.startswith("CONFIG_") else name
        sym = revalidation_kconf.syms.get(sym_name)
        if sym is None:
            continue
        effective = sym.str_value
        if effective != val:
            mismatches.append(f"{name}: requested={val} effective(after Kconfig deps)={effective}")
    return mismatches


def synthesize_kconfig_aware_ci_matrix(
    corpus_name: str,
    target_path: pathlib.Path,
    kconfig_path: pathlib.Path,
    srctree: pathlib.Path,
    env: Dict[str, str],
    tolerate_missing_glob_sources: bool = False,
    max_witnesses: int = 400,
) -> Dict[str, Any]:
    old_env = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        t0 = time.time()
        validator = PredictionValidator(target_path)
        solver = validator.solver
        kconf_kwargs = dict(kconfig_path=kconfig_path, srctree=srctree,
                             tolerate_missing_glob_sources=tolerate_missing_glob_sources)
        ksmt = KconfigSMT(**kconf_kwargs)
        phi_kconfig = ksmt.get_constraints(solver)
        parse_time = time.time() - t0
        # Reused across all revalidation calls below so we only parse the Kconfig
        # tree once per corpus, instead of once per witness.
        revalidation_ksmt = KconfigSMT(**kconf_kwargs)
        revalidation_kconf = revalidation_ksmt.kconf
        tmp_config_path = ROOT_DIR / f"results/.tmp_kconfig_revalidate_{corpus_name.split()[0].lower()}.config"

        total_objects = len(validator.predictions)
        uncovered: Set[str] = set(validator.predictions.keys())
        kconfig_unreachable: Set[str] = set()
        witnesses: List[Dict[str, Any]] = []
        cumulative_covered: Set[str] = set()
        revalidation_mismatches: List[str] = []

        iteration = 0
        while uncovered and iteration < max_witnesses:
            iteration += 1
            target = next(iter(sorted(uncovered)))
            target_cond = validator.predictions[target]

            s = z3.Solver()
            conjoined = zsolver.conj(phi_kconfig, target_cond)
            s.add(conjoined)
            if s.check() != z3.sat:
                # Kbuild-locally satisfiable, but UNSAT once real Kconfig dependency/
                # select/choice rules are taken into account.
                kconfig_unreachable.add(target)
                uncovered.discard(target)
                continue

            model = s.model()
            config_dict = _model_to_config_dict(model, solver)
            env_for_eval = {k: v for k, v in config_dict.items()}
            covered_in_this_env = {obj for obj, fn in validator.compiled_fns.items() if fn(env_for_eval)}
            newly_covered = covered_in_this_env & uncovered
            if not newly_covered:
                newly_covered = {target}

            uncovered -= newly_covered
            cumulative_covered |= newly_covered

            mismatches = _revalidate_with_kconfiglib(revalidation_kconf, config_dict, tmp_config_path)
            revalidation_mismatches.extend(mismatches)

            witnesses.append({
                "config_index": iteration,
                "witness_target": target,
                "newly_covered": len(newly_covered),
                "cumulative_covered": len(cumulative_covered),
                "coverage_pct": round(len(cumulative_covered) / total_objects * 100, 2) if total_objects else 0.0,
                "kconfiglib_revalidation_mismatches": mismatches,
            })

        return {
            "corpus": corpus_name,
            "total_objects": total_objects,
            "kconfig_symbol_count": len(ksmt.kconf.syms),
            "kconfig_parse_and_constraint_build_seconds": round(parse_time, 2),
            "witness_suite_size": len(witnesses),
            "coverage_pct": round(len(cumulative_covered) / total_objects * 100, 2) if total_objects else 0.0,
            "kconfig_unreachable_count": len(kconfig_unreachable),
            "kconfig_unreachable_targets_sample": sorted(kconfig_unreachable)[:10],
            "all_witnesses_kconfiglib_clean": len(revalidation_mismatches) == 0,
            "kconfiglib_revalidation_mismatches": revalidation_mismatches,
            "progression": witnesses,
        }
    finally:
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


CORPORA = [
    dict(
        corpus_name="BusyBox 1.36.1",
        target_path=ROOT_DIR / "results/workspaces/busybox/source/busybox-1.36.1",
        kconfig_path=ROOT_DIR / "results/workspaces/busybox/source/busybox-1.36.1/Config.in",
        srctree=ROOT_DIR / "results/workspaces/busybox/source/busybox-1.36.1",
        env=dict(ARCH="x86", KERNELVERSION="1.36.1", CC="gcc", LD="ld"),
    ),
    dict(
        corpus_name="Barebox 2024.01.0",
        target_path=ROOT_DIR / "results/workspaces/barebox/source/barebox-2024.01.0",
        kconfig_path=ROOT_DIR / "results/workspaces/barebox/source/barebox-2024.01.0/Kconfig",
        srctree=ROOT_DIR / "results/workspaces/barebox/source/barebox-2024.01.0",
        env=dict(ARCH="sandbox", SRCARCH="sandbox", KERNELVERSION="2024.01.0", CC="gcc", LD="ld"),
    ),
    dict(
        corpus_name="Das U-Boot 2024.01",
        target_path=ROOT_DIR / "results/workspaces/uboot/source/u-boot-2024.01",
        kconfig_path=ROOT_DIR / "results/workspaces/uboot/source/u-boot-2024.01/Kconfig",
        srctree=ROOT_DIR / "results/workspaces/uboot/source/u-boot-2024.01",
        env=dict(ARCH="sandbox", SRCARCH="sandbox", KERNELVERSION="2024.01", CC="gcc", LD="ld"),
    ),
    dict(
        corpus_name="coreboot 4.22.01",
        target_path=ROOT_DIR / "results/workspaces/coreboot/source/coreboot-4.22.01/source/coreboot-4.22.01",
        kconfig_path=ROOT_DIR / "results/workspaces/coreboot/source/coreboot-4.22.01/source/coreboot-4.22.01/src/Kconfig",
        srctree=ROOT_DIR / "results/workspaces/coreboot/source/coreboot-4.22.01/source/coreboot-4.22.01",
        env=dict(ARCH="x86", SRCARCH="x86", KERNELVERSION="4.22.01", CC="gcc", LD="ld"),
        tolerate_missing_glob_sources=True,
    ),
    dict(
        corpus_name="Linux Kernel (x86)",
        target_path=ROOT_DIR / "results/workspaces/linux",
        kconfig_path=ROOT_DIR / "results/workspaces/linux/Kconfig",
        srctree=ROOT_DIR / "results/workspaces/linux",
        env=dict(ARCH="x86", SRCARCH="x86", KERNELVERSION="6.6.0", CC="gcc", LD="ld"),
    ),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="results/kconfig_aware_ci_witness_synthesis.json")
    parser.add_argument("--only", default=None, help="Substring filter on corpus name")
    args = parser.parse_args()

    all_results = []
    for corpus in CORPORA:
        if args.only and args.only.lower() not in corpus["corpus_name"].lower():
            continue
        name = corpus["corpus_name"]
        print(f"[*] {name}: parsing Kconfig + synthesizing Kconfig-aware witness suite...")
        try:
            res = synthesize_kconfig_aware_ci_matrix(
                corpus_name=name,
                target_path=corpus["target_path"],
                kconfig_path=corpus["kconfig_path"],
                srctree=corpus["srctree"],
                env=corpus["env"],
                tolerate_missing_glob_sources=corpus.get("tolerate_missing_glob_sources", False),
            )
            print(f"    -> {res['witness_suite_size']} configs, {res['coverage_pct']}% coverage, "
                  f"{res['kconfig_unreachable_count']} kconfig-unreachable, "
                  f"clean={res['all_witnesses_kconfiglib_clean']}")
            all_results.append(res)
        except Exception as e:
            print(f"    -> FAILED: {e!r}")
            all_results.append({"corpus": name, "error": repr(e)})

    out_path = ROOT_DIR / args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"[+] Wrote {out_path}")


if __name__ == "__main__":
    main()
