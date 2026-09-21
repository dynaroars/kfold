from abc import ABC
import itertools
import pdb

import z3

from pymake3 import parserdata, data

import helpers.vcommon as CM
import helpers.zsolver as zsolver

import expansion
from ds import DState, DepDB

import settings
mlog = CM.getLogger(__name__, settings.logger_level)

DBG = pdb.set_trace


def str_of_sid(sid):
    assert isinstance(sid, tuple), sid
    return ''.join(map(str, sid))


class Statement(ABC):
    """A parsed Make statement.

    Symbolic execution (``sexe``) mutates a single shared ``ds.SState`` in
    place under an ambient ``guard`` (the conjunction of all enclosing
    branch conditions), instead of forking a new ``Path`` object per branch
    and later trying to re-merge/split them. See ``ConditionBlock.sexe`` for
    the one place branching actually happens, and ``ds.BaseState`` for the
    per-word guarded-value representation this relies on. This mirrors the
    branch-and-immediately-merge design used by the sibling ``cybolic``
    (CMake) analyzer's ``exec_branches``/``merge_branches``.
    """

    def __init__(self, stmt, sid):
        assert isinstance(stmt, parserdata.Statement), stmt
        assert isinstance(sid, tuple), sid

        self.stmt = stmt
        self.sid = sid
        self.preds = set()

    def __str__(self):
        return "{} {}: {}".format(
            str_of_sid(self.sid),
            self.__class__.__name__,
            self.stmt_str)

    @property
    def stmt_str(self):
        try:
            return self._stmt_str
        except AttributeError:
            self._stmt_str = self.stmt.to_source().strip()
            return self._stmt_str

    # recursive/traverse ops
    def traverse(self, fn):
        return fn(self)

    @property
    def siz(self):
        return 1

    def show(self):
        print(self.__str__())
        print('preds', self.all_preds)

    def dexe(self, state, deps):
        pass

    def myreduce(self, ddb):
        return self

    def sexe(self, state, guard, ddb):
        """Execute this statement against ``state`` (mutated in place)
        under path condition ``guard``. Statements with no symbolic effect
        (Rule/Command/Include/EmptyDirective for now) are no-ops."""
        pass

    @classmethod
    def create(cls, stmt, sid):
        stmt = cls(stmt, sid)
        return stmt

    def set_preds(self, pred):
        self.preds.add(pred)

    # miscs
    @classmethod
    def get_cls(cls, stmt):
        from census import GLOBAL_METRICS
        if isinstance(stmt, parserdata.SetVariable):
            mycls = SetVariable
            token = getattr(stmt, 'token', '=')
            GLOBAL_METRICS.record_construct(f"SetVariable{token}")

        elif isinstance(stmt, parserdata.ConditionBlock):
            mycls = ConditionBlock
            if len(stmt) > 0 and len(stmt[0]) > 0 and hasattr(stmt[0][0], '__class__'):
                cond_type = stmt[0][0].__class__.__name__.replace("Condition", "").lower()
                GLOBAL_METRICS.record_construct(f"ConditionBlock:{cond_type}")
            else:
                GLOBAL_METRICS.record_construct("ConditionBlock")

        elif isinstance(stmt, parserdata.Rule):
            mycls = Rule
            GLOBAL_METRICS.record_construct("Rule")

        elif isinstance(stmt, parserdata.StaticPatternRule):
            mycls = Rule
            GLOBAL_METRICS.record_construct("StaticPatternRule")

        elif isinstance(stmt, parserdata.Include):
            mycls = Include
            GLOBAL_METRICS.record_construct("Include")

        elif isinstance(stmt, parserdata.Command):
            mycls = Command
            GLOBAL_METRICS.record_construct("Command")

        elif isinstance(stmt, parserdata.EmptyDirective):
            mycls = EmptyDirective
            GLOBAL_METRICS.record_construct("EmptyDirective")

        else:
            GLOBAL_METRICS.record_construct(f"Unknown:{stmt.__class__.__name__}")
            raise NotImplementedError("cannot parse {}".format(stmt))
        return mycls

    def set_solver(self, solver):
        def _set_solver(stmt):
            stmt.solver = solver
            return True

        self.traverse(_set_solver)

    @property
    def all_preds(self):
        try:
            return self._all_preds
        except AttributeError:
            preds = set()

            for mypred in self.preds:
                if mypred is None:
                    continue

                preds_ = mypred.all_preds
                preds.update(preds_)
                preds.add(mypred)

            self._all_preds = preds
            return self._all_preds

    def print_remove(self):
        mlog.debug("remove '{}'".format(self))


