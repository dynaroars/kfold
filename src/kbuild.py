from collections import OrderedDict
import itertools
from time import time
import os.path
import pathlib
import pdb

from pymake3 import parser, parserdata, data, functions

import helpers.vcommon as CM
import helpers.zsolver as zsolver

from casestudy import CaseStudy
from ds import Path, Paths

import settings
mlog = CM.getLogger(__name__, settings.logger_level)

DBG = pdb.set_trace


class Kbuild:
    def __init__(self, makefile, casestudy):
        assert isinstance(makefile, pathlib.Path), makefile
        assert isinstance(casestudy, CaseStudy), casestudy

        self.topdir = makefile.parent
        self.makefile = makefile
        self.casestudy = casestudy
        self.solver = zsolver.ZSolver(self.casestudy.__zstate__)

        mlog.info("Kbuild for '{}'".format(self.makefile))

    def symexe(self):
        st = time()
        self.stmts = parser.parsestring(
            self.makefile.read_text(), self.makefile)

        path = Path.get_default(self.topdir)
        stmts = StatementList(
            self.stmts, Paths([path]), self.solver, self.casestudy)
        self.paths = stmts.parse()
        self.se_time = time() - st

        mlog.info("{}: {} paths ({:.2f}s)".format(
            self.makefile, len(self.paths), self.se_time))
        mlog.debug(self.paths)

    def fork(self, new_cond):
        kbuild = self.__class__(self.makefile, self.casestudy)
        kbuild.paths = [path.fork(new_cond) for path in self.paths
                        if self.solver.is_sat(zsolver.conj(path.cond, new_cond))]
        kbuild.se_time = 0.0

        return kbuild

    def save(self, tofile):
        """
        save info to file / load info from file
        note things are a bit complex because
        Z3 data structures cannot be saved directly to file
        """
        assert isinstance(tofile, pathlib.Path) and tofile, tofile

        kinfo = (self.makefile, self.se_time,
                 [(zsolver.to_smt2_str(p.cond), p.states) for p in self.paths],
                 self.solver.typ_info, self.casestudy.__class__.__name__)

        CM.vsave(tofile, kinfo)

    @staticmethod
    def load(fromfile):
        assert fromfile.is_file(), fromfile

        kinfo = CM.vload(fromfile)
        makefile, se_time, path_info, typ_info, casestudy = kinfo

        paths = Paths([
            Path(zsolver.from_smt2_str(cond), states)
            for cond, states in path_info
        ])

        cls = CaseStudy.get_casestudy(casestudy)
        kbuild = Kbuild(makefile, cls(None))
        kbuild.se_time = se_time
        kbuild.paths = paths
        kbuild.typ_info = zsolver.ZSolver.load_obj(typ_info)
        kbuild.casestudy = cls

        return kbuild


