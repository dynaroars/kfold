import itertools
from time import time
import pathlib
import pdb

from pymake3 import parser, parserdata, data

import helpers.vcommon as CM
import helpers.zsolver as zsolver

import expansion
from ds import Path, Paths, DepPath

import settings
mlog = CM.getLogger(__name__, settings.logger_level)

DBG = pdb.set_trace


class DepStatementList(BaseStatementList, SymExe):
    def exe(path):
        pass


class ParserData:


class StatementList(ParserData):
    def __init__(self, stmt, solver, mysettings):
        assert isinstance(stmt, parserdata.StatementList), stmt
        super().__init__(stmt, solver, mysettings)

    @classmethod
    def get_clss(cls, stmts):
        clss = []
        for i, stmt in enumerate(stmts):
            mlog.debug("{}/{}. hit {} smt '{}'".format(
                i + 1, len(stmts),  stmt.__class__.__name__,
                stmt.to_source().strip()))
            clss.append((cls.get_cls(stmt), stmt))
        return clss

    def spy_i(self, path, deps):
        stmts = self.stmt
        for cls, stmt in self.get_clss(stmts):
            cls(stmt, self.solver, self.mysettings).spy(path, deps)

    def symexe_i(self, path):

        paths = Paths([path])
        stmts = self.stmt
        for cls, stmt in self.get_clss(stmts):
            paths = cls(stmt, self.solver, self.mysettings).symexe(paths)

        return paths


class SetVariable(ParserData):
    """
    Examples:
    - obj-y := fork.o
    """

    def __init__(self, stmt, solver, mysettings):
        assert isinstance(stmt, parserdata.SetVariable), stmt
        super().__init__(stmt, solver, mysettings)

    def get_names(self, myeval, path):
        nameexp = self.stmt.vnameexp
        names = myeval.do_expansion(nameexp, path.states)
        return names

    def spy_i(self, path, deps):
        assert isinstance(path, DepPath), path

        myeval = expansion.ExpansionSpy(self.solver, self.mysettings)

        names = self.get_names(myeval, path)

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
                temp_path = path.fork(path.cond)
                path.set_var(name, token, val)
                path.merge(temp_path)

        for name, _ in names:
            path.deps.setdefault(name, set()).update(myeval.deps)

    def symexe_i(self, path):
        assert isinstance(path, Path), path

        nameexp = self.stmt.vnameexp
        token = self.stmt.token   # :=
        val = self.stmt.value.strip()

        myeval = expansion.ExpansionSymexe(self.solver, self.mysettings)
        names = myeval.do_expansion(nameexp, path.states)

        # names = [(name, cond)
        #          for name, cond in names if name in self.used_vars]

        unexpanded = token == "="
        if unexpanded:
            vals = [(val, zsolver.T)]
        else:
            vals = myeval.do_val(val, path.states)

        new_paths = Paths()
        for (name, ncond), (val, vcond) in itertools.product(*[names, vals]):
            new_cond = zsolver.conj(path.cond, zsolver.conj(ncond, vcond))
            if self.solver.is_sat(new_cond):
                new_path = path.fork(new_cond)
                new_path.set_var(name, token, val)
                new_paths.append(new_path)

        if not new_paths:
            new_paths.append(path)

        return new_paths


