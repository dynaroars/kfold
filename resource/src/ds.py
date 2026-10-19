from collections import OrderedDict
import itertools
import pdb

from pymake3 import parserdata
import z3

import settings
import helpers.vcommon as CM
import helpers.zsolver as zsolver


mlog = CM.getLogger(__name__, settings.logger_level)

DBG = pdb.set_trace


class VarG:
    """A Make variable whose value is a set of words, each tagged with the
    Z3 condition under which it is a member. This replaces the old
    per-Path-unconditional ``Var`` (a plain ``frozenset`` of words) --
    conditioning used to come entirely from forking a separate ``Path``
    object per branch (see git history / ds.py before this refactor), which
    is exponential in the number of conditionals. Tagging each word with its
    own condition lets a single ``State`` carry all branches at once.
    """

    RECURSE = "RECURSE"   # =, define
    SIMPLY = "SIMPLY"  # := , ::=, +=

    __slots__ = ("name", "valconds", "flavor", "mysettings")

    def __init__(self, name, valconds, flavor, mysettings):
        assert isinstance(name, str) and name, name
        assert isinstance(valconds, dict), valconds
        assert flavor in (self.RECURSE, self.SIMPLY), flavor
        assert isinstance(mysettings, settings.Settings), mysettings

        self.name = name
        self.valconds = valconds
        self.flavor = flavor
        self.mysettings = mysettings

    @property
    def vals(self):
        return frozenset(self.valconds.keys())

    @property
    def vals_str(self):
        return ' '.join(sorted(map(str, self.vals)))

    @property
    def is_recurse(self):
        return self.flavor == self.RECURSE

    def __str__(self):
        token = "=" if self.flavor == self.RECURSE else ":="
        items = ', '.join(
            "{}[{}]".format(w, self.valconds[w]) for w in sorted(self.valconds))
        return "{} {} {}".format(self.name, token, items)

    @property
    def ignorable(self):
        return self.name in self.mysettings.ignore_vars

    @property
    def is_undef_target(self):  # obj-, lib-
        return self.name in self.mysettings.target_vars

    @property
    def lists_subdirs(self):
        """Variables whose words are directories even without a trailing
        slash: coreboot's subdirs-y and Kbuild's subdir-y/subdir-m."""
        return (self.name.startswith("subdirs-") or self.name == "subdirs"
                or self.name in ("subdir-y", "subdir-m"))

    @property
    def subdir_names(self):
        assert not self.ignorable
        return [d for d in self.valconds
                if d.endswith('/') or self.lists_subdirs]

    def subdirs_with_cond(self, topdir):
        assert topdir.is_dir(), topdir
        assert not self.ignorable

        res = {}
        for d, cond in self.valconds.items():
            if not isinstance(d, str):
                continue
            if d.startswith('-'):
                continue
            if d.endswith('/') or self.lists_subdirs:
                subdir_path = (topdir / d).resolve()
                if subdir_path in res:
                    res[subdir_path] = zsolver.disj(res[subdir_path], cond)
                else:
                    res[subdir_path] = cond
        return res

    @classmethod
    def get_flavor(cls, token):
        if token in set([":=", "::=", "+="]):
            flavor = cls.SIMPLY
        elif token in set(["=", "?="]):
            flavor = cls.RECURSE
        else:
            flavor = cls.RECURSE

        return flavor

    @classmethod
    def src_var(cls, topdir, mysettings):
        assert topdir.is_dir(), topdir
        assert isinstance(mysettings, settings.Settings), mysettings

        return cls("src", {topdir: zsolver.T}, cls.RECURSE, mysettings)


# Backward-compatible alias: some helper/analysis code refers to the
# variable class as ``Var``.
Var = VarG