class StatementList(Statement):
    def __init__(self, stmts, orig_stmt, sid):
        super().__init__(orig_stmt, sid)
        self.stmts = stmts

    @classmethod
    def create(cls, stmts, sid):
        mystmts = []
        for i, stmt in enumerate(stmts):
            mystmt = cls.get_cls(stmt).create(
                stmt, tuple(list(sid) + [i, ]))
            mystmts.append(mystmt)

        stmt = cls(mystmts, stmts, sid)
        return stmt

    def set_preds(self, pred):
        mypred = pred
        for stmt in self.stmts:
            stmt.set_preds(mypred)
            mypred = stmt

        self.preds.add(mypred)

    def traverse(self, fn):
        if all(stmt.traverse(fn) for stmt in self.stmts):
            return super().traverse(fn)
        else:
            return False

    @property
    def siz(self):
        return sum(stmt.siz for stmt in self.stmts) + super().siz

    def show(self):
        for stmt in self.stmts:
            stmt.show()

    def dexe(self, state, deps):
        for i, stmt in enumerate(self.stmts):
            msg = "{}/{} {}".format(i + 1, len(self.stmts), stmt)
            mlog.debug(msg)
            stmt.dexe(state, deps)

    def myreduce(self, ddb):
        stmts = [stmt.myreduce(ddb) for stmt in self.stmts]
        stmts = [stmt for stmt in stmts if stmt]
        if stmts:
            self.stmts = stmts
            return self
        else:
            self.print_remove()
            return None

    def sexe(self, state, guard, ddb):
        for i, stmt in enumerate(self.stmts):
            mlog.debug("{}/{}. {}".format(i + 1, len(self.stmts), stmt))
            stmt.sexe(state, guard, ddb)


def _merge_branch_states(dest_state, then_state, then_guard, else_state, else_guard):
    """Fold ``then_state``/``else_state`` (each a full clone of the
    pre-conditional state that a branch's statements executed against under
    their own ambient guard) back into ``dest_state``.

    A word's condition inside ``then_state``/``else_state`` only reflects
    the branch's guard for entries a statement *inside that branch* actually
    (re)computed; a value merely carried over unchanged from before the
    branch still carries its pre-branch condition, not one scoped to this
    branch. So every branch's contribution must be explicitly re-gated by
    that branch's own guard here, not just unioned as-is -- otherwise an
    unconditional overwrite inside an if/else (e.g. ``BITS := 32`` /
    ``BITS := 64``) would appear to leave the pre-if value reachable too,
    since each branch's "this specific reassignment didn't fire" carry-over
    (see ``ds.BaseState.set_var``) is only complementary *within that
    branch*, and naively OR-ing the two branches' raw dicts reconstructs the
    pre-branch value instead of eliminating it. Since ``then_guard`` and
    ``else_guard`` are complementary within the enclosing guard, gating and
    re-combining is a no-op for values neither branch touched, and correctly
    zeroes out a branch's contribution for values only the other branch
    established. This mirrors cybolic's ``merge_branches``, which gates each
    branch's whole resulting value by that branch's own condition.

    Only names either branch actually reassigned (``state.touched``) are
    rebuilt; everything else is left as-is in ``dest_state`` so condition
    sizes don't grow at every conditional in the file regardless of
    relevance."""
    from ds import VarG

    names = then_state.touched | else_state.touched
    dest_state.touched |= names
    for name in names:
        then_v = then_state.states.get(name)
        else_v = else_state.states.get(name)
        words = set()
        if then_v is not None:
            words |= set(then_v.valconds)
        if else_v is not None:
            words |= set(else_v.valconds)

        merged = {}
        for word in words:
            parts = []
            if then_v is not None and word in then_v.valconds:
                parts.append(zsolver.conj(then_guard, then_v.valconds[word]))
            if else_v is not None and word in else_v.valconds:
                parts.append(zsolver.conj(else_guard, else_v.valconds[word]))
            cond = zsolver.mdisj(parts)
            if not z3.is_false(cond):  # drop words no reachable branch keeps
                merged[word] = cond

        flavor = (then_v or else_v).flavor
        mysettings = (then_v or else_v).mysettings
        dest_state.states[name] = VarG(name, merged, flavor, mysettings)


