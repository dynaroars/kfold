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
from kconfig_solver import formula_vars

import helpers.zsolver as zsolver

ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))


def _import_kconfiglib_and_solver():
    import kconfiglib
    import kconfig_compat  # noqa: F401  (Kconfig syntax newer than kconfiglib)
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


def scoped_constraints(ksmt, kconfiglib, names, solver):
    """Phi_Kconfig restricted to ``names`` (bare symbol names), so Z3 stays
    fast on a whole-kernel Kconfig (~17k symbols); see
    ``KconfigSMT.symbol_clauses`` for the y/m/n semantics."""
    return ksmt.get_constraints(solver, names)


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
        if leaf.orig_type in (kconfiglib.BOOL, kconfiglib.TRISTATE) and cur_value(config_values, leaf.name) == "n":
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
        allvars = [v for v in formula_vars(combined) if str(v).startswith("CONFIG_")]
        # Symbols outside the neighborhood that the constraints mention
        # (mostly selectors of widely selected symbols such as BLOCK) keep
        # their current value, so the search stays small and cannot flip an
        # unconstrained selector to bypass a "depends on".
        pins = []
        for v in allvars:
            name = str(v)
            if name[len("CONFIG_"):] not in scope:
                _, optd = solver.get_sort(name)
                pins.append(v == optd[zkey(cur_value(config_values, name[len("CONFIG_"):]))])
        if pins:
            combined = z3.And(combined, *pins)
        opt = z3.Optimize()
        try:
            opt.set("timeout", timeout_ms)
        except z3.Z3Exception:
            pass
        opt.add(combined)
        for v in allvars:
            name = str(v)
            _, optd = solver.get_sort(name)
            bare = name[len("CONFIG_"):]
            cur = cur_value(config_values, bare)
            cur_const = optd[zkey(cur)]
            opt.add_soft(v == cur_const, weight=2)
            # Among equally small changes, prefer m to y: a symbol a module
            # selects then follows by itself and need not be listed.
            if "m" in optd:
                opt.add_soft(v != optd["y"], weight=1)
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
        # Leave out what olddefconfig derives by itself: symbols without a
        # prompt (set only by select/imply) and symbols whose new value is
        # already forced by a select in the solved configuration.
        def follows(n):
            sym = ksmt.kconf.syms.get(n[len("CONFIG_"):])
            if sym is None or not sym.nodes:
                return False
            if not any(node.prompt for node in sym.nodes):
                return True
            rm, ry = ksmt.tri(sym.rev_dep, solver)
            forced = ("y" if z3.is_true(model.eval(ry, model_completion=True)) else
                      "m" if z3.is_true(model.eval(rm, model_completion=True)) else "n")
            if forced == "m" and sym.orig_type == kconfiglib.BOOL:
                forced = "y"   # a bool selected by a module is y
            return forced != "n" and forced == diff[n]
        derived = sorted(n for n in diff if follows(n))
        for n in derived:
            del diff[n]
        note = f"solved in a {len(scope)}-symbol Kconfig neighborhood"
        if derived:
            note += f"; {len(derived)} more follow via select or olddefconfig"
        return diff, note
    return None, "no satisfying assignment found (even widening the Kconfig neighborhood, or Z3 timed out)"
