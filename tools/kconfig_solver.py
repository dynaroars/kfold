#!/usr/bin/env python3
"""Robust Kconfig Propositional Constraint Extractor & Solver (M17.5).

Uses standard AST parsing via kconfiglib to convert Kconfig dependencies (depends on, select,
choice blocks) into Z3 propositional clauses (Phi_Kconfig) over y/m/n values.

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


# Tools the kernel's top-level Makefile exports before running Kconfig, which
# probes them with $(shell,...) / $(success,...) (e.g. X86_X32_ABI depends on
# "$(OBJCOPY) --version"). Unset, those probes fail and silently force
# options off. Used only where the environment does not already set them.
TOOLCHAIN_DEFAULTS = {
    "CC": "gcc", "LD": "ld", "AR": "ar", "NM": "nm", "OBJCOPY": "objcopy",
    "OBJDUMP": "objdump", "READELF": "readelf", "STRIP": "strip",
    "HOSTCC": "gcc", "HOSTCXX": "g++", "HOSTPKG_CONFIG": "pkg-config",
    "PAHOLE": "pahole", "RUSTC": "rustc", "BINDGEN": "bindgen",
}


def formula_vars(*exprs) -> List[z3.ExprRef]:
    """The uninterpreted constants in ``exprs``, each visited once.
    ``z3.z3util.get_vars`` does not memoize shared subterms, which makes it
    exponential on Kconfig formulas whose select expressions share subterms."""
    seen, out, todo = set(), {}, list(exprs)
    while todo:
        e = todo.pop()
        eid = e.get_id()
        if eid in seen:
            continue
        seen.add(eid)
        if z3.is_const(e):
            if e.decl().kind() == z3.Z3_OP_UNINTERPRETED:
                out[eid] = e
        else:
            todo.extend(e.children())
    return list(out.values())


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
        added_env = [k for k in TOOLCHAIN_DEFAULTS if k not in os.environ]
        try:
            os.chdir(self.srctree)
            os.environ["srctree"] = str(self.srctree)
            for k in added_env:
                os.environ[k] = TOOLCHAIN_DEFAULTS[k]
            if tolerate_missing_glob_sources:
                kconfiglib._OBL_SOURCE_TOKENS = frozenset()
            self.kconf = kconfiglib.Kconfig(str(kconfig_path.relative_to(self.srctree)), warn=False, warn_to_stderr=False)
        finally:
            os.chdir(old_cwd)
            for k in added_env:
                os.environ.pop(k, None)
            kconfiglib._OBL_SOURCE_TOKENS = old_obl_source_tokens
            if old_srctree_env is None:
                os.environ.pop("srctree", None)
            else:
                os.environ["srctree"] = old_srctree_env

    # Kconfig values are n < m < y. A value v is encoded as the pair of Z3
    # Booleans (v >= m, v >= y): y = (T, T), m = (T, F), n = (F, F). Then
    # AND is min, OR is max, and NOT (2 - v) swaps and negates the pair, all
    # without integer arithmetic. With a two-state solver (use_tristate off)
    # there is no m, so both components are "sym == y".

    _N = (zsolver.F, zsolver.F)
    _M = (zsolver.T, zsolver.F)
    _Y = (zsolver.T, zsolver.T)

    def _sym_pair(self, sym, solver):
        z3_sym, optd = solver.get_sort(f"CONFIG_{sym.name}")
        is_y = z3_sym == optd['y']
        if 'm' not in optd:
            return is_y, is_y
        return z3_sym != optd[solver.mysettings.zstate.undef_val], is_y

    def _fresh_pair(self):
        """A Boolean (y or n) result the encoding does not model, such as
        comparing string or int symbols; left unconstrained."""
        self._unknowns = getattr(self, "_unknowns", 0) + 1
        b = z3.Bool(f"__kconfig_unknown_{self._unknowns}")
        return b, b

    def tri(self, expr, solver: zsolver.ZSolver):
        """Translate a kconfiglib expression into its tristate value, as the
        pair (value >= m, value >= y) of Z3 Booleans."""
        if expr is None or expr is self.kconf.n:
            return self._N
        if expr is self.kconf.y:
            return self._Y
        if expr is self.kconf.m:
            return self._M

        if isinstance(expr, kconfiglib.Symbol):
            if expr.is_constant:
                # A quoted string; as a bare expression its value is n.
                return self._N
            if expr.orig_type in (kconfiglib.BOOL, kconfiglib.TRISTATE) or not expr.nodes:
                # Undefined symbols get a variable too, pinned to n by
                # get_constraints, so they stay shared with Kbuild conditions.
                return self._sym_pair(expr, solver)
            # A string/int/hex symbol has tristate value n.
            return self._N

        if isinstance(expr, kconfiglib.Choice):
            return self._fresh_pair()

        op = expr[0]
        if op == kconfiglib.AND:
            (am, ay), (bm, by) = self.tri(expr[1], solver), self.tri(expr[2], solver)
            return zsolver.conj(am, bm), zsolver.conj(ay, by)
        if op == kconfiglib.OR:
            (am, ay), (bm, by) = self.tri(expr[1], solver), self.tri(expr[2], solver)
            return zsolver.disj(am, bm), zsolver.disj(ay, by)
        if op == kconfiglib.NOT:
            am, ay = self.tri(expr[1], solver)
            return zsolver.neg(ay), zsolver.neg(am)
        if op in (kconfiglib.EQUAL, kconfiglib.UNEQUAL):
            eq = self._equal(expr[1], expr[2], solver)
            if eq is None:
                return self._fresh_pair()
            if op == kconfiglib.UNEQUAL:
                eq = zsolver.neg(eq)
            return eq, eq
        # LESS, GREATER, ... compare int/hex values, which are not modeled.
        return self._fresh_pair()

    def _is_tri_operand(self, sym):
        if sym in (self.kconf.y, self.kconf.m, self.kconf.n):
            return True
        return (isinstance(sym, kconfiglib.Symbol) and not sym.is_constant
                and (sym.orig_type in (kconfiglib.BOOL, kconfiglib.TRISTATE) or not sym.nodes))

    def _equal(self, a, b, solver):
        """Z3 Boolean for "a = b", or None if the comparison is not modeled."""
        if self._is_tri_operand(a) and self._is_tri_operand(b):
            (am, ay), (bm, by) = self.tri(a, solver), self.tri(b, solver)
            return z3.And(am == bm, ay == by)
        if (isinstance(a, kconfiglib.Symbol) and a.is_constant
                and isinstance(b, kconfiglib.Symbol) and b.is_constant):
            return zsolver.T if a.str_value == b.str_value else zsolver.F
        return None

    def expr_to_z3(self, expr, solver: zsolver.ZSolver):
        """Z3 Boolean for "expr is on" (y or m), the sense in which Kconfig
        satisfies a "depends on" or "if"."""
        return self.tri(expr, solver)[0]

    def expr_is_y(self, expr, solver: zsolver.ZSolver):
        """Z3 Boolean for "expr is y"."""
        return self.tri(expr, solver)[1]

    def symbol_clauses(self, sym, solver: zsolver.ZSolver) -> List[z3.BoolRef]:
        """Constraints Kconfig places on one bool/tristate symbol:

        - the value is at most max(direct dependency, reverse dependency),
          because "select" overrides an unmet "depends on";
        - the value is at least the reverse dependency ("select");
        - a bool symbol is never m (an m bound rounds up to y);
        - a tristate symbol is m only when MODULES is y.

        A symbol with neither a prompt nor a default is at most the larger of
        its "select" and "imply" reverse dependencies. Symbols that are referenced but defined nowhere are
        always n, and a
        "select" of a choice member is ignored, as in Kconfig.
        Defaults, "imply", and ranges are not modeled, so these constraints
        over-approximate the set of valid configurations."""
        if sym.is_constant or not sym.name:
            return []
        if not sym.nodes:
            return [zsolver.neg(self._sym_pair(sym, solver)[0])] if sym.orig_type == kconfiglib.UNKNOWN else []
        if sym.orig_type not in (kconfiglib.BOOL, kconfiglib.TRISTATE):
            return []

        sm, sy = self._sym_pair(sym, solver)
        dm, dy = self.tri(sym.direct_dep, solver)
        # "select" has no effect on a choice member (Kconfig warns and
        # ignores it); the choice itself decides.
        rev = self.kconf.n if sym.choice is not None else sym.rev_dep
        rm, ry = self.tri(rev, solver)
        bounded = sym.direct_dep is not self.kconf.y and rev is not self.kconf.y
        selected = rev is not self.kconf.n
        clauses = []
        if not any(node.prompt for node in sym.nodes) and not sym.defaults and sym.choice is None:
            # With no prompt and no default, only "select" and "imply" set
            # the value.
            wm, wy = self.tri(sym.weak_rev_dep, solver)
            if sym.orig_type == kconfiglib.BOOL:
                clauses.append(z3.Implies(sy, zsolver.disj(rm, wm)))
            else:
                clauses.append(z3.Implies(sm, zsolver.disj(rm, wm)))
                clauses.append(z3.Implies(sy, zsolver.disj(ry, wy)))
        if sym.orig_type == kconfiglib.BOOL:
            clauses.append(z3.Implies(sm, sy))                           # never m
            if bounded:
                clauses.append(z3.Implies(sy, zsolver.disj(dm, rm)))    # m bound rounds up
            if selected:
                clauses.append(z3.Implies(rm, sy))
        else:
            if bounded:
                clauses.append(z3.Implies(sm, zsolver.disj(dm, rm)))
                clauses.append(z3.Implies(sy, zsolver.disj(dy, ry)))
            if selected:
                clauses.append(z3.Implies(rm, sm))
                clauses.append(z3.Implies(ry, sy))
            modules = self.kconf.modules
            if modules is not None and modules.nodes and modules is not sym:
                clauses.append(z3.Implies(z3.And(sm, zsolver.neg(sy)),
                                          self._sym_pair(modules, solver)[1]))
        return clauses

    def choice_clauses(self, choice, solver: zsolver.ZSolver) -> List[z3.BoolRef]:
        """At most one member of a choice is y."""
        ys = [self._sym_pair(s, solver)[1] for s in choice.syms
              if s.name and s.orig_type in (kconfiglib.BOOL, kconfiglib.TRISTATE)]
        return [z3.Not(z3.And(ys[i], ys[j]))
                for i in range(len(ys)) for j in range(i + 1, len(ys))]

    def dependency_cone(self, names, follow_selects: bool = False) -> Set[str]:
        """Names of the symbols reachable from ``names`` (with or without the
        CONFIG_ prefix) through "depends on", choice membership, and, if
        ``follow_selects``, the symbols that select them. Constraints over a
        cone are a sound relaxation of the whole-tree constraints: every
        valid configuration satisfies them."""
        todo = [n[len("CONFIG_"):] if n.startswith("CONFIG_") else n for n in names]
        seen = set()
        while todo:
            name = todo.pop()
            sym = self.kconf.syms.get(name)
            if name in seen or sym is None:
                continue
            seen.add(name)
            deps = kconfiglib.expr_items(sym.direct_dep)
            if follow_selects:
                deps |= kconfiglib.expr_items(sym.rev_dep)
            if sym.choice is not None:
                deps |= set(sym.choice.syms) | kconfiglib.expr_items(sym.choice.direct_dep)
            todo.extend(d.name for d in deps
                        if isinstance(d, kconfiglib.Symbol) and not d.is_constant)
        return seen

    def get_constraints(self, solver: zsolver.ZSolver, names=None) -> z3.BoolRef:
        """Conjunction of the Kconfig constraints (see ``symbol_clauses``) on
        all symbols, or only on ``names`` and the choices they belong to,
        e.g. a ``dependency_cone``."""
        if names is None:
            syms = list(self.kconf.syms.values())
            choices = self.kconf.choices
        else:
            names = {n[len("CONFIG_"):] if n.startswith("CONFIG_") else n for n in names}
            syms = [self.kconf.syms[n] for n in names if n in self.kconf.syms]
            choices = {s.choice for s in syms if s.choice is not None}
        clauses = []
        for sym in syms:
            clauses.extend(self.symbol_clauses(sym, solver))
        for choice in choices:
            clauses.extend(self.choice_clauses(choice, solver))
        if not clauses:
            return zsolver.T
        return z3.And(*clauses)

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
