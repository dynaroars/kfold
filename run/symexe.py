from abc import ABC
import itertools
import pathlib
from time import time
import pdb

from pymake3 import parser, parserdata, data

import helpers.vcommon as CM
import helpers.zsolver as zsolver

import expansion
from ds import SPath, DPath, Paths, DepDB

import settings
mlog = CM.getLogger(__name__, settings.logger_level)

DBG = pdb.set_trace


def str_of_sid(sid):
    assert isinstance(sid, tuple), sid
    return ''.join(map(str, sid))


class Statement(ABC):
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

    def dexe(self, path, deps):
        pass

    def myreduce(self, ddb):
        return self

    def sexe(self, paths, ddb):
        st = time()
        new_paths = Paths()
        for path in paths:
            try:
                new_paths_ = self.sexe_i(path, ddb)
            except NotImplementedError as ex:
                mlog.warn(ex)
                new_paths_ = Paths([path])

            if not new_paths_:
                new_paths_ = Paths([path])

            new_paths.extend(new_paths_)

        et_mk = time() - st

        if settings.detail:
            print('--- ORIG --- ({} paths)'.format(len(paths)))
            print(paths)
            print('--- NEW --- ({} paths)'.format(len(new_paths)))
            print(new_paths)

        st_split = time()
        split_paths = new_paths.split()
        et_split = time() - st_split

        if settings.detail:
            print('--- SPLIT --- ({} paths)'.format(len(split_paths)))
            print(split_paths)

        st_merge = time()
        merge_paths = split_paths.merge()
        et_merge = time() - st_merge

        if settings.detail:
            print("--- MERGE --- ({} paths):\n{}".format(
                len(merge_paths), merge_paths))

        mlog.debug("paths: orig {}, new {} ({:2f}), "
                   "split {} ({:02f}), "
                   "merge {} ({:02f}), "
                   "mem {}, configs {}, time {:02f}".format(
                       len(paths),
                       len(new_paths), et_mk,
                       len(split_paths), et_split,
                       len(merge_paths), et_merge,
                       SPath.__ct__,
                       len(zsolver.ZSolver.__config_vars__),
                       time() - st))
        return merge_paths

    def sexe_i(self, path, ddb):
        mlog.warn('Skipping {}. {}'.format(
            self.__class__.__name__, self.stmt_str))
        return Paths()

    @classmethod
    def create(cls, stmt, sid):
        stmt = cls(stmt, sid)
        return stmt

    def set_preds(self, pred):
        self.preds.add(pred)

    # miscs
    @classmethod
    def get_cls(cls, stmt):
        if isinstance(stmt, parserdata.SetVariable):
            mycls = SetVariable

        elif isinstance(stmt, parserdata.ConditionBlock):
            mycls = ConditionBlock

        elif isinstance(
                stmt, (parserdata.Rule, parserdata.StaticPatternRule)):
            mycls = Rule

        elif isinstance(stmt, parserdata.Include):
            mycls = Include

        elif isinstance(stmt, parserdata.Command):
            mycls = Command

        elif isinstance(stmt, parserdata.EmptyDirective):
            mycls = EmptyDirective

        else:
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

    def get_new_path(self, path, cond):
        newcond = zsolver.conj(path.cond, cond)
        return path.fork(newcond) if self.solver.is_sat(newcond) else None


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

    def dexe(self, path, deps):
        for i, stmt in enumerate(self.stmts):
            msg = "{}/{} {}".format(i + 1, len(self.stmts), stmt)
            mlog.debug(msg)
            stmt.dexe(path, deps)

    def myreduce(self, ddb):
        stmts = [stmt.myreduce(ddb) for stmt in self.stmts]
        stmts = [stmt for stmt in stmts if stmt]
        if stmts:
            self.stmts = stmts
            return self
        else:
            self.print_remove()
            return None

    def sexe(self, paths, ddb):
        assert isinstance(paths, Paths) and paths, paths
        assert isinstance(ddb, DepDB), ddb

        for i, stmt in enumerate(self.stmts):
            msg = "{}/{}. {} paths hitting {}".format(
                i + 1, len(self.stmts), len(paths), stmt)
            mlog.debug(msg)
            paths = stmt.sexe(paths, ddb)

        return paths


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

    def dexe(self, path, deps):
        myeval = expansion.ExpansionDExe(self.solver)
        self.eval_condition(self.if_cond, path, myeval)
        new_deps = deps | myeval.deps

        def f(stmts):
            if stmts:
                stmts.dexe(path, new_deps)
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

    def sexe_i(self, path, ddb):
        myeval = expansion.ExpansionSExe(self.solver)
        if_cond = self.eval_condition(self.if_cond, path, myeval)

        paths_then = self.get_new_paths(path, if_cond, self.then_stmts, ddb)
        paths_else = self.get_new_paths(
            path, zsolver.neg(if_cond), self.else_stmts, ddb)

        paths = Paths()
        paths.extend(paths_then)
        paths.extend(paths_else)
        return paths

    def get_new_paths(self, path, cond, stmts, ddb):
        newcond = zsolver.conj(path.cond, cond)
        if not self.solver.is_sat(newcond):
            return Paths()

        paths = Paths([path.fork(newcond)])
        return stmts.sexe(paths, ddb) if stmts else paths

    def eval_condition(self, cond, path, myeval):
        """
        evaluation arguments of the condition and return a Z3 condition
        """
        if isinstance(cond, parserdata.EqCondition):
            exps1 = myeval.do_expansion(cond.exp1, path.states)
            exps2 = myeval.do_expansion(cond.exp2, path.states)

            eq_cond = self.get_eq_cond(exps1, exps2)

            ret_cond = eq_cond if cond.expected else zsolver.neg(eq_cond)

        elif isinstance(cond, parserdata.IfdefCondition):
            assert isinstance(cond.exp, data.StringExpansion), cond.exp

            exp = "$({})".format(cond.exp.s)
            exp = myeval.do_fake_expansion(exp, path.states)

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
        keys1 = set([v for v, _ in exps1])
        keys2 = set([v for v, _ in exps2])
        keys = set.intersection(keys1, keys2)

        merge_d = {}
        for v, c in exps1 + exps2:
            if v not in keys:
                continue
            merge_d.setdefault(v, []).append(c)

        assert all(len(merge_d[k]) >= 2 for k in merge_d), merge_d

        disjs = [zsolver.mconj(cs) for cs in merge_d.values()]
        if not disjs:
            return zsolver.F
        elif len(disjs) == 1:
            return disjs[0]
        else:
            assert all(disj is not zsolver.T for disj in disjs), disjs
            return zsolver.mdisj(disjs)


