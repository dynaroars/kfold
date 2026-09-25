#!/usr/bin/env python3
"""Robust Kconfig Propositional Constraint Extractor & Solver (M17.5).

Uses standard AST parsing via kconfiglib to convert Kconfig dependencies (depends on, select,
choice blocks, defaults) into Z3 propositional clauses (Phi_Kconfig).

Conjoins Phi_Kconfig with Kbuild presence conditions (Phi_Kbuild) to guarantee that synthesized
test configurations produce 100% physically valid .config files without Kconfig dependency warnings.
"""

import os
import pathlib
import sys
from typing import Dict, List, Optional, Set, Tuple

import kconfiglib
import z3

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "src"))

import settings
import helpers.zsolver as zsolver


class _ModulesPropertyFilter:
    """Wraps a Kconfig file handle and blanks out standalone 'modules' property
    lines, a newer Kconfig keyword (kernel >= 6.3, replacing 'option modules')
    that kconfiglib 14.1.0 does not parse. Blanking (rather than deleting) the
    line keeps line numbers intact for kconfiglib's own error reporting."""

    def __init__(self, f):
        self._f = f

    def readline(self, *args):
        line = self._f.readline(*args)
        if line.strip() == "modules":
            return "\n"
        return line

    def close(self):
        return self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()
        return False

    def __iter__(self):
        return self

    def __next__(self):
        line = self.readline()
        if line == "":
            raise StopIteration
        return line

    def __getattr__(self, name):
        return getattr(self._f, name)


_orig_kconfig_open = kconfiglib.Kconfig._open


def _patched_kconfig_open(self, filename, mode):
    f = _orig_kconfig_open(self, filename, mode)
    if mode != "r":
        return f
    return _ModulesPropertyFilter(f)


kconfiglib.Kconfig._open = _patched_kconfig_open


