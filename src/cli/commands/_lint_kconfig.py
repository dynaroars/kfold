"""kfold lint helpers: Kconfig symbol declarations and the Kconfig-aware
dead-object check (Phi_Kbuild(o) AND Phi_Kconfig unsatisfiable).

Not auto-discovered as a subcommand (leading underscore); imported by
``cli.commands.lint``.
"""
import collections
import os
import pathlib
import re
import sys

import z3

ROOT = pathlib.Path(__file__).resolve().parents[3]
_TOOLS = ROOT / "tools"


def _kconfig_smt_cls():
    """Import tools/kconfig_solver.KconfigSMT lazily (tools/ is not on
    sys.path by default; adding it here keeps the import local to lint)."""
    if str(_TOOLS) not in sys.path:
        sys.path.insert(0, str(_TOOLS))
    from kconfig_solver import KconfigSMT
    return KconfigSMT


_CONFIG_DECL_RE = re.compile(r"^\s*(?:config|menuconfig)\s+([A-Za-z0-9_]+)", re.MULTILINE)

# Directories that hold Kconfig-*like* files that are not real declarations
# in scope for a lint run: kconfiglib's own self-test fixtures (scripts/
# kconfig/tests/*/Kconfig), documentation snippets, and vendored copies under
# tools/ (e.g. tools/perf has its own unrelated Kconfig-like build glue in
# some trees). Excluding these keeps the "declared" universe limited to
# symbols the kernel's own Kconfig actually defines.
_EXCLUDE_TOP = ("Documentation", "tools", "scripts")


def kconfig_files(tree):
    """Kconfig/Kconfig.* files under ``tree``, excluding non-declaration
    trees (see ``_EXCLUDE_TOP``)."""
    out = []
    for p in tree.rglob("Kconfig*"):
        if not p.is_file():
            continue
        try:
            rel = p.relative_to(tree)
        except ValueError:
            continue
        if rel.parts and rel.parts[0] in _EXCLUDE_TOP:
            continue
        out.append(p)
    return sorted(out)


def arch_of(rel_path):
    """The arch name if ``rel_path`` (relative to the tree) is under
    arch/<name>/, else None (common/shared code)."""
    parts = pathlib.Path(rel_path).parts
    if len(parts) >= 2 and parts[0] == "arch":
        return parts[1]
    return None


def declared_symbols(tree, files=None):
    """{CONFIG_X: {arch or None, ...}} of every ``config``/``menuconfig``
    declaration found by a plain regex scan of the tree's Kconfig files (not
    a real Kconfig parse: it does not know about ``source`` guards, so a
    symbol declared in a file that itself is never sourced still counts as
    declared -- documented as a false-negative-prone heuristic, which keeps
    the zombie-symbol check's false positive rate low)."""
    declared = collections.defaultdict(set)
    for f in (files if files is not None else kconfig_files(tree)):
        rel = f.relative_to(tree)
        arch = arch_of(rel)
        try:
            text = f.read_text(errors="ignore")
        except OSError:
            continue
        for m in _CONFIG_DECL_RE.finditer(text):
            declared["CONFIG_" + m.group(1)].add(arch)
    return declared


def is_in_scope(arches, target_arch):
    """True if ``arches`` (a set from ``declared_symbols``) declares the
    symbol for ``target_arch`` or for common/shared code (None)."""
    return None in arches or target_arch in arches


# ---------------------------------------------------------------- dead objects

DEFAULT_KCONFIG_ENV = {
    "ARCH": "x86", "SRCARCH": "x86", "KERNELVERSION": "6.6.0", "CC": "gcc", "LD": "ld",
}