class Eval(object):
    def __init__(self, states, solver):
        assert isinstance(states, dict), states

        self.states = states
        self.solver = solver

    @staticmethod
    def combine(ts, delim=''):
        """
        take in a list of tuple(str, cond) and
        combine the strs if cond is satisfied
        Example 1
        ts = [[('my-', None)], [('on', None)], [('-', None)],
                [('y', CONFIG_A == y), ('m', CONFIG_A == m)]]
        output = [('my-on-y', CONFIG_A == y), ('my-on-m', CONFIG_A == m)]
        """
        assert ts, ts

        if len(ts) == 1:
            return ts[0]

        comb = []
        for pair in itertools.product(*ts):
            ss, cs = list(zip(*pair))
            c = zsolver.mconj(cs)
            comb.append((delim.join(ss), c))

        return comb

    def do_val(self, val):
        assert isinstance(val, str), val

        val = val.strip()
        if val:
            return self.do_fake_expansion(val)
        else:
            return [('', zsolver.T)]

    def do_fake_expansion(self, expansion):
        assert isinstance(expansion, str), expansion
        stmts = parser.parsestring(expansion, None)
        assert (len(stmts) == 1 and
                isinstance(stmts[0], parserdata.EmptyDirective)), stmts

        ret = self.do_expansion(stmts[0].exp)

        return ret

    def do_expansion(self, expansion):
        if isinstance(expansion, data.StringExpansion):  # 'x'
            return [(expansion.s, zsolver.T)]
        else:
            assert isinstance(expansion, data.Expansion), expansion
            elems = [self.do_elem(elem, isfun) for elem, isfun in expansion]
            comb = self.combine(elems)
            return comb

    def do_elem(self, elem, isfun):
        if isinstance(elem, str):
            return [(elem, zsolver.T)]
        elif isfun:
            if isinstance(elem, functions.VariableRef):
                return self.do_fun_VariableRef(elem)
            elif isinstance(elem, functions.SubstFunction):
                return self.do_fun_SubstFunction(elem)
            elif isinstance(elem, functions.PatSubstFunction):
                return self.do_fun_PatSubstFunction(elem)
            elif isinstance(elem, functions.WildcardFunction):
                return self.do_fun_WildcardFunction(elem)
            elif isinstance(elem, functions.FilteroutFunction):
                return self.do_fun_Filterout(elem)
            elif isinstance(elem, functions.AddPrefixFunction):
                return self.do_fun_AddPrefixFunction(elem)
            else:
                raise NotImplementedError(type(elem))
        else:
            return self.do_expansion(elem)

    def do_fun_AddPrefixFunction(self, fun):
        """
        $(addprefix src/,foo bar)
        produces the result 'src/foo src/bar'.
        """
        assert isinstance(fun, functions.AddPrefixFunction), fun

        # Note: $(addprefix pfx/  , g) is diff than $(addprefix pfx/,  g)

        combines = self.get_fun_arg_vals(fun, 2)
        d = OrderedDict()
        for (pv, pc), (nv, nc) in combines:
            cond = zsolver.conj(pc, nc)
            if self.solver.is_sat(cond):
                v = " ".join(pv + n for n in nv.split())
                d[v] = cond

        rs = list(d.items())
        return rs

    def do_fun_Filterout(self, fun):
        assert isinstance(fun, functions.FilteroutFunction), fun
        combines = self.get_fun_arg_vals(fun, 2)

        d = OrderedDict()
        for (pv, pc), (tv, tc) in combines:
            cond = zsolver.mconj([pc, tc])
            if self.solver.is_sat(cond):
                v = " ".join(v for v in tv.split() if v not in pv.split())
                if v not in d:
                    d[v] = cond
                else:
                    d[v] = zsolver.disj(d[v], cond)

        rs = list(d.items())
        return rs

    def do_fun_WildcardFunction(self, fun):
        assert isinstance(fun, functions.WildcardFunction), fun
        exps = self.do_expansion(fun._arguments[0])
        d = OrderedDict()
        import fnmatch
        for wc, cond in exps:
            if self.solver.is_sat(cond):
                dir = list(self.states['src'].vals)[0]
                v = ' '.join(map(str, fnmatch.filter(os.listdir(dir), wc)))
                if v not in d:
                    d[v] = cond

        rs = list(d.items())
        return rs

    def do_fun_PatSubstFunction(self, fun):
        assert isinstance(fun, functions.PatSubstFunction), fun
        import re

        combines = self.get_fun_arg_vals(fun, 3)
        d = OrderedDict()
        for (fv, fc), (tv, tc), (iv, ic) in combines:
            cond = zsolver.mconj([fc, tc, ic])
            if self.solver.is_sat(cond):
                pattern = "^" + fv.replace(r"%", r"(.*)", 1) + "$"
                replacement = tv.replace(r"%", r"\1", 1)

                v = " ".join(
                    re.sub(pattern, replacement, v) for v in iv.split())
                if v not in d:
                    d[v] = cond
                else:
                    d[v] = zsolver.disj(d[v], cond)

        rs = list(d.items())
        return rs

    def do_fun_SubstFunction(self, fun):
        assert isinstance(fun, functions.SubstFunction), fun
        combines = self.get_fun_arg_vals(fun, 3)

        d = OrderedDict()
        for (fv, fc), (tv, tc), (iv, ic) in combines:
            cond = zsolver.mconj([fc, tc, ic])
            if self.solver.is_sat(cond):
                v = iv.replace(fv, tv)
                if v not in d:
                    d[v] = cond
                else:
                    d[v] = zsolver.disj(d[v], cond)

        rs = list(d.items())
        return rs

    def do_fun_VariableRef(self, fun):
        assert isinstance(fun, functions.VariableRef), fun
        names = self.do_expansion(fun.vname)

        rs = []
        for name, _ in names:
            if name in self.states:
                v = self.states[name]
                if v.is_recurse:
                    vals = self.do_fake_expansion(v.vals_str)
                else:
                    vals = [(v.vals_str, zsolver.T)]
            elif name.startswith(settings.sym_prefix):
                vals = self.do_config_var(name)
            else:
                mlog.warn("'{}' undefined in path".format(name))
                vals = [(self.solver.undef_val, zsolver.T)]
            rs.extend(vals)
        return rs

    def do_config_var(self, name):
        assert name.startswith(settings.sym_prefix), name

        s = self.solver.get_tristate_sort(name)

        vals = [(k, s == self.solver.COptD[k]) for k in self.solver.COptD]
        return vals

    def get_fun_arg_vals(self, fun, nargs):
        assert nargs >= 1, nargs
        fargs = [fun._arguments[i] for i in range(nargs)]
        expansions = [self.do_expansion(farg) for farg in fargs]
        return itertools.product(*expansions)


