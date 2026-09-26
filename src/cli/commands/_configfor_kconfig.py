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
DEFAULT_KCONFIG_ENV = {"ARCH": "x86", "SRCARCH": "x86", "CC": "gcc", "LD": "ld"}


def _kernelversion(tree):
    """VERSION.PATCHLEVEL.SUBLEVEL from a Linux tree's top-level Makefile."""
    v = {}
    try:
        for line in (tree / "Makefile").read_text(errors="replace").splitlines()[:10]:
            k, sep, val = line.partition("=")
            if sep and k.strip() in ("VERSION", "PATCHLEVEL", "SUBLEVEL"):
                v[k.strip()] = val.strip()
    except OSError:
        pass
    return ".".join(v.get(k, "0") for k in ("VERSION", "PATCHLEVEL", "SUBLEVEL"))


def kconfig_path_for(tree):
    p = tree / "Kconfig"
    return p if p.is_file() else None


def load_kconfig(tree, env=None):
    """A KconfigSMT for ``tree``'s Kconfig, or None if it has none."""
    path = kconfig_path_for(tree)
    if path is None:
        return None
    env = env or dict(DEFAULT_KCONFIG_ENV, KERNELVERSION=_kernelversion(tree))
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
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
    import kconfig_compat  # noqa: F401  (Kconfig syntax newer than kconfiglib)
    if isinstance(expr, kconfiglib.Symbol):
        if expr.name:
            yield expr.name
        return
    if isinstance(expr, tuple):
        for e in expr[1:]:
            yield from _expr_symbol_names(e, kconf)


def restricted_constraints(ksmt, solver, seed_names, max_symbols=8000, base_values=None,
                           follow_selects=False):
    """Phi_Kconfig (Z3) restricted to the cone of Kconfig symbols ``seed_names``
    (bare names) reach through "depends on" and choice membership
    (``KconfigSMT.dependency_cone``), much smaller than the whole tree's
    constraint set. The cone does not follow "select" fan-in: for widely
    selected symbols (CRC32, USB core, ...) that pulls in much of the tree.
    Symbols outside the cone that the cone's constraints mention (mostly
    selectors) are held at their ``base_values`` value when given, so a
    select from the base config still sets a lower bound and the solver
    cannot flip an unconstrained selector to bypass a "depends on". Falls
    back to the whole-tree formula if the cone exceeds ``max_symbols``.
    With ``follow_selects`` the cone also includes the symbols that select
    each cone symbol (transitively), which a promptless symbol such as
    DRM_SCHED needs: its only way to turn on is a selector, and pinning every
    selector to an off base value would make it look impossible.
    Returns (formula, cone symbol names)."""
    from kconfig_solver import formula_vars
    kconf = ksmt.kconf
    closure = ksmt.dependency_cone(seed_names, follow_selects=follow_selects)
    if len(closure) > max_symbols:
        return ksmt.get_constraints(solver), set(kconf.syms)
    formula = ksmt.get_constraints(solver, closure)
    if base_values is not None:
        pins = []
        for v in formula_vars(formula):
            name = str(v)
            if not name.startswith("CONFIG_") or name[len("CONFIG_"):] in closure:
                continue
            _, optd = solver.get_sort(name)
            want = base_values.get(name, "")
            pins.append(v == optd.get(want if want in optd else "", optd[""]))
        formula = z3.And(formula, *pins) if pins else formula
    return formula, closure