class ConditionBlock(Statement):
    def __init__(self, if_cond, then_stmts, else_stmts, orig_stmt, sid):
        super().__init__(orig_stmt, sid)
        self.if_cond = if_cond
        self.then_stmts = then_stmts
        self.else_stmts = else_stmts

    @classmethod
    def get_info(cls, stmt, sid=None):
        if_cond, then_stmts = stmt[0]  # if/then branch
        if len(stmt) == 1:  # no else branch, treats as else: empty
            else_stmts = None
        elif len(stmt) == 2:  # else branch
            _, else_stmts = stmt[1]
        else:
            raise NotImplementedError("{} stmts".format(len(stmt)))

        return if_cond, then_stmts, else_stmts

    @classmethod
    def create(cls, stmt, sid):
        if_cond, then_stmts, else_stmts = cls.get_info(stmt)

        def f(stmts, mid):
            return StatementList.create(stmts, mid) if stmts else None

        then_stmts = f(then_stmts, tuple(list(sid) + [0, ]))
        else_stmts = f(else_stmts, tuple(list(sid) + [1, ]))
        mystmt = cls(if_cond, then_stmts, else_stmts, stmt, sid)
        return mystmt

    def set_preds(self, pred):
        def f(stmts):
            if stmts:
                stmts.set_preds(pred)
                self.preds.add(stmts)

        f(self.then_stmts)
        f(self.else_stmts)

    def traverse(self, fn):
        if ((self.then_stmts is None or self.then_stmts.traverse(fn)) and
                (self.else_stmts is None or self.else_stmts.traverse(fn))):
            return super().traverse(fn)
        else:
            return False

    @property
    def siz(self):
        def f(stmts): return stmts.siz if stmts else 0
        return f(self.then_stmts) + f(self.else_stmts) + super().siz

    def show(self):
        print(self.if_cond.__str__(details=False))
        if self.then_stmts:
            self.then_stmts.show()
        if self.else_stmts:
            self.else_stmts.show()

    def dexe(self, state, deps):
        myeval = expansion.ExpansionDExe(self.solver)
        self.eval_condition(self.if_cond, state, myeval)
        new_deps = deps | myeval.deps

        def f(stmts):
            if stmts:
                stmts.dexe(state, new_deps)
        f(self.then_stmts)
        f(self.else_stmts)

    def myreduce(self, ddb):
        def f(stmts):
            return stmts.myreduce(ddb) if stmts else None

        self.then_stmts = f(self.then_stmts)
        self.else_stmts = f(self.else_stmts)
        if (self.then_stmts or self.else_stmts):
            return self
        else:
            self.print_remove()
            return None

    def sexe(self, state, guard, ddb):
        myeval = expansion.ExpansionSExe(self.solver)
        if_cond = self.eval_condition(self.if_cond, state, myeval)
        not_if_cond = zsolver.neg(if_cond)

        then_guard = zsolver.conj(guard, if_cond)
        else_guard = zsolver.conj(guard, not_if_cond)

        then_state = state.clone()
        if self.then_stmts and self.solver.is_sat(then_guard):
            self.then_stmts.sexe(then_state, then_guard, ddb)

        else_state = state.clone()
        if self.else_stmts and self.solver.is_sat(else_guard):
            self.else_stmts.sexe(else_state, else_guard, ddb)

        _merge_branch_states(state, then_state, then_guard, else_state, else_guard)

    def eval_condition(self, cond, state, myeval):
        """
        evaluation arguments of the condition and return a Z3 condition
        """
        if isinstance(cond, parserdata.EqCondition):
            exps1 = myeval.do_expansion(cond.exp1, state.states)
            exps2 = myeval.do_expansion(cond.exp2, state.states)

            eq_cond = self.get_eq_cond(exps1, exps2)

            ret_cond = eq_cond if cond.expected else zsolver.neg(eq_cond)

        elif isinstance(cond, parserdata.IfdefCondition):
            assert isinstance(cond.exp, data.StringExpansion), cond.exp

            exp = "$({})".format(cond.exp.s)
            exp = myeval.do_fake_expansion(exp, state.states)

            exp_undef = [(self.solver.undef_str, zsolver.T)]
            undef_cond = self.get_eq_cond(exp, exp_undef)

            ret_cond = zsolver.neg(undef_cond) if cond.expected else undef_cond

        else:
            raise NotImplementedError("Cannot parse condition: {}".format(
                cond.to_source()))

        return ret_cond

    @staticmethod
    def get_eq_cond(exps1, exps2):
        """
        Create a condition that represent exps1 == exps2

        1. exps = [('y', CONFIG_A == y), ('m', CONFIG_A == m)]
        2. exps = [('y', CONFIG_B == y), ('m', CONFIG_B == m)]
        3. exps = [('y', T)]
        3a. exps = ['m', T]
        # subs, note 'y' has 2 conds
        4. exps = [('y', CONFIG_B == y), ('y', CONFIG_B == m)]
        5. exps = [('1',f1) , ('2',f2), ('m', f3)]
        6. exps = [('m', f4), ('2', f2a)]

        1,2: CONFIG_A == CONFIG_B =>
        (CONFIG_A == y && CONFIG_B== y) || (CONFIG_A == m && CONFIG_B == m)
        1,3: CONFIG_A == 'y'  =>  CONFIG_A == y
        1,3a:  CONFIG_A == 'm'  =>  CONFIG_A == m
        3,4:  CONFIG_B =y || CONFIG_B == m
        3, 3a:  [] => False
        3, 3:  T
        3a, 4:  [] => False
        5,6:  f3 && f4  or   f2 and f2a
        """
        d1 = {}
        for v, c in exps1:
            if v in d1:
                d1[v] = zsolver.disj(d1[v], c)
            else:
                d1[v] = c

        d2 = {}
        for v, c in exps2:
            if v in d2:
                d2[v] = zsolver.disj(d2[v], c)
            else:
                d2[v] = c

        common_keys = set(d1.keys()) & set(d2.keys())
        if not common_keys:
            return zsolver.F

        terms = [zsolver.conj(d1[k], d2[k]) for k in common_keys]
        return zsolver.mdisj(terms)