class BaseState:
    """A single symbolic state (one ``VarG`` per variable name), replacing
    the old ``Paths`` list of mutually exclusive, fully-concrete ``Path``
    objects. Branching (``ConditionBlock``) clones this state for each
    branch, executes each branch against its clone, and merges the two
    clones back into one state (see ``symexe.ConditionBlock.sexe``) instead
    of keeping every branch combination alive as a separate object.
    """

    def __init__(self, states, mysettings):
        assert isinstance(states, dict), states
        assert isinstance(mysettings, settings.Settings), mysettings

        self.states = states
        self.mysettings = mysettings
        self.touched = set()
        self.unsat_blocks = []

    def __str__(self):
        ss = (v for v in self.states.values() if not v.ignorable)
        return '; '.join(map(str, ss))

    def clone(self):
        new_states = OrderedDict(
            (name, VarG(v.name, dict(v.valconds), v.flavor, v.mysettings))
            for name, v in self.states.items())
        cloned = self.__class__(new_states, self.mysettings)
        cloned.unsat_blocks = list(self.unsat_blocks)
        return cloned

    def restrict(self, extra_cond, solver):
        """Return a new state with ``extra_cond`` conjoined onto every
        value's condition, dropping words that become unsatisfiable.
        Replaces the old ``Path.fork(new_cond)``/``Kbuild.fork``."""
        new_states = OrderedDict()
        for name, v in self.states.items():
            new_valconds = {}
            for word, cond in v.valconds.items():
                c = zsolver.conj(cond, extra_cond)
                if solver.is_sat(c):
                    new_valconds[word] = c
            if new_valconds:
                new_states[name] = VarG(
                    v.name, new_valconds, v.flavor, v.mysettings)
        return self.__class__(new_states, self.mysettings)

    def _config_default(self, name, solver):
        """A Kconfig option that a Makefile assigns starts from its value in
        include/config/auto.conf, which the top-level Makefile includes
        before any Kbuild file: U-Boot's tools/Makefile sets CONFIG_CMD_NET = y
        only under ifneq ($(HOST_TOOLS_ALL),), and elsewhere
        $(CONFIG_CMD_NET) is still the option's value."""
        if solver is None or not (self.mysettings.is_copt(name) or self.mysettings.is_xopt(name)):
            return None
        from expansion import config_valconds
        vals = {k: c for k, c in config_valconds(solver, name) if k}
        return VarG(name, vals, VarG.get_flavor("="), self.mysettings) if vals else None

    def set_var_dict(self, name, token, valconds, name_guard, solver):
        assert isinstance(name, str), name
        assert isinstance(token, str) and token, token
        assert isinstance(valconds, dict), valconds
        assert z3.is_expr(name_guard), name_guard
        from census import GLOBAL_METRICS
        GLOBAL_METRICS.set_var_calls += 1

        old = self.states.get(name)
        if old is None:
            old = self._config_default(name, solver)

        if old is None or self.check_token(token):
            if token == "?=":
                if old is not None:
                    old_active = zsolver.mdisj(list(old.valconds.values()))
                    effective_cond = zsolver.conj(name_guard, zsolver.neg(old_active))
                    new_valconds = dict(old.valconds)
                    for w, c in valconds.items():
                        w_cond = zsolver.conj(c, effective_cond)
                        if w in new_valconds:
                            new_valconds[w] = zsolver.disj(new_valconds[w], w_cond)
                        else:
                            new_valconds[w] = w_cond
                else:
                    new_valconds = {w: zsolver.conj(c, name_guard) for w, c in valconds.items()}
            else:
                not_name_guard = zsolver.neg(name_guard)
                new_valconds = {w: zsolver.conj(c, name_guard) for w, c in valconds.items()}
                if old is not None:
                    for w, c in old.valconds.items():
                        carried = zsolver.conj(c, not_name_guard)
                        if w in new_valconds:
                            new_valconds[w] = zsolver.disj(new_valconds[w], carried)
                        else:
                            new_valconds[w] = carried
            flavor = VarG.get_flavor(token)
            if old is None and token == "+=":
                flavor = VarG.RECURSE  # += on an undefined variable acts like =
        else:
            new_valconds = dict(old.valconds)
            for w, c in valconds.items():
                w_cond = zsolver.conj(c, name_guard)
                if w in new_valconds:
                    new_valconds[w] = zsolver.disj(new_valconds[w], w_cond)
                else:
                    new_valconds[w] = w_cond
            flavor = old.flavor

        self.states[name] = VarG(name, new_valconds, flavor, self.mysettings)
        self.touched.add(name)

    def set_var(self, name, token, val, cond, solver):
        assert isinstance(name, str), name
        assert isinstance(token, str) and token, token
        assert isinstance(val, str), val
        assert z3.is_expr(cond), cond
        from census import GLOBAL_METRICS
        GLOBAL_METRICS.set_var_calls += 1

        words = frozenset(val.split())
        old = self.states.get(name)
        if old is None:
            old = self._config_default(name, solver)

        if old is None or self.check_token(token):
            # Overwrite-like assignment (=, :=, ::=, ?=).
            # When the assignment itself is gated by a condition (e.g.
            # inside an `ifeq` block, or because the LHS variable name could
            # only resolve this way conditionally, e.g.
            # ``obj-$(CONFIG_A) := 1.o`` only assigns to the variable named
            # "obj-y" when CONFIG_A=y). Outside ``cond`` this statement did
            # not execute against this variable at all, so any prior value
            # must survive there -- a blind replace would incorrectly erase
            # contributions made under other configurations.
            if token == "?=":
                if old is not None:
                    old_active = zsolver.mdisj(list(old.valconds.values()))
                    effective_cond = zsolver.conj(cond, zsolver.neg(old_active))
                    new_valconds = dict(old.valconds)
                    for w in words:
                        if w in new_valconds:
                            new_valconds[w] = zsolver.disj(new_valconds[w], effective_cond)
                        else:
                            new_valconds[w] = effective_cond
                else:
                    new_valconds = {w: cond for w in words}
            else:
                not_cond = zsolver.neg(cond)
                new_valconds = {w: cond for w in words}
                if old is not None:
                    for w, c in old.valconds.items():
                        carried = zsolver.conj(c, not_cond)
                        if w in new_valconds:
                            new_valconds[w] = zsolver.disj(new_valconds[w], carried)
                        else:
                            new_valconds[w] = carried
            flavor = VarG.get_flavor(token)
        else:
            new_valconds = dict(old.valconds)
            for w in words:
                if w in new_valconds:
                    new_valconds[w] = zsolver.disj(new_valconds[w], cond)
                else:
                    new_valconds[w] = cond
            flavor = old.flavor

        self.states[name] = VarG(name, new_valconds, flavor, self.mysettings)
        self.touched.add(name)

    def is_target(self, t):
        # A target list is a family prefix followed by y, m, or nothing
        # (obj-y, obj-m, obj-); helper variables such as
        # obj-pvrusb2-dvb-y or ramstage-srcs only share the prefix.
        return any(t.startswith(x) and (t[len(x):] in ("", "y", "m")
                                        or t[len(x):] in self.mysettings.root_lists)
                   for x in self.mysettings.target_vars)

    def subdirs_with_cond(self, topdir):
        result = {}
        for name, v in self.states.items():
            if v.ignorable or v.is_undef_target:
                continue
            for subdir, cond in v.subdirs_with_cond(topdir).items():
                if subdir in result:
                    result[subdir] = zsolver.disj(result[subdir], cond)
                else:
                    result[subdir] = cond
        return result

    def expand_deferred(self, solver):
        """Expand the deferred words of target, program, and composite lists
        once the Makefile has been executed, as Kbuild reads those lists
        only after the whole file (GNU Make's recursive variables)."""
        from expansion import ExpansionSExe
        myeval = ExpansionSExe(solver)
        list_suffixes = ("-y", "-m", "-objs", "-lib")
        for name, v in list(self.states.items()):
            if not (self.is_target(name) or is_program_family(name)
                    or name.endswith(list_suffixes)):
                continue
            if not any(isinstance(w, str) and "$" in w for w in v.valconds):
                continue
            new = {}
            for w, c in v.valconds.items():
                parts = [(w, zsolver.T)]
                if isinstance(w, str) and "$" in w and f"({name})" not in w:
                    parts = myeval.do_val(w, self.states)
                for val, vc in parts:
                    for w2 in (val.split() if isinstance(val, str) else [val]):
                        cc = zsolver.conj(c, vc)
                        new[w2] = zsolver.disj(new[w2], cc) if w2 in new else cc
            self.states[name] = VarG(name, new, v.flavor, v.mysettings)

    @property
    def program_files(self):
        return [self.states[name] for name in self.states
                if is_program_family(name)]

    @property
    def target_files(self):
        return [self.states[name] for name in self.states
                if self.is_target(name)]

    def composite_members(self, stem, include_m=True):
        """Constituent objects of composite ``stem.o``: words of ``stem-objs``,
        ``stem-y``, ``stem-m``, and ``stem-lib`` (and their ``.suffix``
        variants), each with its own condition. Target-list variables such as
        ``lib-y`` are never treated as a composite's member list."""
        res = {}
        # Kbuild links foo-m members only into a modular foo.o.
        valid_suffixes = ("-objs", "-y", "-m", "-lib") if include_m else ("-objs", "-y", "-lib")
        for name, var in self.states.items():
            if (not name.startswith(f"{stem}-") or var.ignorable
                    or name == f"{stem}-" or self.is_target(name)):
                continue
            suffix = name[len(stem):]
            if any(suffix == x or suffix.startswith(f"{x}.") for x in valid_suffixes):
                for word, cond in var.valconds.items():
                    if isinstance(word, str) and word.endswith(('.o', '.a')):
                        res[word] = zsolver.disj(res[word], cond) if word in res else cond
        return res

    def resolve_composites(self, solver=None, parent_guard=None):
        """Fixed-point composite resolution for Kbuild objects.
        Recursively resolves composite definitions (foo-objs, foo-y, foo-m)
        and propagates parent and subfeature conditions down to constituent C units.

        Returns:
            dict containing:
                - composite_map: dict of container .o -> dict of constituent .o -> effective Z3 condition
                - compilation_units: dict of leaf atomic .o -> effective Z3 condition
                - composite_units: dict of container .o -> effective Z3 condition
        """
        if parent_guard is None:
            parent_guard = zsolver.T
        if solver is None:
            solver = zsolver.ZSolver(self.mysettings)

        # 1. Identify all top-level target words from target_files (obj-y, obj-m, lib-y, etc.)
        top_targets = {}
        for v in self.target_files:
            if v.is_undef_target:
                continue
            for word, cond in v.valconds.items():
                if not isinstance(word, str) or not word.endswith(('.o', '.a')):
                    continue
                eff_cond = zsolver.conj(parent_guard, cond)
                if solver.is_sat(eff_cond):
                    if word in top_targets:
                        top_targets[word] = zsolver.disj(top_targets[word], eff_cond)
                    else:
                        top_targets[word] = eff_cond

        composite_map = {}       # container.o -> {constituent.o: cond}
        compilation_units = {}   # leaf.o -> cond
        composite_units = {}     # container.o -> cond

        find_composite_valconds = self.composite_members

        worklist = [(obj, cond, (obj,)) for obj, cond in top_targets.items()]

        while worklist:
            obj, obj_cond, chain = worklist.pop(0)
            stem = obj[:-2] if obj.endswith(('.o', '.a')) else obj
            constituents = find_composite_valconds(stem)

            if not constituents:
                if obj in compilation_units:
                    compilation_units[obj] = zsolver.disj(compilation_units[obj], obj_cond)
                else:
                    compilation_units[obj] = obj_cond
            else:
                if obj in composite_units:
                    composite_units[obj] = zsolver.disj(composite_units[obj], obj_cond)
                else:
                    composite_units[obj] = obj_cond

                if obj not in composite_map:
                    composite_map[obj] = {}

                for c_word, c_cond in constituents.items():
                    if c_word in chain:
                        continue  # prevent cycle
                    c_eff_cond = zsolver.conj(obj_cond, c_cond)
                    if solver.is_sat(c_eff_cond):
                        if c_word in composite_map[obj]:
                            composite_map[obj][c_word] = zsolver.disj(composite_map[obj][c_word], c_eff_cond)
                        else:
                            composite_map[obj][c_word] = c_eff_cond

                        worklist.append((c_word, c_eff_cond, chain + (c_word,)))

        return {
            "composite_map": composite_map,
            "compilation_units": compilation_units,
            "composite_units": composite_units,
        }

    def get_units_by_type(self, solver=None, parent_guard=None):
        """Classify extracted makefile entities into semantic categories across Kbuild dialects."""
        if parent_guard is None:
            parent_guard = zsolver.T
        if solver is None:
            solver = zsolver.ZSolver(self.mysettings)

        res_comp = self.resolve_composites(solver, parent_guard)

        host_prefixes = ("hostprogs", "host-progs", "userprogs", "always")
        dialect_prefixes = ("pbl-", "obj-pbl-", "bootblock-", "romstage-", "postcar-", "verstage-", "ramstage-", "smm-", "spl-", "tpl-")
        clean_prefixes = ("clean-files", "clean-dirs", "mrproper-dirs")
        extra_prefixes = ("extra-", "targets")

        hostprog_units = {}
        dialect_units = {}
        clean_files = {}
        extra_targets = {}
        unconfigurable_units = {}

        for name, var in self.states.items():
            if var.ignorable:
                continue

            if var.is_undef_target or name in ("obj-", "lib-", "pbl-"):
                for w, cond in var.valconds.items():
                    if isinstance(w, str) and w.endswith(('.o', '.a')):
                        eff = zsolver.conj(parent_guard, cond)
                        unconfigurable_units[w] = zsolver.disj(unconfigurable_units[w], eff) if w in unconfigurable_units else eff
                continue

            if any(name.startswith(hp) for hp in host_prefixes):
                for w, cond in var.valconds.items():
                    if isinstance(w, str):
                        eff = zsolver.conj(parent_guard, cond)
                        if solver.is_sat(eff):
                            hostprog_units[w] = zsolver.disj(hostprog_units[w], eff) if w in hostprog_units else eff

            elif any(name.startswith(dp) for dp in dialect_prefixes):
                for w, cond in var.valconds.items():
                    if isinstance(w, str) and w.endswith(('.o', '.a')):
                        eff = zsolver.conj(parent_guard, cond)
                        if solver.is_sat(eff):
                            dialect_units[w] = zsolver.disj(dialect_units[w], eff) if w in dialect_units else eff

            elif any(name.startswith(cp) for cp in clean_prefixes):
                for w, cond in var.valconds.items():
                    if isinstance(w, str):
                        eff = zsolver.conj(parent_guard, cond)
                        clean_files[w] = zsolver.disj(clean_files[w], eff) if w in clean_files else eff

            elif any(name.startswith(ep) for ep in extra_prefixes):
                for w, cond in var.valconds.items():
                    if isinstance(w, str):
                        eff = zsolver.conj(parent_guard, cond)
                        if solver.is_sat(eff):
                            extra_targets[w] = zsolver.disj(extra_targets[w], eff) if w in extra_targets else eff

        subdirs = self.subdir_names

        return {
            "compilation_units": res_comp["compilation_units"],
            "composite_units": res_comp["composite_units"],
            "composite_map": res_comp["composite_map"],
            "hostprog_units": hostprog_units,
            "dialect_units": dialect_units,
            "clean_files": clean_files,
            "extra_targets": extra_targets,
            "unconfigurable_units": unconfigurable_units,
            "subdirs": subdirs,
        }

    @property
    def subdir_names(self):
        res = []
        for v in self.states.values():
            if not v.ignorable and not v.is_undef_target:
                res.extend(v.subdir_names)
        return list(dict.fromkeys(res))

    @property
    def vals_d(self):
        return {self.states[name].name: self.states[name].valconds
                for name in self.states}

    def is_not_target(self, t):
        return not self.is_target(t)

    @classmethod
    def get_default(cls, src_dir, mysettings):
        assert isinstance(src_dir, VarG) or src_dir.is_dir(), src_dir
        assert isinstance(mysettings, settings.Settings), mysettings

        if not isinstance(src_dir, VarG) and mysettings.src_dir:
            src_dir = mysettings.maindir / mysettings.src_dir
        states = {'src': src_dir if isinstance(
            src_dir, VarG) else VarG.src_var(src_dir, mysettings)}
        # $(obj) names the Makefile's directory; paths are kept relative to it.
        states['obj'] = VarG('obj', {'.': zsolver.T}, VarG.SIMPLY, mysettings)
        for name, value in mysettings.defines.items():
            states[name] = VarG(name, {w: zsolver.T for w in value.split()},
                                VarG.SIMPLY, mysettings)
        if mysettings.define_guards:
            solver = zsolver.ZSolver(mysettings)
            for name, entries in mysettings.define_guards.items():
                valconds = {}
                for value, sym in entries:
                    zvar, values = solver.get_sort(sym)
                    guard = zvar == values['y']
                    for w in value.split():
                        valconds[w] = zsolver.disj(valconds[w], guard) if w in valconds else guard
                states[name] = VarG(name, valconds, VarG.SIMPLY, mysettings)
        return cls(states, mysettings)

    def to_savable(self):
        """Z3 ``ExprRef`` values are not directly picklable; serialize each
        condition to an SMT2 string (see ``Kbuild.save``/``Kbuild.load``)."""
        return OrderedDict(
            (name, (v.flavor,
                    {word: zsolver.to_smt2_str(cond)
                     for word, cond in v.valconds.items()}))
            for name, v in self.states.items())

    @classmethod
    def from_savable(cls, data, mysettings):
        states = OrderedDict()
        for name, (flavor, wordconds) in data.items():
            valconds = {word: zsolver.from_smt2_str(s)
                        for word, s in wordconds.items()}
            states[name] = VarG(name, valconds, flavor, mysettings)
        return cls(states, mysettings)