class ConditionBlock(ParserData):
    def __init__(self, stmt, solver, mysettings):
        assert isinstance(stmt, parserdata.ConditionBlock), stmt
        super().__init__(stmt, solver, mysettings)

    def spy_i(self, path, deps):

        if_cond, then_stmts = self.stmt[0]  # if/then branch
        _, deps_ = self.eval_condition(if_cond, path, do_spy=True)
        new_deps = deps | deps_

        # spy on then_stmts
        then_stmts = StatementList(then_stmts, self.solver, self.mysettings)
        then_stmts.spy_i(path, new_deps)

        # then spy on else_stmts
        if len(self.stmt) == 1:  # no else branch, treats as else: empty
            else_stmts = parserdata.StatementList()
        elif len(self.stmt) == 2:  # else branch
            _, else_stmts = self.stmt[1]
        else:
            raise NotImplementedError("{} stmts".format(len(self.stmt)))

        else_stmts = StatementList(else_stmts, self.solver, self.mysettings)
        else_path = path.fork(path.cond)
        else_stmts.spy_i(else_path, new_deps)

        path.merge(else_path)

    def symexe_i(self, path):
        if_cond, then_stmts = self.stmt[0]  # if/then branch
        if_cond = self.eval_condition(if_cond, path, do_spy=False)

        paths = self.add_paths(path, if_cond, then_stmts)

        # else branch
        else_cond = zsolver.neg(if_cond)
        if len(self.stmt) == 1:  # no else branch, treats as else: empty
            else_stmts = parserdata.StatementList()
        elif len(self.stmt) == 2:  # else branch
            _, else_stmts = self.stmt[1]
        else:
            raise NotImplementedError("{} stmts".format(len(self.stmt)))

        paths_ = self.add_paths(path, else_cond, else_stmts)
        paths.extend(paths_)
        return paths

    def add_paths(self, path, cond, stmts):
        assert isinstance(stmts, parserdata.StatementList), stmts
        new_path = self.get_new_path(path, cond)
        if new_path:
            stmt_list = StatementList(stmts, self.solver, self.mysettings)
            paths = stmt_list.symexe(Paths([new_path]))
            return paths
        else:
            return []

    def eval_condition(self, cond, path, do_spy):
        """
        evaluation arguments of the condition and return a Z3 condition
        """
        cls = expansion.ExpansionSpy if do_spy else expansion.ExpansionSymexe
        myeval = cls(self.solver, self.mysettings)

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

        if do_spy:
            return ret_cond, myeval.deps
        else:
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


class Include(ParserData):
    def __init__(self, stmt, solver, mysettings):
        assert isinstance(stmt, parserdata.Include), stmt
        super().__init__(stmt, solver, mysettings)

    def symexe_i(self, path):
        myeval = expansion.ExpansionSymexe(self.solver, self.mysettings)
        exp = myeval.do_expansion(self.stmt.exp, path.states)
        paths = []
        for include_file, include_cond in exp:
            assert include_file, include_file
            assert len(include_file.split()) == 1

            include_file = pathlib.Path(include_file)
            if not include_file.is_file():
                include_file = self.mysettings.main_dir / include_file
                if not include_file.is_file():
                    mlog.warn("include file '{}' does not exist".format(
                        include_file))
                    continue

            new_path = self.get_new_path(path, include_cond)
            if not new_path:
                continue

            stmts = parser.parsestring(include_file.read_text(), include_file)
            stmt_list = StatementList(stmts, self.solver, self.mysettings)
            paths_ = stmt_list.symexe(Paths([new_path]))
            paths.extend(paths_)

        return Paths(paths if paths else [path])


class Rule(ParserData):
    def __init__(self, stmt, solver, mysettings):
        assert isinstance(
            stmt, (parserdata.Rule, parserdata.StaticPatternRule)), stmt
        super().__init__(stmt, solver, mysettings)
        mlog.debug("Ignoring {}: {}".format(
            self.__class__.__name__, self.stmt.to_source().strip()))


class Command(ParserData):
    def __init__(self, stmt, solver, mysettings):
        assert isinstance(stmt, parserdata.Command), stmt
        super().__init__(stmt, solver, mysettings)
        mlog.warn("Ignoring {}: {}".format(
            self.__class__.__name__, self.stmt.to_source().strip()))


class EmptyDirective(ParserData):
    def __init__(self, stmt, solver, mysettings):
        assert isinstance(stmt, parserdata.EmptyDirective), stmt
        super().__init__(stmt, solver, mysettings)
        mlog.warn("Ignoring {}: {}".format(
            self.__class__.__name__, self.stmt.to_source().strip()))
