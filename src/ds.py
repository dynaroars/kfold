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
    def subdir_names(self):
        assert not self.ignorable
        return [d for d in self.valconds
                if d.endswith('/') or self.name.startswith("subdirs-") or self.name == "subdirs"]

    def subdirs_with_cond(self, topdir):
        assert topdir.is_dir(), topdir
        assert not self.ignorable

        res = {}
        for d, cond in self.valconds.items():
            if d.endswith('/') or self.name.startswith("subdirs-") or self.name == "subdirs":
                subdir_path = (topdir / d).resolve()
                if subdir_path in res:
                    res[subdir_path] = zsolver.disj(res[subdir_path], cond)
                else:
                    res[subdir_path] = cond
        return res

    @classmethod
    def get_flavor(cls, token):
        if token in set([":=", "::="]) or token in set(["+="]):
            flavor = cls.SIMPLY
        else:
            assert token == "=", token
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
        # Names actually (re)assigned since this state was created/cloned.
        # A branch clone starts this empty so a ConditionBlock merge only
        # has to rebuild (and re-gate by the branch guard) variables that
        # branch actually touched -- variables neither branch touched are
        # left completely alone, which is what keeps condition sizes from
        # growing at every conditional in the file regardless of relevance.
        self.touched = set()

    def __str__(self):
        ss = (v for v in self.states.values() if not v.ignorable)
        return '; '.join(map(str, ss))

    def clone(self):
        new_states = OrderedDict(
            (name, VarG(v.name, dict(v.valconds), v.flavor, v.mysettings))
            for name, v in self.states.items())
        return self.__class__(new_states, self.mysettings)

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

    def set_var(self, name, token, val, cond, solver):
        assert isinstance(name, str), name
        assert isinstance(token, str) and token, token
        assert isinstance(val, str), val
        assert z3.is_expr(cond), cond
        from census import GLOBAL_METRICS
        GLOBAL_METRICS.set_var_calls += 1

        words = frozenset(val.split())
        old = self.states.get(name)

        if old is None or self.check_token(token):
            # Overwrite ("=", ":="). ``cond`` is the condition under which
            # *this particular* assignment fires (its name/value may itself
            # only resolve this way conditionally, e.g.
            # ``obj-$(CONFIG_A) := 1.o`` only assigns to the variable named
            # "obj-y" when CONFIG_A=y). Outside ``cond`` this statement did
            # not execute against this variable at all, so any prior value
            # must survive there -- a blind replace would incorrectly erase
            # contributions made under other configurations.
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
        return any(t.startswith(x) for x in self.mysettings.target_vars)

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

    @property
    def target_files(self):
        return [self.states[name] for name in self.states
                if self.is_target(name)]

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

        states = {'src': src_dir if isinstance(
            src_dir, VarG) else VarG.src_var(src_dir, mysettings)}
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

    def compute_used_vars(self, target_vars):
        # compute dependency for all files
        dep_d = {}
        for sid in self:
            di = self[sid]
            for name in di.lvals:
                dep_d.setdefault(name, set()).update(
                    di.ldeps | di.rvals | di.rdeps | di.xdeps)
        self.dep_d = dep_d

        # compute dependency for target files
        target_names = [v for v in dep_d
                        if any(v.startswith(x) for x in target_vars)]
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