class SState(BaseState):
    """Symbolic-execution state (the live analysis state)."""

    @classmethod
    def check_token(cls, token):
        return token in set(["=", ":="])


class DState(BaseState):
    """Dependency-analysis state: a single unconditional pass (no branching
    at all -- this was already effectively single-state before this
    refactor) used to compute which variables are actually read by target
    files, so irrelevant statements can be pruned before symbolic
    execution."""

    def __init__(self, states, mysettings):
        super().__init__(states, mysettings)
        self.ddb = DepDB()  # stmt_hash -> DepInfo

    @classmethod
    def check_token(cls, token):
        return False

    def add_dep(self, stmt, lvals, ldeps, rvals, rdeps, xdeps):
        assert isinstance(
            stmt.sid, tuple) and stmt.sid not in self.ddb, stmt.sid
        self.ddb[stmt.sid] = DepInfo(stmt, lvals, ldeps, rvals, rdeps, xdeps)

    def compute_used_vars(self):
        self.ddb.compute_used_vars(self.mysettings.target_vars)


# Backward-compatible aliases used by a couple of call sites/docstrings.
SPath = SState
DPath = DState


# Kbuild variables listing host or user programs (scripts/Makefile.host,
# scripts/Makefile.userprogs); a program p with p-objs is linked from them.
PROGRAM_FAMILIES = ("hostprogs", "hostprogs-always", "userprogs", "userprogs-always")