class SetVariable(Statement):
    def dexe(self, path, deps):
        assert isinstance(path, DPath), path

        myeval = expansion.ExpansionDExe(self.solver)
        nameexp = self.stmt.vnameexp
        names = myeval.do_expansion(nameexp, path.states)

        lvals = frozenset(name for name, _ in names)
        ldeps = frozenset(myeval.deps)
        myeval.deps.clear()

        token = self.stmt.token   # :=
        val = self.stmt.value.strip()
        unexpanded = token == "="
        if unexpanded:
            vals = [(val, zsolver.T)]
        else:
            vals = myeval.do_val(val, path.states)

        rvals = frozenset(itertools.chain(
            *[v.strip().split() for v, _ in vals]))

        rdeps = frozenset(myeval.deps)
        myeval.deps.clear()

        for (name, ncond), (val, vcond) in itertools.product(*[names, vals]):
            new_cond = zsolver.conj(path.cond, zsolver.conj(ncond, vcond))
            if self.solver.is_sat(new_cond):
                path.set_var(name, token, val)

        path.add_dep(self, lvals, ldeps, rvals, rdeps, deps)

    def myreduce(self, ddb):
        if ddb.skip(self.sid):
            self.print_remove()
            return None
        else:
            return self

    def sexe_i(self, path, ddb):
        assert isinstance(path, SPath), path

        assert not ddb.skip(self.sid)

        myeval = expansion.ExpansionSExe(self.solver)
        nameexp = self.stmt.vnameexp
        names = myeval.do_expansion(nameexp, path.states)

        names_ = []
        for name, cond in names:
            if name in ddb.used_vars:
                names_.append((name, cond))
            else:
                mlog.warn("Ignoring var (likely unused) '{}'".format(name))
        names = names_

        new_paths = Paths()
        if not names:
            return new_paths

        token = self.stmt.token   # :=
        val = self.stmt.value.strip()

        unexpanded = token == "="
        if unexpanded:
            vals = [(val, zsolver.T)]
        else:
            vals = myeval.do_val(val, path.states)

        for (name, ncond), (val, vcond) in itertools.product(*[names, vals]):
            new_cond = zsolver.conj(path.cond, zsolver.conj(ncond, vcond))
            if self.solver.is_sat(new_cond):
                new_path = path.fork(new_cond)
                new_path.set_var(name, token, val)
                new_paths.append(new_path)
        return new_paths