class ParserData(object):
    def __init__(self, stmt, paths, solver, casestudy):
        assert isinstance(paths, Paths), paths
        assert isinstance(solver, zsolver.ZSolver), solver

        self.stmt = stmt
        self.paths = paths
        self.solver = solver
        self.casestudy = casestudy

    def parse(self):
        st = time()
        new_paths = Paths()
        for i, path in enumerate(self.paths):
            new_paths_ = self.parse_single(path)
            new_paths.extend(new_paths_)

        if isinstance(self, StatementList):
            return new_paths

        et_mk = time() - st

        if settings.detail:
            print('--- ORIG --- ({} paths)'.format(len(self.paths)))
            print(self.paths)
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

        mlog.debug("--- MERGE --- ({} paths):\n{}".format(
            len(merge_paths), merge_paths))

        mlog.debug("paths: orig {}, new {} ({:2f}), "
                   "split {} ({:02f}), "
                   "merge {} ({:02f}), "
                   "mem {}, config {}, time {:02f}".format(
                       len(self.paths),
                       len(new_paths), et_mk,
                       len(split_paths), et_split,
                       len(merge_paths), et_merge,
                       Path.__ct__, len(zsolver.ZSolver.__config_vars__),
                       time() - st))

        return merge_paths

    def get_new_path(self, path, cond):
        newcond = zsolver.conj(path.cond, cond)
        if self.solver.is_sat(newcond):
            new_path = path.fork(newcond)
            return new_path
        else:
            return None


class StatementList(ParserData):
    def __init__(self, stmt, paths, solver, casestudy):
        assert isinstance(stmt, parserdata.StatementList), stmt

        super().__init__(stmt, paths, solver, casestudy)

    def parse_single(self, path):

        paths = Paths([path])
        stmts = self.stmt

        for i, stmt in enumerate(stmts):
            mlog.debug("{}/{}. {} paths hit stmt '{}'".format(
                i + 1, len(stmts),  len(paths), stmt.to_source().strip()))

            if isinstance(stmt, parserdata.SetVariable):
                cls = SetVariable

            elif isinstance(stmt, parserdata.ConditionBlock):
                cls = ConditionBlock

            elif isinstance(
                    stmt, (parserdata.Rule, parserdata.StaticPatternRule)):
                cls = Rule

            elif isinstance(stmt, parserdata.Include):
                cls = Include

            elif isinstance(stmt, parserdata.Command):
                cls = Command

            elif isinstance(stmt, parserdata.EmptyDirective):
                cls = EmptyDirective

            else:
                raise NotImplementedError("cannot parse {}".format(stmt))

            paths = cls(
                stmt, paths, self.solver, self.casestudy).parse()

        return paths


class SetVariable(ParserData):
    """
    Examples:
    - obj-y := fork.o
    """

    def __init__(self, stmt, paths, solver, casestudy):
        assert isinstance(stmt, parserdata.SetVariable), stmt
        super().__init__(stmt, paths, solver, casestudy)

    def parse_single(self, path):
        assert isinstance(path, Path), path

        nameexp = self.stmt.vnameexp
        token = self.stmt.token   # :=
        val = self.stmt.value

        myeval = Eval(path.states, self.solver)
        names = myeval.do_expansion(nameexp)

        # [('CFLAGS_wp512.o', True)]
        if len(names) == 1 and self.casestudy.ignore_symbol(names[0][0]):
            mlog.warn("ignoring '{}'".format(names[0][0]))
            return Paths([path])

        unexpanded = token == "="
        vals = [(val, zsolver.T)] if unexpanded else myeval.do_val(val)

        new_paths = Paths()
        for (name, ncond), (val, vcond) in itertools.product(*[names, vals]):
            new_cond = zsolver.conj(path.cond, zsolver.conj(ncond, vcond))
            if self.solver.is_sat(new_cond):
                new_path = path.fork(new_cond)
                new_path.set_var(name, token, val)
                new_paths.append(new_path)

        return new_paths