def is_program_family(name):
    return any(name == f or name == f + "-y" for f in PROGRAM_FAMILIES)


class DepInfo:
    def __init__(self, stmt, lvals, ldeps, rvals, rdeps, xdeps):
        assert isinstance(lvals, frozenset), lvals
        assert isinstance(ldeps, frozenset), ldeps
        assert isinstance(rvals, frozenset), rvals
        assert isinstance(rdeps, frozenset), rdeps
        assert isinstance(xdeps, frozenset), xdeps

        self.stmt = stmt
        self.lvals = lvals
        self.ldeps = ldeps
        self.rvals = rvals
        self.rdeps = rdeps
        self.xdeps = xdeps

    def __str__(self):
        def _str(fs): return ' '.join(map(str, fs))

        return "{} -> {}, {}; {}, {}; {}".format(
            self.stmt.stmt.to_source().strip(),
            _str(self.lvals), _str(self.ldeps),
            _str(self.rvals), _str(self.rdeps),
            _str(self.xdeps))


class DepDB(OrderedDict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.extra_roots = set()

    def __str__(self):
        return '\n'.join("{}: {}".format(
            ','.join(map(str, sid)), self[sid]) for sid in self)

    def skip(self, sid):
        if sid not in self:
            return False

        di = self[sid]
        assert isinstance(di.stmt.stmt, parserdata.SetVariable), \
            di.stmt.stmt.to_source().strip()

        return all(name not in self.used_vars for name in di.lvals)

    @property
    def lvals(self):
        lvals_ = set()
        for di in self.values():
            lvals_.update(di.lvals)
        return lvals_

    ARTIFACT_PREFIXES = (
        "obj-", "lib-",
        "hostprogs", "host-progs", "userprogs", "always",
        "pbl-", "obj-pbl-", "bootblock-", "romstage-", "postcar-", "verstage-", "ramstage-", "smm-", "spl-", "tpl-",
        "clean-files", "clean-dirs", "mrproper-dirs",
        "extra-", "targets", "subdir-y", "subdir-m"
    )

    def compute_used_vars(self, target_vars):
        # compute dependency for all files
        dep_d = {}
        for sid in self:
            di = self[sid]
            for name in di.lvals:
                dep_d.setdefault(name, set()).update(
                    di.ldeps | di.rvals | di.rdeps | di.xdeps)
        self.dep_d = dep_d

        # compute dependency for target files and all recognized artifact kinds
        combined_prefixes = tuple(set(target_vars) | set(self.ARTIFACT_PREFIXES))
        target_names = [v for v in dep_d
                        if any(v.startswith(x) for x in combined_prefixes)]

        # Variables that rules and sub-make recipes reference.
        target_names += [v for v in self.extra_roots if v in dep_d and v not in target_names]

        # Also find composite variables for any .o targets (e.g. foo.o -> foo-objs, foo-y, foo-m)
        composite_stems = set()
        for tname in target_names:
            for word in dep_d.get(tname, set()):
                if isinstance(word, str) and word.endswith('.o'):
                    composite_stems.add(word[:-2])
                elif (isinstance(word, str) and is_program_family(tname)
                      and "$" not in word):
                    # host/user program: its objects are listed in word-objs
                    composite_stems.add(word)

        prev_stems_count = -1
        while len(composite_stems) > prev_stems_count:
            prev_stems_count = len(composite_stems)
            extra_vars = [v for v in dep_d if any(v.startswith(f"{stem}-") for stem in composite_stems)]
            for evar in extra_vars:
                if evar not in target_names:
                    target_names.append(evar)
                for word in dep_d.get(evar, set()):
                    if isinstance(word, str) and word.endswith('.o'):
                        composite_stems.add(word[:-2])

        dep_t = {}
        for name in target_names:
            deps = set()
            self.find_deps(name, deps)
            dep_t[name] = deps

        # compute vars that are required by target files
        used_vars = [dep_t[name] for name in dep_t]
        used_vars.append(list(dep_t.keys()))

        # also consider name if name is assigned to a subdir, e.g.,
        # libs-y := subdir/
        used_vars.append(name for name in dep_d
                         if any(isinstance(d, str) and d.endswith('/')
                                for d in dep_d[name]))

        self.used_vars = frozenset(itertools.chain(*used_vars))

    def find_deps(self, name, deps):
        assert name in self.dep_d, name

        dep_names = set()
        for dname in self.dep_d[name]:
            if dname not in deps:
                dep_names.add(dname)
            #     mlog.warn('Potential dep cycle: {}'.format(dname))
            # else:

        deps.update(dep_names)
        for dname in dep_names:
            if dname not in self.dep_d:
                continue
            self.find_deps(dname, deps)