class Rule(Statement):
    def myreduce(self, ddb):
        return None


class Command(Statement):
    def myreduce(self, ddb):
        return None


class Include(Statement):
    def check_skip(self, ddb):
        raise NotImplementedError('check me')

    # def sexe_i(self, path, ddb):
    #     myeval = expansion.ExpansionSExe(self.solver)
    #     exp = myeval.do_expansion(self.stmt.exp, path.states)
    #     new_paths = Paths()
    #     for include_file, include_cond in exp:
    #         assert include_file, include_file
    #         assert len(include_file.split()) == 1

    #         include_file = pathlib.Path(include_file)
    #         if not include_file.is_file():
    #             include_file = self.solver.mysettings.main_dir / include_file
    #             if not include_file.is_file():
    #                 mlog.warn("include file '{}' does not exist".format(
    #                     include_file))
    #                 continue

    #         new_path = self.get_new_path(path, include_cond)
    #         if not new_path:
    #             continue

    #         stmts = parser.parsestring(include_file.read_text(), include_file)
    #         stmt_list = StatementList(stmts, self.solver, self.mysettings)
    #         paths = stmt_list.sexe(Paths([new_path]), ddb)
    #         new_paths.extend(paths)

    #     return new_paths


class EmptyDirective(Statement):
    def check_skip(self, ddb):
        raise NotImplementedError('check me')


# class MyStmt(ABC):
#     def __init__(self, stmt, solver, mysettings):
#         assert isinstance(stmt, parserdata.Statement), stmt
#         assert isinstance(solver, zsolver.ZSolver), solver
#         assert isinstance(mysettings, settings.Settings), mysettings

#         self.stmt = stmt
#         self.solver = solver
#         self.mysettings = mysettings

#     def get_sid(self):
#         try:
#             return self.stmt.sid
#         except AttributeError:
#             assert isinstance(self.stmt, parserdata.StatementList)
#             return None

#     def set_sid(self, sid):
#         assert isinstance(sid, tuple), sid
#         assert self.sid is None, self.sid
#         self.stmt.sid = sid

#     sid = property(get_sid, set_sid)

#     def dexe(self, path, deps):
#         assert isinstance(path, DPath), path
#         assert isinstance(deps, frozenset), deps
#         try:
#             self.dexe_i(path, deps)
#         except NotImplementedError as ex:
#             mlog.warn(ex)

#     def dexe_i(self, path, deps):
#         assert isinstance(path, DPath), path
#         assert isinstance(deps, frozenset), deps
#         return self

#     def sexe(self, paths, ddb):
#         assert isinstance(paths, Paths) and paths, paths
#         assert isinstance(ddb, DepDB), ddb

#         if ddb.skip(self.sid):
#             mlog.warn("Ignoring unused stmt '{}'".format(
#                 self.stmt.to_source().strip()))
#             return paths

#         st = time()
#         new_paths = Paths()
#         for path in paths:
#             try:
#                 new_paths_ = self.sexe_i(path, ddb)
#             except NotImplementedError as ex:
#                 mlog.warn(ex)
#                 new_paths_ = Paths([path])

#             if not new_paths_:
#                 new_paths_ = Paths([path])

#             new_paths.extend(new_paths_)

#         assert new_paths
#         if isinstance(self, StatementList):
#             return new_paths

#         et_mk = time() - st

#         if settings.detail:
#             print('--- ORIG --- ({} paths)'.format(len(paths)))
#             print(paths)
#             print('--- NEW --- ({} paths)'.format(len(new_paths)))
#             print(new_paths)

#         st_split = time()
#         split_paths = new_paths.split()
#         et_split = time() - st_split

#         if settings.detail:
#             print('--- SPLIT --- ({} paths)'.format(len(split_paths)))
#             print(split_paths)

#         st_merge = time()
#         merge_paths = split_paths.merge()
#         et_merge = time() - st_merge

#         if settings.detail:
#             print("--- MERGE --- ({} paths):\n{}".format(
#                 len(merge_paths), merge_paths))

