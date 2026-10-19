#!/usr/bin/env python3
"""Check kfold's Kconfig model against scripts/kconfig on the Linux configs.

Usage: experiments/check_kconfig.py

kfold's Kconfig reasoning (``why`` explanations, ``config-for``) goes through
kconfiglib plus src/kconfig_compat.py. For each generated Linux .config, this
loads the .config into kconfiglib and compares every symbol's value with the
value scripts/kconfig wrote. It also checks that the .config satisfies the
Z3 encoding of Kconfig that ``config-for`` solves (tools/kconfig_solver.py),
symbol by symbol: the encoding over-approximates Kconfig, so a real .config
that violates it would mean config-for can call a buildable object
impossible. The toolchain probes that the kernel Makefile
exports to Kconfig (CC_VERSION_TEXT, PAHOLE, NM, ...) are set as the Makefile
sets them. Writes results/kconfig_check.json.
"""
import json
import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from subjects import CC, EVIDENCE, RESULTS, ROOT, SUBJECTS, analysis_dir  # noqa: E402

sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
import kconfiglib  # noqa: E402
import kconfig_compat  # noqa: E402
import z3  # noqa: E402
from cli import cache  # noqa: E402
from kconfig_solver import KconfigSMT, formula_vars  # noqa: E402


def smt_violations(tree, want):
    """Symbols whose clauses in KconfigSMT fail under the .config values."""
    solver = cache.load(tree, ROOT / "work" / "kfold-cache", check=False).solver()
    ksmt = KconfigSMT(tree / "Kconfig", srctree=tree)
    per_sym = [(sym.name, ksmt.symbol_clauses(sym, solver)) for sym in ksmt.kconf.unique_defined_syms]
    value = {}
    for name, (var, optd) in solver.__config_vars__.items():
        v = want.get(name[len("CONFIG_"):], "n")
        value[var.get_id()] = (var, optd.get(v, optd[solver.mysettings.zstate.undef_val]))
    bad = []
    for name, clauses in per_sym:
        if not clauses:
            continue
        c = z3.And(*clauses)
        pairs = [value[v.get_id()] for v in formula_vars(c) if v.get_id() in value]
        c = z3.simplify(z3.substitute(c, *pairs)) if pairs else z3.simplify(c)
        if z3.is_false(c) or (not z3.is_true(c) and z3.Solver().check(c) != z3.sat):
            bad.append(name)
    return bad


def values(path):
    d = {}
    for line in open(path):
        if line.startswith("CONFIG_"):
            k, v = line.rstrip("\n").split("=", 1)
            d[k[7:]] = v.strip('"')
        elif line.startswith("# CONFIG_") and line.endswith(" is not set\n"):
            d[line[9:-12]] = "n"
    return d


def main():
    tree = analysis_dir("linux")
    out = {}
    for config, cfg in SUBJECTS["linux"]["configs"].items():
        path = EVIDENCE / "configs" / "linux" / f"{config}.config"
        if not path.exists():
            continue
        os.environ.update(srctree=str(tree), ARCH=cfg["arch"], SRCARCH="x86", CC=CC, LD="ld",
                          NM="nm", OBJCOPY="objcopy", PAHOLE="pahole", HOSTCC="gcc",
                          KERNELVERSION=SUBJECTS["linux"]["version"],
                          RUSTC="rustc", BINDGEN="bindgen", PYTHON3="python3")
        os.environ.update(kconfig_compat.makefile_exports(tree))
        kc = kconfiglib.Kconfig(str(tree / "Kconfig"), warn=False)
        kc.load_config(str(path))
        want = values(path)
        bad = []
        for name, v in want.items():
            sym = kc.syms.get(name)
            if sym is None or not sym.nodes:
                continue
            got = sym.str_value
            if got != v and not (v == "n" and got in ("n", "")):
                bad.append({"symbol": name, "scripts_kconfig": v, "kconfiglib": got})
        smt = smt_violations(tree, want)
        out[config] = {"symbols_in_config": len(want), "defined_symbols": len(kc.unique_defined_syms),
                       "mismatches": bad, "smt_violations": smt}
        print(config, len(want), "symbols,", len(bad), "mismatches", bad[:5],
              len(smt), "SMT violations", smt[:10], flush=True)
    (RESULTS / "kconfig_check.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
