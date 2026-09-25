"""Kconfig-side helpers for ``kfold why``: loading the tree's Kconfig with
kconfiglib (via tools/kconfig_solver.KconfigSMT), explaining why a symbol is
off (depends on / select / choice), and suggesting a minimal set of symbol
changes (Z3: the object's condition, conjoined with a Kconfig-derived
neighborhood of constraints, minimized against the current .config) that
would turn it on.

Kept separate from why.py, and not auto-discovered (leading underscore), per
the phase-2A file-ownership rule: this module only reads other files, never
edits them.
"""
import os
import pathlib
import sys

import z3
from z3.z3util import get_vars

import helpers.zsolver as zsolver

ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))


def _import_kconfiglib_and_solver():
    import kconfiglib
    from kconfig_solver import KconfigSMT
    return kconfiglib, KconfigSMT


def _set_env_defaults():
    # Matches tools/kconfig_witness_demo.py; the archived configs kfold is
    # checked against (defconfig/tinyconfig_i386/allmodconfig) are all x86.
    os.environ.setdefault("ARCH", "x86")
    os.environ.setdefault("SRCARCH", "x86")
    os.environ.setdefault("KERNELVERSION", "6.6.0")
    os.environ.setdefault("CC", "gcc")
    os.environ.setdefault("LD", "ld")


def load(tree):
    """A ``KconfigSMT`` for ``tree``'s top-level Kconfig, or None (with a
    reason string) if the tree has none or kconfiglib cannot parse it."""
    kconfig_path = pathlib.Path(tree) / "Kconfig"
    if not kconfig_path.is_file():
        return None, f"{kconfig_path}: no such file"
    _set_env_defaults()
    kconfiglib, KconfigSMT = _import_kconfiglib_and_solver()
    try:
        return KconfigSMT(kconfig_path, srctree=pathlib.Path(tree)), None
    except Exception as e:  # kconfiglib raises plain Exception/KconfigError
        return None, f"kconfiglib could not parse {kconfig_path}: {e}"


def zkey(value):
    """The raw python value ZSolver's enum dict is keyed by, for a
    developer-facing value ('y'/'m'/'n'/'' all mean off except y/m)."""
    return "" if value in (None, "", "n") else value


def cur_value(config_values, name):
    """'y'/'m'/'n' for CONFIG_ ``name`` (no prefix) under ``config_values``
    ({CONFIG_X: value})."""
    v = config_values.get(f"CONFIG_{name}", "")
    return v if v in ("y", "m") else "n"


def truth_of(expr, config_values, solver):
    """True/False/None (symbolic) for a cached z3 condition under a
    {CONFIG_X: value} mapping, reusing objects._truth (read-only import)."""
    from objects import _truth, _Symbolic
    cache = {}
    names = {}

    def value_of(sym):
        if sym not in names:
            _, values = solver.get_sort(sym)
            v = config_values.get(sym, "")
            names[sym] = str(values.get(v, values[""]))
        return names[sym]

    try:
        return bool(_truth(expr, value_of, cache))
    except _Symbolic:
        return None


def closure(ksmt, kconfiglib, seed_names, max_iters=5, cap=4000):
    """Names (bare, no CONFIG_ prefix) reachable from ``seed_names`` through
    kconfiglib's ``referenced`` (deps, selects, defaults, ranges, surrounding
    menu/if conditions) and choice membership -- the Kconfig neighborhood a
    minimal-change search should consider."""
    scope = set(seed_names)
    frontier = set(seed_names)
    for _ in range(max_iters):
        if len(scope) >= cap:
            break
        new = set()
        for name in frontier:
            sym = ksmt.kconf.syms.get(name)
            if sym is None:
                continue
            refs = list(getattr(sym, "referenced", ()) or ())
            if sym.choice is not None:
                refs.append(sym.choice)
            for ref in refs:
                if isinstance(ref, kconfiglib.Symbol):
                    if ref.name and not ref.is_constant and ref.name not in scope:
                        new.add(ref.name)
                elif isinstance(ref, kconfiglib.Choice):
                    for s in ref.syms:
                        if s.name and s.name not in scope:
                            new.add(s.name)
        if not new:
            break
        scope |= new
        frontier = new
        if len(scope) >= cap:
            break
    return scope