#         mlog.debug("paths: orig {}, new {} ({:2f}), "
#                    "split {} ({:02f}), "
#                    "merge {} ({:02f}), "
#                    "mem {}, configs {}, time {:02f}".format(
#                        len(paths),
#                        len(new_paths), et_mk,
#                        len(split_paths), et_split,
#                        len(merge_paths), et_merge,
#                        SPath.__ct__,
#                        len(zsolver.ZSolver.__config_vars__),
#                        time() - st))
#         return merge_paths

#     def sexe_i(self, path, ddb):
#         return Paths()

#     def get_new_path(self, path, cond):
#         newcond = zsolver.conj(path.cond, cond)
#         return path.fork(newcond) if self.solver.is_sat(newcond) else None


# class StatementList(MyStmt):
#     def __init__(self, stmt, solver, mysettings):
#         assert isinstance(stmt, parserdata.StatementList), stmt
#         super().__init__(stmt, solver, mysettings)

#     @classmethod
#     def get_cls(cls, stmt):
#         if isinstance(stmt, parserdata.SetVariable):
#             cls = SetVariable

#         elif isinstance(stmt, parserdata.ConditionBlock):
#             cls = ConditionBlock

#         elif isinstance(
#                 stmt, (parserdata.Rule, parserdata.StaticPatternRule)):
#             cls = Rule

#         elif isinstance(stmt, parserdata.Include):
#             cls = Include

#         elif isinstance(stmt, parserdata.Command):
#             cls = Command

#         elif isinstance(stmt, parserdata.EmptyDirective):
#             cls = EmptyDirective

#         else:
#             raise NotImplementedError("cannot parse {}".format(stmt))

#         return cls

#     def get_clss(self, stmts):

#         for i, stmt in enumerate(stmts):
#             sid = tuple(list(self.sid) + [i, ])
#             msg = "{}/{}. {}, {} '{}'".format(
#                 i + 1, len(stmts),
#                 sid,
#                 stmt.__class__.__name__,
#                 stmt.to_source().strip())
#             yield msg, self.get_cls(stmt), stmt, sid

#     def dexe_i(self, path, deps):

#         stmts = self.stmt
#         for msg, cls, stmt, sid in self.get_clss(stmts):
#             mlog.debug(msg)
#             mystmt = cls(stmt, self.solver, self.mysettings)
#             mystmt.sid = sid
#             mystmt.dexe(path, deps)

#     def sexe_i(self, path, ddb):

#         paths = Paths([path])
#         stmts = self.stmt
#         for msg, cls, stmt, sid in self.get_clss(stmts):
#             assert stmt.sid == sid
#             mlog.debug(msg)
#             paths = cls(stmt, self.solver, self.mysettings).sexe(
#                 paths, ddb)

#         return paths


# class SetVariable(MyStmt):
#     """
#     Examples:
#     - obj-y := fork.o
#     """

#     def __init__(self, stmt, solver, mysettings):
#         assert isinstance(stmt, parserdata.SetVariable), stmt
#         super().__init__(stmt, solver, mysettings)

#     def dexe_i(self, path, deps):
#         assert isinstance(path, DPath), path

#         myeval = expansion.ExpansionDExe(self.solver, self.mysettings)
#         nameexp = self.stmt.vnameexp
#         names = myeval.do_expansion(nameexp, path.states)

#         lvals = frozenset(name for name, _ in names)
#         ldeps = frozenset(myeval.deps)
#         myeval.deps.clear()

#         token = self.stmt.token   # :=
#         val = self.stmt.value.strip()
#         unexpanded = token == "="
#         if unexpanded:
#             vals = [(val, zsolver.T)]
#         else:
#             vals = myeval.do_val(val, path.states)

#         rvals = frozenset(itertools.chain(
#             *[v.strip().split() for v, _ in vals]))

#         rdeps = frozenset(myeval.deps)
#         myeval.deps.clear()

#         for (name, ncond), (val, vcond) in itertools.product(*[names, vals]):
#             new_cond = zsolver.conj(path.cond, zsolver.conj(ncond, vcond))
#             if self.solver.is_sat(new_cond):
#                 path.set_var(name, token, val)

#         # TODO: remove self.sid
#         path.add_dep(self.stmt, self.sid, lvals, ldeps, rvals, rdeps, deps)

#     def sexe_i(self, path, ddb):
#         assert isinstance(path, SPath), path
#         myeval = expansion.ExpansionSExe(self.solver, self.mysettings)
#         nameexp = self.stmt.vnameexp
#         names = myeval.do_expansion(nameexp, path.states)

