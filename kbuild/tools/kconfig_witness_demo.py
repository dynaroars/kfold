#!/usr/bin/env python3
"""Kconfig-Aware Buildable Witness Synthesis Case Study (M17.5).

Demonstrates that conjoining kfold's Kbuild-local presence conditions with
Kconfig propositional constraints (via tools/kconfig_solver.py) is necessary
to synthesize a *buildable* configuration witness, using a real Linux driver
(CONFIG_E1000, which `depends on PCI`) as a concrete example.

Requires a full Linux kernel source checkout at LINUX_SRCTREE (see
results/workspaces/linux for the checkout used to produce results/
kconfig_witness_synthesis.json).
"""

import argparse
import json
import os
import pathlib
import sys

import z3

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))
sys.path.insert(0, str(ROOT_DIR / "tools"))

import settings
import helpers.zsolver as zsolver
from kconfig_solver import KconfigSMT


def run(linux_srctree: pathlib.Path, target_symbol: str = "E1000"):
    os.environ.setdefault("ARCH", "x86")
    os.environ.setdefault("SRCARCH", "x86")
    os.environ.setdefault("KERNELVERSION", "6.6.0")
    os.environ.setdefault("CC", "gcc")
    os.environ.setdefault("LD", "ld")

    kconf_path = linux_srctree / "Kconfig"
    ksmt = KconfigSMT(kconf_path)
    mysettings = settings.Settings(linux_srctree)
    solver = zsolver.ZSolver(mysettings)
    phi_kconfig = ksmt.get_constraints(solver)

    target_name = f"CONFIG_{target_symbol}"
    target_sym, target_optd = solver.get_sort(target_name)
    dep_sym, dep_optd = solver.get_sort("CONFIG_PCI")

    target_cond = target_sym == target_optd["y"]
    if "m" in target_optd:
        target_cond = z3.Or(target_cond, target_sym == target_optd["m"])

    # 1. Kbuild-local-only "witness": the Kbuild presence condition for
    #    drivers/net/ethernet/intel/e1000/e1000.o is simply CONFIG_E1000 active;
    #    it says nothing about CONFIG_PCI, so a naive SAT model leaves it free.
    naive_solver = z3.Solver()
    naive_solver.add(target_cond)
    naive_sat = naive_solver.check() == z3.sat
    naive_model = naive_solver.model() if naive_sat else None
    naive_pci_constrained = (
        naive_model is not None and str(naive_model.eval(dep_sym, model_completion=False)) != str(dep_sym)
    )

    # 2. Kconfig-aware witness: conjoin Phi_Kconfig, which encodes `depends on PCI`.
    witness = ksmt.find_buildable_witness(target_cond, solver)

    result = {
        "target_symbol": target_name,
        "kconfig_dependency": "depends on PCI",
        "kconfig_symbol_count": len(ksmt.kconf.syms),
        "naive_kbuild_only": {
            "satisfiable": naive_sat,
            "pci_constrained_in_model": naive_pci_constrained,
        },
        "kconfig_aware_witness": {
            "buildable": witness is not None,
            f"{target_name}": witness.get(target_name) if witness else None,
            "CONFIG_PCI": witness.get("CONFIG_PCI") if witness else None,
            "total_symbols_assigned": len(witness) if witness else 0,
        },
    }
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("linux_srctree", type=str, help="Path to a full Linux kernel source checkout")
    parser.add_argument("--target", default="E1000", help="Kconfig symbol name (without CONFIG_ prefix)")
    parser.add_argument("--output", default="results/kconfig_witness_synthesis.json")
    args = parser.parse_args()

    res = run(pathlib.Path(args.linux_srctree).resolve(), args.target)
    print(json.dumps(res, indent=2))

    out_path = ROOT_DIR / args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(res, f, indent=2)
    print(f"[+] Wrote {out_path}")