def _active_z3(ksmt, kconfiglib, expr, solver):
    """Like KconfigSMT.expr_to_z3, but a bare Symbol leaf means "on" (y or
    m), not just "y": KconfigSMT.get_constraints treats "depends on"/
    "select" as if only CONFIG_X=y satisfies them, so a dependency of a
    module (CONFIG_X=m) is left unconstrained there. That under-constrains
    exactly the common case this command's suggestions land on (enabling
    something as a module), so this module recurses itself instead of
    calling ksmt.expr_to_z3, changing only the Symbol-leaf case; local to
    kfold's own why.py, tools/kconfig_solver.py is untouched."""
    if expr is None or expr == ksmt.kconf.n:
        return zsolver.F
    if expr == ksmt.kconf.y:
        return zsolver.T
    if isinstance(expr, kconfiglib.Symbol):
        name = f"CONFIG_{expr.name}"
        sym, optd = solver.get_sort(name)
        if expr.type not in (kconfiglib.BOOL, kconfiglib.TRISTATE):
            return sym == optd["y"]
        return sym != optd[""]
    if isinstance(expr, tuple):
        op = expr[0]
        if op == kconfiglib.AND:
            return zsolver.conj(_active_z3(ksmt, kconfiglib, expr[1], solver),
                                _active_z3(ksmt, kconfiglib, expr[2], solver))
        if op == kconfiglib.OR:
            return zsolver.disj(_active_z3(ksmt, kconfiglib, expr[1], solver),
                                _active_z3(ksmt, kconfiglib, expr[2], solver))
        if op == kconfiglib.NOT:
            return zsolver.neg(_active_z3(ksmt, kconfiglib, expr[1], solver))
        if op in (kconfiglib.EQUAL, kconfiglib.UNEQUAL):
            return ksmt.expr_to_z3(expr, solver)
    return zsolver.T


def scoped_constraints(ksmt, kconfiglib, names, solver):
    """Phi_Kconfig restricted to ``names`` (bare symbol names): per-symbol
    direct-dependency / reverse-dependency (select) implications and choice
    mutual-exclusion clauses, built only for this neighborhood so Z3 stays
    fast on a whole-kernel Kconfig (~17k symbols), and using tri-state
    "on" = y-or-m (see ``_active_z3``) rather than KconfigSMT's y-only
    notion of "active"."""
    clauses = []
    name_set = set(names)
    for name in name_set:
        sym = ksmt.kconf.syms.get(name)
        if sym is None or sym.type not in (kconfiglib.BOOL, kconfiglib.TRISTATE):
            continue
        config_name = f"CONFIG_{name}"
        z3_sym, optd = solver.get_sort(config_name)
        sym_active = (z3_sym != optd[""])
        if sym.direct_dep is not None and sym.direct_dep != ksmt.kconf.y:
            dep_z3 = _active_z3(ksmt, kconfiglib, sym.direct_dep, solver)
            rev_z3 = (_active_z3(ksmt, kconfiglib, sym.rev_dep, solver)
                      if sym.rev_dep is not None and sym.rev_dep != ksmt.kconf.n else zsolver.F)
            clauses.append(z3.Implies(sym_active, zsolver.disj(dep_z3, rev_z3)))
        if sym.rev_dep is not None and sym.rev_dep != ksmt.kconf.n:
            select_z3 = _active_z3(ksmt, kconfiglib, sym.rev_dep, solver)
            clauses.append(z3.Implies(select_z3, sym_active))
    for choice in ksmt.kconf.choices:
        members = [s for s in choice.syms if s.name in name_set]
        if len(members) > 1:
            zs = [_active_z3(ksmt, kconfiglib, s, solver) for s in members]
            for i in range(len(zs)):
                for j in range(i + 1, len(zs)):
                    clauses.append(z3.Not(z3.And(zs[i], zs[j])))
    if not clauses:
        return zsolver.T
    return z3.And(*clauses)