#         names_ = []
#         for name, cond in names:
#             if name in ddb.used_vars:
#                 names_.append((name, cond))
#             else:
#                 mlog.warn("Ignoring var (likely unused) '{}'".format(name))
#         names = names_

#         new_paths = Paths()
#         if not names:
#             return new_paths

#         token = self.stmt.token   # :=
#         val = self.stmt.value.strip()

#         unexpanded = token == "="
#         if unexpanded:
#             vals = [(val, zsolver.T)]
#         else:
#             vals = myeval.do_val(val, path.states)

#         for (name, ncond), (val, vcond) in itertools.product(*[names, vals]):
#             new_cond = zsolver.conj(path.cond, zsolver.conj(ncond, vcond))
#             if self.solver.is_sat(new_cond):
#                 new_path = path.fork(new_cond)
#                 new_path.set_var(name, token, val)
#                 new_paths.append(new_path)
#         return new_paths


# class ConditionBlock(MyStmt):
#     def __init__(self, stmt, solver, mysettings):
#         assert isinstance(stmt, parserdata.ConditionBlock), stmt
#         super().__init__(stmt, solver, mysettings)

#     def get_info(self):
#         if_cond, then_stmts = self.stmt[0]  # if/then branch
#         if len(self.stmt) == 1:  # no else branch, treats as else: empty
#             else_stmts = parserdata.StatementList()
#         elif len(self.stmt) == 2:  # else branch
#             _, else_stmts = self.stmt[1]
#         else:
#             raise NotImplementedError("{} stmts".format(len(self.stmt)))

#         then_sid = tuple(list(self.sid) + [0, ])
#         else_sid = tuple(list(self.sid) + [1, ])
#         return if_cond, then_stmts, then_sid, else_stmts, else_sid

#     def dexe_i(self, path, deps):
#         if_cond, then_stmts, then_sid, else_stmts, else_sid = self.get_info()

#         myeval = expansion.ExpansionDExe(self.solver, self.mysettings)
#         self.eval_condition(if_cond, path, myeval)
#         new_deps = deps | myeval.deps

#         # dexe on then_stmts

#         then_stmts = StatementList(then_stmts, self.solver, self.mysettings)
#         then_stmts.sid = then_sid
#         then_stmts.dexe_i(path, new_deps)

#         else_stmts = StatementList(else_stmts,  self.solver, self.mysettings)
#         else_stmts.sid = else_sid
#         else_stmts.dexe_i(path, new_deps)

#     def sexe_i(self, path, ddb):
#         if_cond, then_stmts, then_sid, else_stmts, else_sid = self.get_info()

#         myeval = expansion.ExpansionSExe(self.solver, self.mysettings)
#         if_cond = self.eval_condition(if_cond, path, myeval)

#         paths_then = self.add_paths(path, if_cond, then_stmts, then_sid, ddb)
#         paths_else = self.add_paths(
#             path, zsolver.neg(if_cond), else_stmts, else_sid, ddb)

#         return paths_then + paths_else

#     def add_paths(self, path, cond, stmts, sid, ddb):
#         assert isinstance(stmts, parserdata.StatementList), stmts

#         new_path = self.get_new_path(path, cond)
#         if new_path:
#             stmtlist = StatementList(stmts, self.solver, self.mysettings)
#             #assert stmtlist.sid == sid, (stmtlist.sid, sid)
#             return stmtlist.sexe(Paths([new_path]), ddb)
#         else:
#             return Paths()

#     def eval_condition(self, cond, path, myeval):
#         """
#         evaluation arguments of the condition and return a Z3 condition
#         """
#         if isinstance(cond, parserdata.EqCondition):
#             exps1 = myeval.do_expansion(cond.exp1, path.states)
#             exps2 = myeval.do_expansion(cond.exp2, path.states)

#             eq_cond = self.get_eq_cond(exps1, exps2)

#             ret_cond = eq_cond if cond.expected else zsolver.neg(eq_cond)

#         elif isinstance(cond, parserdata.IfdefCondition):
#             assert isinstance(cond.exp, data.StringExpansion), cond.exp

#             exp = "$({})".format(cond.exp.s)
#             exp = myeval.do_fake_expansion(exp, path.states)

#             exp_undef = [(self.solver.undef_str, zsolver.T)]
#             undef_cond = self.get_eq_cond(exp, exp_undef)

