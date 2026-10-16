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

import kconfiglib

import kconfig_compat  # noqa: F401  (Kconfig syntax newer than kconfiglib)
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
    arch/<name>/..., else None (common/shared code). ``arch/Kconfig`` itself
    (and any ``arch/Kconfig.*``) is architecture-independent glue included by
    every arch's Kconfig, not a declaration scoped to a pseudo-arch named
    "Kconfig" -- a bug caught during checkpoint verification that would have
    bucketed all ~220 symbols declared there (SMP, KPROBES, HOTPLUG_*, ...)
    as arch-only and never "common"."""
    parts = pathlib.Path(rel_path).parts
    if len(parts) >= 2 and parts[0] == "arch" and not parts[1].startswith("Kconfig"):
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
    """Phi_Kconfig for a tree, built once and reused across many SAT checks,
    on top of the shared, unedited ``tools/kconfig_solver.KconfigSMT`` (its
    final, y/m/n-pair-encoded version: proper bool-never-m and
    tristate-m-requires-MODULES=y semantics, ``dependency_cone`` for a sound
    per-object constraint subset, ``symbol_clauses``/``choice_clauses`` for
    the per-symbol constraints themselves). This wrapper only adds a local
    memo cache over ``symbol_clauses``/``choice_clauses`` (keyed by symbol
    name / choice identity) so a per-object SAT check can reuse clauses
    already derived for a shared symbol instead of ``get_constraints``
    rebuilding them from scratch on every one of ~29k calls.

    ``declared``: whether kconfiglib's parse produced a symbol for CONFIG_X
    (either genuinely undeclared -- already caught by the zombie check -- or
    a parse limitation, e.g. an arch-conditional ``source`` kfold's
    simplified Kconfig walk did not follow). Dead-object findings that
    mention such a symbol are marked ``incomplete=True`` and should not be
    trusted as firm dead code without independently checking that symbol.
    """

    def __init__(self, tree, kconfig_rel="Kconfig", solver=None, env=None,
                 tolerate_missing_glob_sources=True, follow_selects=False):
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
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.solver = solver
        self.follow_selects = follow_selects
        self.known_names = set(self.ksmt.kconf.syms.keys())
        self._sym_clauses = {}
        self._choice_clauses = {}

    def _clauses_for(self, name):
        c = self._sym_clauses.get(name)
        if c is None:
            sym = self.ksmt.kconf.syms.get(name)
            c = self.ksmt.symbol_clauses(sym, self.solver) if sym is not None else []
            self._sym_clauses[name] = c
        return c

    def _choice_clauses_for(self, choice):
        key = id(choice)
        c = self._choice_clauses.get(key)
        if c is None:
            c = self.ksmt.choice_clauses(choice, self.solver)
            self._choice_clauses[key] = c
        return c

    def constraints_for(self, seed_names):
        """The Kconfig clauses relevant to ``seed_names`` (bare names): the
        symbol/choice constraints over ``KconfigSMT.dependency_cone``, a
        sound relaxation (every valid configuration still satisfies it)."""
        cone = self.ksmt.dependency_cone(seed_names, follow_selects=self.follow_selects)
        clauses = []
        seen_choices = set()
        for n in cone:
            clauses.extend(self._clauses_for(n))
            sym = self.ksmt.kconf.syms.get(n)
            if sym is not None and sym.choice is not None and id(sym.choice) not in seen_choices:
                seen_choices.add(id(sym.choice))
                clauses.extend(self._choice_clauses_for(sym.choice))
        return clauses

    def declared(self, config_symbol):
        """Whether kconfiglib's parse produced a symbol for CONFIG_X."""
        if not config_symbol.startswith("CONFIG_"):
            return True
        return config_symbol[len("CONFIG_"):] in self.known_names

    def undefined_here(self, name):
        """True if kconfiglib has no real declaration node for CONFIG_<name>
        under this arch's Kconfig parse -- the exact condition
        ``symbol_clauses`` uses to pin a symbol to n. Independent of
        directory-naming heuristics (which miss cases like
        drivers/acpi/arm64/Kconfig's ACPI_APMT, declared outside any arch/
        directory)."""
        sym = self.ksmt.kconf.syms.get(name)
        return sym is None or not sym.nodes

    _M_ATOM_RE = re.compile(r"CONFIG_(\w+) == m")

    def classify_dead(self, cond, seed, timeout_ms=10000):
        """("arch-dead" | "dead-everywhere", extra) for an object already
        found Kconfig-unsatisfiable (``dead_check``'s "kconfig" status).

        arch-dead: unsatisfiable only because some symbol in the object's
        Kconfig dependency cone is undefined under this arch's parse (a
        foreign-arch symbol, e.g. ARCH_ROCKCHIP, or one declared outside
        arch/ entirely but still arch-specific, e.g. ACPI_APMT); confirmed
        by re-checking SAT with exactly those symbols freed (unconstrained)
        rather than pinned to n. Some cases stay unsat even after freeing
        them (e.g. a symbol whose *only* "select" lives in a foreign arch's
        Kconfig file, which single-arch parsing cannot see at all -- e.g.
        ACPI_APMT is select'd only by "config ARM64 ... select ACPI_APMT if
        ACPI" in arch/arm64/Kconfig); those are classified dead-everywhere
        even though they are, in spirit, still an arch-scope limitation
        rather than genuine dead code -- documented, not auto-detected.

        extra["bool_composite_container"]: the object's own condition
        requires some symbol declared ``bool`` (never modular) to equal
        "m". This is not a real dead-code bug: kfold's Kbuild analyzer
        writes a composite family's own combined object only under the
        family's obj-m branch (Linux links a built-in composite's members
        directly into built-in.a without a combined object of its own), so
        for a family whose top Kconfig symbol happens to be bool (can never
        be "m"), the predicted container object path is structurally
        unreachable even though the member source files are compiled fine
        under a different (obj-y) path. Confirmed to be the dominant
        dead-everywhere sub-cause on v6.6 (net/unix/unix.o needing
        CONFIG_UNIX=m when UNIX is bool, fs/iomap/iomap.o needing
        CONFIG_FS_IOMAP=m when FS_IOMAP is bool, etc.)."""
        cone = self.ksmt.dependency_cone(seed, follow_selects=self.follow_selects)
        undef = sorted(n for n in cone if self.undefined_here(n))
        bool_container = False
        for name in set(self._M_ATOM_RE.findall(str(cond))):
            sym = self.ksmt.kconf.syms.get(name)
            if sym is not None and sym.orig_type == kconfiglib.BOOL:
                bool_container = True
                break
        extra = {"undef_syms": undef, "bool_composite_container": bool_container}
        if not undef:
            return "dead-everywhere", extra
        clauses = []
        for n in cone:
            if n in undef:
                continue
            clauses.extend(self._clauses_for(n))
            sym = self.ksmt.kconf.syms.get(n)
            if sym is not None and sym.choice is not None:
                clauses.extend(self._choice_clauses_for(sym.choice))
        s = z3.Solver()
        s.set("timeout", timeout_ms)
        s.add(cond, *clauses)
        return ("arch-dead" if s.check() == z3.sat else "dead-everywhere"), extra


def dead_check(analysis, kconfig, paths=None, timeout_ms=15000, limit=None):
    """[(path, status, incomplete, cause, extra)] for objects whose Kbuild
    condition (``status="kbuild"``) or Kbuild-and-Kconfig conjunction
    (``status="kconfig"``) is unsatisfiable. ``paths`` restricts the objects
    checked (default: every cached object). Each Kconfig check conjoins only
    the closure of Kconfig clauses relevant to the object's own symbols
    (``KconfigConstraints.constraints_for``), not the whole tree's Kconfig
    constraints, so this scales to tens of thousands of objects.

    ``cause`` (only meaningful for ``status="kconfig"``; "dead-everywhere"
    for ``status="kbuild"``, which has nothing to do with Kconfig/arch at
    all) is ``KconfigConstraints.classify_dead``'s "arch-dead" or
    "dead-everywhere" split; ``extra`` is its accompanying detail dict
    (``undef_syms``, ``bool_composite_container``)."""
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
            out.append((p, "kbuild", False, "dead-everywhere", {}))
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
            cause, extra = kconfig.classify_dead(cond, bare)
            out.append((p, "kconfig", incomplete, cause, extra))
    return out