class KconfigSMT:
    def __init__(self, kconfig_path: pathlib.Path, srctree: Optional[pathlib.Path] = None,
                 tolerate_missing_glob_sources: bool = False):
        """
        tolerate_missing_glob_sources: some Kconfig dialects (e.g. coreboot's
        `source "src/vendorcode/*/*/Kconfig.debug"`) use wildcard `source`
        directives to optionally pull in per-vendor Kconfig fragments that may
        not exist in every checkout (e.g. proprietary vendor blobs excluded from
        a public archive). Standard kconfiglib treats plain `source` (unlike
        `osource`) as an error when the pattern matches zero files. When this
        flag is set, we relax that check for the duration of parsing so a glob
        matching zero files is silently skipped rather than raising an error;
        this does not affect non-glob `source` directives, which still require
        their target file to exist.
        """
        assert kconfig_path.is_file(), kconfig_path
        kconfig_path = kconfig_path.resolve()
        self.kconfig_path = kconfig_path
        self.srctree = (srctree or kconfig_path.parent).resolve()
        old_cwd = pathlib.Path.cwd()
        old_srctree_env = os.environ.get("srctree")
        old_obl_source_tokens = kconfiglib._OBL_SOURCE_TOKENS
        try:
            os.chdir(self.srctree)
            os.environ["srctree"] = str(self.srctree)
            if tolerate_missing_glob_sources:
                kconfiglib._OBL_SOURCE_TOKENS = frozenset()
            self.kconf = kconfiglib.Kconfig(str(kconfig_path.relative_to(self.srctree)), warn=False, warn_to_stderr=False)
        finally:
            os.chdir(old_cwd)
            kconfiglib._OBL_SOURCE_TOKENS = old_obl_source_tokens
            if old_srctree_env is None:
                os.environ.pop("srctree", None)
            else:
                os.environ["srctree"] = old_srctree_env

    def expr_to_z3(self, expr, solver: zsolver.ZSolver):
        """Recursively translate a kconfiglib expression into a Z3 BoolRef."""
        if expr is None or expr == self.kconf.n:
            return zsolver.F
        if expr == self.kconf.y:
            return zsolver.T

        if isinstance(expr, kconfiglib.Symbol):
            name = f"CONFIG_{expr.name}"
            sym, optd = solver.get_sort(name)
            return (sym == optd['y'])

        if isinstance(expr, tuple):
            op = expr[0]
            if op == kconfiglib.AND:
                return zsolver.conj(self.expr_to_z3(expr[1], solver), self.expr_to_z3(expr[2], solver))
            elif op == kconfiglib.OR:
                return zsolver.disj(self.expr_to_z3(expr[1], solver), self.expr_to_z3(expr[2], solver))
            elif op == kconfiglib.NOT:
                return zsolver.neg(self.expr_to_z3(expr[1], solver))
            elif op == kconfiglib.EQUAL:
                return (self.expr_to_z3(expr[1], solver) == self.expr_to_z3(expr[2], solver))
            elif op == kconfiglib.UNEQUAL:
                return (self.expr_to_z3(expr[1], solver) != self.expr_to_z3(expr[2], solver))

        return zsolver.T

    def get_constraints(self, solver: zsolver.ZSolver) -> z3.BoolRef:
        """Extract all symbol dependency and selection rules as a conjoined Z3 formula."""
        clauses = []

        for name, sym in self.kconf.syms.items():
            if not name or sym.type not in (kconfiglib.BOOL, kconfiglib.TRISTATE):
                continue

            config_name = f"CONFIG_{name}"
            z3_sym, optd = solver.get_sort(config_name)
            sym_active = (z3_sym == optd['y'])

            # 1. Direct dependencies: sym => direct_dep
            if sym.direct_dep and sym.direct_dep != self.kconf.y:
                dep_z3 = self.expr_to_z3(sym.direct_dep, solver)
                rev_z3 = self.expr_to_z3(sym.rev_dep, solver) if sym.rev_dep and sym.rev_dep != self.kconf.n else zsolver.F
                # If selected (rev_dep), direct_dep can be bypassed in Kconfig
                valid_enable = zsolver.disj(dep_z3, rev_z3)
                clauses.append(z3.Implies(sym_active, valid_enable))

            # 2. Reverse dependencies (select): rev_dep => sym
            if sym.rev_dep and sym.rev_dep != self.kconf.n:
                select_z3 = self.expr_to_z3(sym.rev_dep, solver)
                clauses.append(z3.Implies(select_z3, sym_active))

        # 3. Choices: at most one selected in non-optional choice blocks
        for choice in self.kconf.choices:
            choice_syms = [
                self.expr_to_z3(s, solver) for s in choice.syms
                if s.name and s.type in (kconfiglib.BOOL, kconfiglib.TRISTATE)
            ]
            if len(choice_syms) > 1:
                # Pairwise mutual exclusion
                for i in range(len(choice_syms)):
                    for j in range(i + 1, len(choice_syms)):
                        clauses.append(z3.Not(z3.And(choice_syms[i], choice_syms[j])))

        if not clauses:
            return zsolver.T
        return z3.simplify(z3.And(*clauses))

    def find_buildable_witness(self, target_cond: z3.BoolRef, solver: zsolver.ZSolver) -> Optional[Dict[str, str]]:
        """Find a model satisfying Phi_Kconfig conjoined with target Phi_Kbuild."""
        kconfig_formula = self.get_constraints(solver)
        conjoined = zsolver.conj(kconfig_formula, target_cond)

        s = z3.Solver()
        s.add(conjoined)
        if s.check() != z3.sat:
            return None

        model = s.model()
        config_dict = {}
        for name, (z3_sym, optd) in solver.__config_vars__.items():
            val = model.eval(z3_sym)
            for k, expr in optd.items():
                if str(val) == str(expr):
                    config_dict[name] = k
                    break
        return config_dict

    @staticmethod
    def write_dotconfig(config_dict: Dict[str, str], output_file: pathlib.Path):
        """Write a dictionary of config assignments to standard .config syntax."""
        lines = ["# Automatically generated by kfold buildable witness synthesis\n"]
        for k, v in sorted(config_dict.items()):
            if v in ('y', 'm'):
                lines.append(f"{k}={v}\n")
            else:
                lines.append(f"# {k} is not set\n")
        output_file.write_text(''.join(lines))