#             ret_cond = zsolver.neg(undef_cond) if cond.expected else undef_cond

#         else:
#             raise NotImplementedError("Cannot parse condition: {}".format(
#                 cond.to_source()))

#         return ret_cond

#     @staticmethod
#     def get_eq_cond(exps1, exps2):
#         """
#         Create a condition that represent exps1 == exps2

#         1. exps = [('y', CONFIG_A == y), ('m', CONFIG_A == m)]
#         2. exps = [('y', CONFIG_B == y), ('m', CONFIG_B == m)]
#         3. exps = [('y', T)]
#         3a. exps = ['m', T]
#         # subs, note 'y' has 2 conds
#         4. exps = [('y', CONFIG_B == y), ('y', CONFIG_B == m)]
#         5. exps = [('1',f1) , ('2',f2), ('m', f3)]
#         6. exps = [('m', f4), ('2', f2a)]

#         1,2: CONFIG_A == CONFIG_B =>
#         (CONFIG_A == y && CONFIG_B== y) || (CONFIG_A == m && CONFIG_B == m)
#         1,3: CONFIG_A == 'y'  =>  CONFIG_A == y
#         1,3a:  CONFIG_A == 'm'  =>  CONFIG_A == m
#         3,4:  CONFIG_B =y || CONFIG_B == m
#         3, 3a:  [] => False
#         3, 3:  T
#         3a, 4:  [] => False
#         5,6:  f3 && f4  or   f2 and f2a
#         """
#         keys1 = set([v for v, _ in exps1])
#         keys2 = set([v for v, _ in exps2])
#         keys = set.intersection(keys1, keys2)

#         merge_d = {}
#         for v, c in exps1 + exps2:
#             if v not in keys:
#                 continue
#             merge_d.setdefault(v, []).append(c)

#         assert all(len(merge_d[k]) >= 2 for k in merge_d), merge_d

#         disjs = [zsolver.mconj(cs) for cs in merge_d.values()]
#         if not disjs:
#             return zsolver.F
#         elif len(disjs) == 1:
#             return disjs[0]
#         else:
#             assert all(disj is not zsolver.T for disj in disjs), disjs
#             return zsolver.mdisj(disjs)


# class Include(MyStmt):
#     def __init__(self, stmt, solver, mysettings):
#         assert isinstance(stmt, parserdata.Include), stmt
#         super().__init__(stmt, solver, mysettings)

#     def sexe_i(self, path, ddb):
#         myeval = expansion.ExpansionSExe(self.solver, self.mysettings)
#         exp = myeval.do_expansion(self.stmt.exp, path.states)
#         new_paths = Paths()
#         for include_file, include_cond in exp:
#             assert include_file, include_file
#             assert len(include_file.split()) == 1

#             include_file = pathlib.Path(include_file)
#             if not include_file.is_file():
#                 include_file = self.mysettings.main_dir / include_file
#                 if not include_file.is_file():
#                     mlog.warn("include file '{}' does not exist".format(
#                         include_file))
#                     continue

#             new_path = self.get_new_path(path, include_cond)
#             if not new_path:
#                 continue

#             stmts = parser.parsestring(include_file.read_text(), include_file)
#             stmt_list = StatementList(stmts, self.solver, self.mysettings)
#             paths = stmt_list.sexe(Paths([new_path]), ddb)
#             new_paths.extend(paths)

#         return new_paths


# class Rule(MyStmt):
#     def __init__(self, stmt, solver, mysettings):
#         assert isinstance(
#             stmt, (parserdata.Rule, parserdata.StaticPatternRule)), stmt
#         super().__init__(stmt, solver, mysettings)
#         mlog.debug("Ignoring {}: {}".format(
#             self.__class__.__name__, self.stmt.to_source().strip()))


# class Command(MyStmt):
#     def __init__(self, stmt, solver, mysettings):
#         assert isinstance(stmt, parserdata.Command), stmt
#         super().__init__(stmt, solver, mysettings)
#         mlog.warn("Ignoring {}: {}".format(
#             self.__class__.__name__, self.stmt.to_source().strip()))


# class EmptyDirective(MyStmt):
#     def __init__(self, stmt, solver, mysettings):
#         assert isinstance(stmt, parserdata.EmptyDirective), stmt
#         super().__init__(stmt, solver, mysettings)
#         mlog.warn("Ignoring {}: {}".format(
#             self.__class__.__name__, self.stmt.to_source().strip()))
