"""Kconfig-dependency-aware constraint building for ``config-for``, restricted
to the cone of Kconfig symbols reachable from a set of seed symbols (rather
than the whole tree's ~15k symbols), so the Z3 formulas stay small for a
single-patch query. Reuses ``tools/kconfig_solver.KconfigSMT`` for parsing
and expression translation instead of reimplementing either.
"""
import os

import z3

import helpers.zsolver as zsolver
from kconfig_solver import KconfigSMT

# Environment kconfiglib needs to parse Linux's Kconfig the way the rest of
# kfold's tooling does (tools/kconfig_aware_ci_matrix.py CORPORA); harmless
# for trees whose Kconfig does not reference these.
DEFAULT_KCONFIG_ENV = {"ARCH": "x86", "SRCARCH": "x86", "KERNELVERSION": "6.6.0",
                       "CC": "gcc", "LD": "ld"}


def kconfig_path_for(tree):
    p = tree / "Kconfig"
    return p if p.is_file() else None


def load_kconfig(tree, env=None):
    """A KconfigSMT for ``tree``'s Kconfig, or None if it has none."""
    path = kconfig_path_for(tree)
    if path is None:
        return None
    old = {k: os.environ.get(k) for k in (env or DEFAULT_KCONFIG_ENV)}
    os.environ.update(env or DEFAULT_KCONFIG_ENV)
    try:
        return KconfigSMT(kconfig_path=path, srctree=tree)
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _expr_symbol_names(expr, kconf):
    """Names of the Kconfig symbols mentioned in a kconfiglib expression."""
    if expr is None or expr is kconf.n or expr is kconf.y:
        return
    import kconfiglib
    if isinstance(expr, kconfiglib.Symbol):
        if expr.name:
            yield expr.name
        return
    if isinstance(expr, tuple):
        for e in expr[1:]:
            yield from _expr_symbol_names(e, kconf)


def restricted_constraints(ksmt, solver, seed_names, max_symbols=8000):
    """Phi_Kconfig (Z3), restricted to the transitive cone of Kconfig symbols
    that ``seed_names`` (bare symbol names, no CONFIG_ prefix) depend on or
    are depended on by (direct_dep/rev_dep/choice siblings, expanded to a
    fixpoint) -- exact for questions about whether/how the seeds can be
    turned on, much smaller than the whole-tree constraint set. Falls back to
    the whole-tree formula (``ksmt.get_constraints``) if the cone would
    exceed ``max_symbols``. Returns (formula, closure symbol names)."""
    import kconfiglib
    kconf = ksmt.kconf
    closure = set()
    frontier = list(seed_names)
    overflowed = False
    while frontier:
        name = frontier.pop()
        if name in closure:
            continue
        sym = kconf.syms.get(name)
        if sym is None:
            continue
        closure.add(name)
        if len(closure) > max_symbols:
            overflowed = True
            break
        # Only expand through direct_dep ("depends on"/dependent expressions),
        # not rev_dep ("select"): rev_dep is every symbol that *selects this
        # one*, tree-wide, so for a handful of widely-selected symbols (e.g.
        # CRC32, USB core) it pulls in a large fraction of the whole tree and
        # their own deps recursively. Dropping it keeps the cone to the
        # "what must I turn on for my own depends-on chain" question, which
        # is sound (every witness still satisfies real direct_dep) though not
        # complete (a config that relies on some unrelated symbol's `select`
        # to bypass a depends-on it does not itself satisfy is not explored).
        for dep in _expr_symbol_names(sym.direct_dep, kconf):
            if dep not in closure:
                frontier.append(dep)
        if sym.choice is not None:
            for s in sym.choice.syms:
                if s.name and s.name not in closure:
                    frontier.append(s.name)
    if overflowed:
        return ksmt.get_constraints(solver), set(kconf.syms)

    clauses = []
    for name in closure:
        sym = kconf.syms[name]
        if sym.type not in (kconfiglib.BOOL, kconfiglib.TRISTATE):
            continue
        config_name = f"CONFIG_{name}"
        z3_sym, optd = solver.get_sort(config_name)
        sym_active = (z3_sym == optd["y"])
        if sym.type == kconfiglib.BOOL and "m" in optd:
            # kfold's config model is tristate-uniform regardless of a
            # symbol's real Kconfig type; a plain bool can never be "m".
            clauses.append(z3_sym != optd["m"])
        if sym.direct_dep and sym.direct_dep != kconf.y:
            dep_z3 = ksmt.expr_to_z3(sym.direct_dep, solver)
            clauses.append(z3.Implies(sym_active, dep_z3))
    for choice in kconf.choices:
        choice_syms = [s for s in choice.syms if s.name in closure]
        if len(choice_syms) > 1:
            zs = [ksmt.expr_to_z3(s, solver) for s in choice_syms]
            for i in range(len(zs)):
                for j in range(i + 1, len(zs)):
                    clauses.append(z3.Not(z3.And(zs[i], zs[j])))
    formula = z3.And(*clauses) if clauses else zsolver.T
    return formula, closure