def explain_symbol(ksmt, kconfiglib, name, config_values):
    """depends on / unmet deps / choice / select explanation for CONFIG_
    ``name`` (bare), as seen under ``config_values``."""
    sym = ksmt.kconf.syms.get(name)
    out = {"name": f"CONFIG_{name}", "current_value": cur_value(config_values, name)}
    if sym is None:
        out["found"] = False
        return out
    out["found"] = True
    out["depends_on"] = (kconfiglib.expr_str(sym.direct_dep)
                         if sym.direct_dep is not None and sym.direct_dep != ksmt.kconf.y else None)

    def leaves(e):
        if e is None or isinstance(e, str):
            return
        if isinstance(e, kconfiglib.Symbol):
            yield e
        elif isinstance(e, tuple):
            for x in e[1:]:
                if isinstance(x, (kconfiglib.Symbol, tuple)):
                    yield from leaves(x)

    unmet, seen = [], set()
    for leaf in leaves(sym.direct_dep):
        if leaf.is_constant or not leaf.name or leaf.name in seen:
            continue
        seen.add(leaf.name)
        if leaf.type in (kconfiglib.BOOL, kconfiglib.TRISTATE) and cur_value(config_values, leaf.name) != "y":
            unmet.append({"name": f"CONFIG_{leaf.name}", "value": cur_value(config_values, leaf.name)})
    out["unmet_deps"] = unmet

    out["choice"] = None
    if sym.choice is not None:
        ch = sym.choice
        cur_sel = next((s.name for s in ch.syms if cur_value(config_values, s.name) == "y"), None)
        out["choice"] = {
            "prompt": ch.prompts[0][0] if ch.prompts else None,
            "members": [s.name for s in ch.syms],
            "currently_selected": cur_sel,
        }

    selected_by = []
    for other_name, other in ksmt.kconf.syms.items():
        for target, cond in getattr(other, "selects", ()) or ():
            if target is sym:
                selected_by.append({
                    "name": f"CONFIG_{other_name}",
                    "value": cur_value(config_values, other_name),
                    "condition": kconfiglib.expr_str(cond) if cond is not None and cond != ksmt.kconf.y else None,
                })
    out["selected_by"] = selected_by
    return out


def _model_value(model, z3_sym, optd):
    v = model.eval(z3_sym, model_completion=True)
    for k, expr in optd.items():
        if str(v) == str(expr):
            return "n" if k == "" else k
    return "n"


def minimal_changes(a, ksmt, kconfiglib, path, config_values, timeout_ms=20000):
    """A minimal {CONFIG_X: 'y'|'m'|'n'} change (from ``config_values``) that
    satisfies ``a.conds[path]`` under Phi_Kconfig, searched in the Kconfig
    neighborhood of the object's own symbols; widens the neighborhood once
    if the first attempt is UNSAT/unknown. Returns (diff dict or None,
    note)."""
    solver = a.solver()
    full_cond = a.conds[path]
    seed = {s[len("CONFIG_"):] for s in a.symbols(path) if s.startswith("CONFIG_")}
    seed = {n for n in seed if n in ksmt.kconf.syms}
    if not seed:
        return None, "object's condition has no Kconfig-known symbols"

    for max_iters, cap in ((3, 1500), (6, 4000)):
        scope = closure(ksmt, kconfiglib, seed, max_iters=max_iters, cap=cap)
        phi = scoped_constraints(ksmt, kconfiglib, scope, solver)
        combined = zsolver.conj(phi, full_cond)
        allvars = [v for v in get_vars(combined) if str(v).startswith("CONFIG_")]
        opt = z3.Optimize()
        try:
            opt.set("timeout", timeout_ms)
        except z3.Z3Exception:
            pass
        opt.add(combined)
        for v in allvars:
            name = str(v)
            bare0 = name[len("CONFIG_"):]
            sym0 = ksmt.kconf.syms.get(bare0)
            if sym0 is not None and sym0.type == kconfiglib.BOOL:
                # kfold's z3 model is uniformly tri-state (see cache.py's
                # use_tristate), but a real bool Kconfig symbol has no valid
                # "m" value; olddefconfig silently drops an "m" assignment
                # to a bool symbol, which can undo a suggested change. Keep
                # the search from ever proposing "m" for a symbol Kconfig
                # itself declares bool.
                _, optd0 = solver.get_sort(name)
                if "m" in optd0:
                    opt.add(v != optd0["m"])
        for v in allvars:
            name = str(v)
            _, optd = solver.get_sort(name)
            bare = name[len("CONFIG_"):]
            cur = cur_value(config_values, bare)
            cur_const = optd[zkey(cur)]
            opt.add_soft(v == cur_const, weight=1)
        result = opt.check()
        if result != z3.sat:
            continue
        model = opt.model()
        diff = {}
        for v in allvars:
            name = str(v)
            _, optd = solver.get_sort(name)
            bare = name[len("CONFIG_"):]
            new_val = _model_value(model, v, optd)
            cur = cur_value(config_values, bare)
            if new_val != cur:
                diff[name] = new_val
        return diff, f"solved in a {len(scope)}-symbol Kconfig neighborhood"
    return None, "no satisfying assignment found (even widening the Kconfig neighborhood, or Z3 timed out)"