class KconfigConstraints:
    """Phi_Kconfig for a tree, built once and reused across many SAT checks.

    ``incomplete_symbols``: CONFIG_ names referenced by the analyzed objects
    that kconfiglib's parse did not turn into a symbol (either genuinely
    undeclared -- already caught by the zombie check -- or a parse
    limitation, e.g. an arch-conditional ``source`` kfold's simplified
    Kconfig walk did not follow). Dead-object findings that mention such a
    symbol are marked ``incomplete=True`` and should not be trusted as firm
    dead code without independently checking that symbol.
    """

    def __init__(self, tree, kconfig_rel="Kconfig", solver=None, env=None,
                 tolerate_missing_glob_sources=True, max_closure_depth=6):
        KconfigSMT = _kconfig_smt_cls()
        self.tree = pathlib.Path(tree)
        self.kconfig_path = self.tree / kconfig_rel
        if not self.kconfig_path.is_file():
            raise FileNotFoundError(str(self.kconfig_path))
        env = dict(DEFAULT_KCONFIG_ENV, **(env or {}))
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            self.ksmt = KconfigSMT(self.kconfig_path, srctree=self.tree,
                                   tolerate_missing_glob_sources=tolerate_missing_glob_sources)
            self._build_clauses(solver)
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.known_names = set(self.ksmt.kconf.syms.keys())
        self.max_closure_depth = max_closure_depth

    def _build_clauses(self, solver):
        """Per-symbol Z3 clauses (direct_dep/rev_dep implications, plus a
        bool-forbids-m supplement -- see below) and a name->name dependency
        graph, so a SAT check for one object can conjoin only the small
        closure of Kconfig clauses actually relevant to it instead of the
        whole tree's constraints (checking ~29k Linux objects against one
        monolithic formula each does not finish in practical time)."""
        import kconfiglib
        self._sym_clauses = {}
        self._deps = collections.defaultdict(set)
        for name, sym in self.ksmt.kconf.syms.items():
            if not name or sym.type not in (kconfiglib.BOOL, kconfiglib.TRISTATE):
                continue
            zvar, optd = solver.get_sort(f"CONFIG_{name}")
            sym_active = zvar == optd["y"]
            clauses = []
            if sym.direct_dep and sym.direct_dep != self.ksmt.kconf.y:
                dep_z3 = self.ksmt.expr_to_z3(sym.direct_dep, solver)
                rev_z3 = (self.ksmt.expr_to_z3(sym.rev_dep, solver)
                         if sym.rev_dep and sym.rev_dep != self.ksmt.kconf.n
                         else z3.BoolVal(False))
                clauses.append(z3.Implies(sym_active, z3.Or(dep_z3, rev_z3)))
                for n2 in _expr_names(sym.direct_dep) | _expr_names(sym.rev_dep):
                    if n2 != name:
                        self._deps[name].add(n2)
            if sym.rev_dep and sym.rev_dep != self.ksmt.kconf.n:
                select_z3 = self.ksmt.expr_to_z3(sym.rev_dep, solver)
                clauses.append(z3.Implies(select_z3, sym_active))
                for n2 in _expr_names(sym.rev_dep):
                    if n2 != name:
                        self._deps[name].add(n2)
            # See the module docstring / report: KconfigSMT.expr_to_z3 models
            # "enabled" purely as sym == y, so without this a bool symbol
            # forced off by Kconfig would still look reachable through the
            # Kbuild analyzer's generic obj-m branch (a false negative, not a
            # false positive, for the dead check).
            if sym.type == kconfiglib.BOOL and "m" in optd:
                clauses.append(zvar != optd["m"])
            if clauses:
                self._sym_clauses[name] = clauses
        self._choice_clauses = []
        for choice in self.ksmt.kconf.choices:
            syms = [s for s in choice.syms if s.name and s.type in (kconfiglib.BOOL, kconfiglib.TRISTATE)]
            if len(syms) < 2:
                continue
            names = {s.name for s in syms}
            zvars = [solver.get_sort(f"CONFIG_{s.name}") for s in syms]
            clauses = [z3.Not(z3.And(zvars[i][0] == zvars[i][1]["y"], zvars[j][0] == zvars[j][1]["y"]))
                      for i in range(len(zvars)) for j in range(i + 1, len(zvars))]
            self._choice_clauses.append((names, clauses))
            for n in names:
                self._deps[n] |= (names - {n})

    def closure(self, seed_names):
        """Kconfig symbol names (bare, no CONFIG_ prefix) transitively
        relevant to ``seed_names`` via direct_dep/rev_dep/choice edges, up to
        ``max_closure_depth`` hops."""
        seen = set()
        frontier = {n for n in seed_names if n in self.ksmt.kconf.syms}
        depth = 0
        while frontier and depth < self.max_closure_depth:
            seen |= frontier
            nxt = set()
            for n in frontier:
                nxt |= self._deps.get(n, set())
            frontier = nxt - seen
            depth += 1
        return seen

    def constraints_for(self, seed_names):
        """The Kconfig clauses relevant to ``seed_names`` (bare names)."""
        closure = self.closure(seed_names)
        clauses = []
        for n in closure:
            clauses.extend(self._sym_clauses.get(n, ()))
        for names, cls in self._choice_clauses:
            if names & closure:
                clauses.extend(cls)
        return clauses

    def declared(self, config_symbol):
        """Whether kconfiglib's parse produced a symbol for CONFIG_X."""
        if not config_symbol.startswith("CONFIG_"):
            return True
        return config_symbol[len("CONFIG_"):] in self.known_names


def _expr_names(expr):
    """Kconfig symbol names (bare) mentioned by a kconfiglib expression."""
    import kconfiglib
    out = set()
    stack = [expr]
    while stack:
        e = stack.pop()
        if e is None:
            continue
        if isinstance(e, kconfiglib.Symbol):
            if e.name:
                out.add(e.name)
        elif isinstance(e, tuple):
            stack.extend(e[1:])
    return out


def dead_check(analysis, kconfig, paths=None, timeout_ms=15000, limit=None):
    """[(path, status, incomplete)] for objects whose Kbuild condition
    (``status="kbuild"``) or Kbuild-and-Kconfig conjunction
    (``status="kconfig"``) is unsatisfiable. ``paths`` restricts the objects
    checked (default: every cached object). Each Kconfig check conjoins only
    the closure of Kconfig clauses relevant to the object's own symbols
    (``KconfigConstraints.constraints_for``), not the whole tree's Kconfig
    constraints, so this scales to tens of thousands of objects."""
    paths = sorted(paths if paths is not None else analysis.conds)
    if limit:
        paths = paths[:limit]
    solo = z3.Solver()
    solo.set("timeout", timeout_ms)
    out = []
    for p in paths:
        cond = analysis.conds[p]
        if not isinstance(cond, z3.ExprRef):
            continue
        if z3.is_true(cond):
            continue
        solo.push()
        solo.add(cond)
        r = solo.check()
        solo.pop()
        if r == z3.unsat:
            out.append((p, "kbuild", False))
            continue
        if r == z3.unknown:
            continue  # timed out on Kbuild alone; do not risk a false "dead"
        seed = analysis.symbols(p)
        bare = {s[len("CONFIG_"):] for s in seed if s.startswith("CONFIG_")}
        clauses = kconfig.constraints_for(bare)
        if not clauses:
            continue  # nothing Kconfig-side to add; already known SAT
        s2 = z3.Solver()
        s2.set("timeout", timeout_ms)
        s2.add(cond, *clauses)
        r2 = s2.check()
        if r2 == z3.unsat:
            incomplete = any(not kconfig.declared(s) for s in seed)
            out.append((p, "kconfig", incomplete))
    return out