class ConditionBlock(ParserData):
    def __init__(self, stmt, paths, solver, casestudy):
        assert isinstance(stmt, parserdata.ConditionBlock), stmt
        super().__init__(stmt, paths, solver, casestudy)

    def parse_single(self, path):
        if_cond, then_stmts = self.stmt[0]  # if/then branch
        if_cond = self.eval_condition(if_cond, path)

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
            stmt_list = StatementList(stmts, Paths([new_path]), self.solver,
                                      self.casestudy)
            paths = stmt_list.parse()
            return paths
        else:
            return []

    def eval_condition(self, cond, path):
        """
        evaluation arguments of the condition and return a Z3 condition
        """
        myeval = Eval(path.states, self.solver)

        if isinstance(cond, parserdata.EqCondition):
            exps1 = myeval.do_expansion(cond.exp1)
            exps2 = myeval.do_expansion(cond.exp2)

            eq_cond = self.get_eq_cond(exps1, exps2)

            return eq_cond if cond.expected else zsolver.neg(eq_cond)

        elif isinstance(cond, parserdata.IfdefCondition):
            assert isinstance(cond.exp, data.StringExpansion), cond.exp
            exp = "$({})".format(cond.exp.s)
            exp = myeval.do_fake_expansion(exp)

            exp_undef = [(self.solver.undef_val, zsolver.T)]
            undef_cond = self.get_eq_cond(exp, exp_undef)

            return zsolver.neg(undef_cond) if cond.expected else undef_cond

        else:
            raise NotImplementedError("Cannot parse condition: {}".format(
                cond.to_source()))

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


class Rule(ParserData):
    def __init__(self, stmt, paths, solver, casestudy):
        assert isinstance(
            stmt, (parserdata.Rule, parserdata.StaticPatternRule)), stmt
        super().__init__(stmt, paths, solver, casestudy)

    def parse_single(self, path):
        # mlog.warn("Cannot parse Rule: {}".format(self.stmt.to_source()))
        new_paths = Paths([path])
        return new_paths


class Include(ParserData):
    def __init__(self, stmt, paths, solver, casestudy):
        assert isinstance(stmt, parserdata.Include), stmt
        super().__init__(stmt, paths, solver, casestudy)

    def parse_single(self, path):
        myeval = Eval(path.states, self.solver)
        exp = myeval.do_expansion(self.stmt.exp)
        paths = []
        for include_file, include_cond in exp:
            assert include_file, include_file
            assert len(include_file.split()) == 1

            if not os.path.exists(include_file):
                mlog.warn(
                    "include file '{}' does not exist".format(include_file))
                continue

            new_path = self.get_new_path(path, include_cond)
            if not new_path:
                continue

            fh = open(include_file, "rU")
            stmts = fh.read()
            fh.close()
            stmts = parser.parsestring(stmts, fh.name)
            stmt_list = StatementList(stmts, [new_path], self.solver,
                                      self.casestudy)
            paths_ = stmt_list.parse()
            paths.extend(paths_)

        return paths


class Command(ParserData):
    def __init__(self, stmt, paths, solver, casestudy):
        assert isinstance(stmt, parserdata.Command), stmt
        super().__init__(stmt, paths, solver, casestudy)

    def parse_single(self, path):
        # mlog.warn("Cannot parse Command: {}".format(self.stmt.to_source()))
        return Paths([path])


class EmptyDirective(ParserData):
    def __init__(self, stmt, paths, solver, casestudy):
        assert isinstance(stmt, parserdata.EmptyDirective), stmt
        super().__init__(stmt, paths, solver, casestudy)

    def parse_single(self, path):
        mlog.warn("Cannot parse EmptyDirective: {}".format(
            self.stmt.to_source()))
        return Paths([path])