class SetVariable(Statement):
    def dexe(self, state, deps):
        assert isinstance(state, DState), state

        myeval = expansion.ExpansionDExe(self.solver)
        nameexp = self.stmt.vnameexp
        names = myeval.do_expansion(nameexp, state.states)

        lvals = frozenset(name for name, _ in names)
        ldeps = frozenset(myeval.deps)
        myeval.deps.clear()

        token = self.stmt.token   # :=
        val = self.stmt.value.strip()
        unexpanded = token == "="
        if unexpanded:
            vals = [(val, zsolver.T)]
        else:
            vals = myeval.do_val(val, state.states)

        rvals = frozenset(itertools.chain(
            *[v.strip().split() for v, _ in vals]))

        rdeps = frozenset(myeval.deps)
        myeval.deps.clear()

        for name, _ in names:
            for val, _ in vals:
                state.set_var(name, token, val, zsolver.T, self.solver)

        state.add_dep(self, lvals, ldeps, rvals, rdeps, deps)

    def myreduce(self, ddb):
        if ddb.skip(self.sid):
            self.print_remove()
            return None
        else:
            return self

    def sexe(self, state, guard, ddb):
        assert not ddb.skip(self.sid)

        myeval = expansion.ExpansionSExe(self.solver)
        nameexp = self.stmt.vnameexp
        names = myeval.do_expansion(nameexp, state.states)

        names_ = []
        for name, cond in names:
            if name in ddb.used_vars:
                names_.append((name, cond))
            else:
                mlog.warn("Ignoring var (likely unused) '{}'".format(name))
        names = names_

        if not names:
            return

        token = self.stmt.token   # :=
        val = self.stmt.value.strip()

        unexpanded = token == "="
        if unexpanded:
            vals = [(val, zsolver.T)]
        else:
            vals = myeval.do_val(val, state.states)

        for name, ncond in names:
            for val, vcond in vals:
                new_cond = zsolver.mconj([guard, ncond, vcond])
                if self.solver.is_sat(new_cond):
                    state.set_var(name, token, val, new_cond, self.solver)


class Rule(Statement):
    def myreduce(self, ddb):
        return None


class Command(Statement):
    def myreduce(self, ddb):
        return None


class Include(Statement):
    def check_skip(self, ddb):
        raise NotImplementedError('check me')


class EmptyDirective(Statement):
    def check_skip(self, ddb):
        raise NotImplementedError('check me')
