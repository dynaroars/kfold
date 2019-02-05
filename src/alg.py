#! /usr/bin/env python

from collections import OrderedDict
import itertools
from time import time
from datetime import datetime
import os.path
import pdb

import z3
from pymake import parser, parserdata, data, functions


import vcommon as CM

from zsolver import ZSolver
import zsolver
from ds import Path, Paths


import settings
mlog = CM.getLogger(__name__, settings.logger_level)

trace = pdb.set_trace
pause = CM.pause


class Eval(object):
    def __init__(self, path, solver, zvars):
        # path is None => spy
        assert isinstance(path, Path), path
        self.path = path
        self.solver = solver
        self.zvars = zvars

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
            ss, cs = zip(*pair)
            c = zsolver.mconj(cs)
            comb.append((delim.join(ss), c))

        return comb

    def do_value(self, value):
        assert isinstance(value, str), value

        value = value.strip()
        if not value:
            return [('', zsolver.T)]
        else:
            val = self.do_fake_expansion(value)

            return val

    def do_fake_expansion(self, expansion):
        assert isinstance(expansion, str), expansion

        stmts = parser.parsestring(expansion, None)
        assert len(stmts) == 1 and isinstance(
            stmts[0], parserdata.EmptyDirective), stmts
        ret = self.do_expansion(stmts[0].exp)

        return ret

    def do_expansion(self, expansion):
        if isinstance(expansion, data.StringExpansion):  # 'x'
            return [(expansion.s, zsolver.T)]
        else:
            assert isinstance(expansion, data.Expansion), expansion

            elems = [self.do_elem(elem, isfun)
                     for elem, isfun in expansion]
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

        # [('pfx/', True)]
        prefixes = self.do_expansion(fun._arguments[0])

        # [(' first second y', CONFIG_G == y), (' first second ',
        # CONFIG_G == undef), (' first second m', CONFIG_G == m)]
        names = self.do_expansion(fun._arguments[1])

        # important: do not prefix.
        # e.g., $(addprefix pfx/  , g) is diff than $(addprefix pfx/,  g)

        combines = [(pv, nv) for pv in prefixes for nv in names]
        d = OrderedDict()
        for (pv, pc), (nv, nc) in combines:
            cond = zsolver.conj(pc, nc)
            if self.solver.is_sat(cond):
                v = " ".join(pv + n for n in nv.split())
                d[v] = cond

        rs = d.items()
        return rs

    def do_fun_SubstFunction(self, fun):
        assert isinstance(fun, functions.SubstFunction), fun
        from_vals = self.do_expansion(fun._arguments[0])
        to_vals = self.do_expansion(fun._arguments[1])
        in_vals = self.do_expansion(fun._arguments[2])

        combines = [(fv, tv, iv) for fv in from_vals
                    for tv in to_vals
                    for iv in in_vals]

        d = OrderedDict()
        for (fv, fc), (tv, tc), (iv, ic) in combines:
            cond = zsolver.mconj([fc, tc, ic])
            if self.solver.is_sat(cond):
                v = iv.replace(fv, tv)
                if v not in d:
                    d[v] = cond
                else:
                    d[v] = zsolver.disj(d[v], cond)

        rs = d.items()
        return rs

    def do_fun_VariableRef(self, fun):
        assert isinstance(fun, functions.VariableRef), fun

        names = self.do_expansion(fun.vname)

        rs = []
        for name, _ in names:
            if name in self.path.states:
                vals = self.path.states[name].vals_str
                vals = [(vals, zsolver.T)]
            elif name.startswith(settings.sym_prefix):
                vals = self.do_config_var(name)
            else:
                mlog.warn("'{}' undefined in path".format(name))
                vals = [(zsolver.Undef_Val, zsolver.T)]
            rs.extend(vals)

        return rs

    def do_config_var(self, name):
        assert name.startswith(settings.sym_prefix), name

        if name not in self.zvars:
            self.zvars[name] = ZSolver.get_tristate_sort(name)
        s = self.zvars[name]

        vals = [(k, s == zsolver.COptD[k]) for k in zsolver.COptD]
        return vals


class ParserData(object):
    def __init__(self, stmt, paths, solver, zvars):
        assert isinstance(paths, Paths), paths
        self.stmt = stmt
        self.paths = paths
        self.solver = solver
        self.zvars = zvars

    def parse(self):
        new_paths = Paths()
        for i, path in enumerate(self.paths):
            new_paths_ = self.parse_single(path)
            new_paths.extend(new_paths_)

        return new_paths

    def get_new_path(self, path, cond):
        newcond = zsolver.conj(path.cond, cond)
        if self.solver.is_sat(newcond):
            new_path = path.fork(newcond)
            return new_path
        else:
            return None

    @staticmethod
    def get_trace_loc(stmt):
        """Return the trace location if stmt is a trace command. Otherwise
        return None.
        """
        if (isinstance(stmt, parserdata.Rule) and
                stmt.targetexp.s == settings.trace_target):
            return str(stmt.targetexp.loc)
        else:
            return None


class StatementList(ParserData):
    def __init__(self, stmt, paths, solver, zvars):
        assert isinstance(stmt, parserdata.StatementList), stmt
        super(StatementList, self).__init__(stmt, paths, solver, zvars)

    def parse_single(self, path):

        paths = Paths([path])
        stmts = self.stmt

        for i, stmt in enumerate(stmts):
            st = time()
            mlog.debug("{}/{}: '{}' with {} paths".format(
                i + 1, len(stmts), stmt.to_source(), len(paths)))

            if isinstance(stmt, parserdata.SetVariable):
                cls = SetVariable
            elif isinstance(stmt, parserdata.ConditionBlock):
                cls = ConditionBlock
            elif isinstance(stmt,
                            (parserdata.Rule, parserdata.StaticPatternRule)):
                cls = Rule
            elif isinstance(stmt, parserdata.Include):
                cls = Include
            elif isinstance(stmt, parserdata.Command):
                cls = Command
            elif isinstance(stmt, parserdata.EmptyDirective):
                cls = EmptyDirective
            else:
                raise NotImplementedError("cannot parse {}".format(stmt))

            new_paths = cls(stmt, paths, self.solver, self.zvars).parse()
            et_mk = time() - st

            if settings.detail:
                print '--- ORIG --- ({} paths)'.format(len(paths))
                print paths
                print '--- NEW --- ({} paths)'.format(len(new_paths))
                print new_paths

            st_split = time()
            split_paths = new_paths.split()
            et_split = time() - st_split

            if settings.detail:
                print '--- SPLIT --- ({} paths)'.format(len(split_paths))
                print split_paths

            st_merge = time()
            merge_paths = split_paths.merge()
            et_merge = time() - st_merge

            if settings.detail:
                print '--- MERGE --- ({} paths)'.format(len(merge_paths))
                print merge_paths

            paths = merge_paths

            mlog.debug("paths: orig {}, new {} ({:2f}), "
                       "split {} ({:02f}), "
                       "merge {} ({:02f}), "
                       "mem {}, config {}, time {:02f}".format(
                           len(paths), len(new_paths), et_mk,
                           len(split_paths), et_split,
                           len(merge_paths), et_merge,
                           Path.__ct__,  ZSolver.__config_ct__,
                           time() - st))

        return paths


class SetVariable(ParserData):
    def __init__(self, stmt, paths, solver, zvars):
        assert isinstance(stmt, parserdata.SetVariable), stmt
        super(SetVariable, self).__init__(stmt, paths, solver, zvars)

    def parse(self):

        new_paths = Paths()
        for i, path in enumerate(self.paths):
            new_paths_ = self.parse_single(path)
            new_paths.extend(new_paths_)

        return new_paths

    def parse_single(self, path):
        assert isinstance(path, Path), path

        nameexp = self.stmt.vnameexp
        token = self.stmt.token
        value = self.stmt.value

        eval = Eval(path, self.solver, self.zvars)
        names = eval.do_expansion(nameexp)

        # [('CFLAGS_wp512.o', True)]
        if (len(names) == 1 and
            names[0][0].startswith("CFLAGS") or
                names[0][0].endswith("extract_certs")):
            return Paths([path])

        values = eval.do_value(value)

        new_paths = Paths()
        for (name, ncond), (val, vcond) in itertools.product(*[names, values]):
            new_cond = zsolver.conj(path.cond, zsolver.conj(ncond, vcond))
            if self.solver.is_sat(new_cond):
                new_path = path.fork(new_cond)
                new_path.set_var(name, token, val)
                new_paths.append(new_path)

        return new_paths


class ConditionBlock(ParserData):
    def __init__(self, stmt, paths, solver, zvars):
        assert isinstance(stmt, parserdata.ConditionBlock), stmt
        super(ConditionBlock, self).__init__(stmt, paths, solver, zvars)

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
            stmt_list = StatementList(
                stmts, Paths([new_path]), self.solver, self.zvars)
            paths = stmt_list.parse()
            return paths
        else:
            return []

    def eval_condition(self, cond, path):
        """
        evaluation arguments of the condition and return a Z3 condition
        """
        eval = Eval(path, self.solver, self.zvars)

        if isinstance(cond, parserdata.EqCondition):
            exps1 = eval.do_expansion(cond.exp1)
            exps2 = eval.do_expansion(cond.exp2)

            eq_cond = self.get_eq_cond(exps1, exps2)

            return eq_cond if cond.expected else zsolver.neg(eq_cond)

        elif isinstance(cond, parserdata.IfdefCondition):
            assert isinstance(cond.exp, data.StringExpansion), cond.exp
            exp = "$({})".format(cond.exp.s)
            exp = eval.do_fake_expansion(exp)

            exp_undef = [(zsolver.Undef_Val, zsolver.T)]
            undef_cond = self.get_eq_cond(exp, exp_undef)

            return zsolver.neg(undef_cond) if cond.expected else undef_cond

        else:
            raise NotImplementedError(
                "Cannot parse condition: {}".format(repr(cond)))

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

            if v not in merge_d:
                merge_d[v] = []
            merge_d[v].append(c)

        assert all(len(merge_d[k]) >= 2 for k in merge_d), merge_d

        disjs = [zsolver.mconj(cs) for cs in merge_d.itervalues()]
        if not disjs:
            return zsolver.F
        elif len(disjs) == 1:
            return disjs[0]
        else:
            assert all(disj is not zsolver.T for disj in disjs), disjs
            return zsolver.mdisj(disjs)


class Rule(ParserData):
    def __init__(self, stmt, paths, solver, zvars):
        assert isinstance(
            stmt, (parserdata.Rule, parserdata.StaticPatternRule)), stmt
        super(Rule, self).__init__(stmt, paths, solver, zvars)

    def parse_single(self, path):
        mlog.warn("Cannot parse Rule: {}".format(self.stmt))
        # tloc = self.get_trace_loc(self.stmt)
        # if tloc:
        #     if tloc not in self.traces:
        #         self.traces[tloc] = Paths()
        #     self.traces[tloc].append(path)

        # else:
        #     mlog.warn("Cannot parse Rule: {}".format(self.stmt))

        new_paths = Paths([path])
        return new_paths


class Include(ParserData):
    def __init__(self, stmt, paths, solver, zvars):
        assert isinstance(stmt, parserdata.Include), stmt
        super(Include, self).__init__(stmt, paths, solver, zvars)

    def parse_single(self, path):
        eval = Eval(path, self.solver, self.zvars)
        exp = eval.do_expansion(self.stmt.exp)
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
            stmt_list = StatementList(
                stmts, [new_path], self.solver, self.zvars)
            paths_ = stmt_list.parse()
            paths.extend(paths_)

        return paths


class Command(ParserData):
    def __init__(self, stmt, paths, solver, zvars):
        assert isinstance(stmt, parserdata.Command), stmt
        super(Command, self).__init__(stmt, paths, solver, zvars)

    def parse_single(self, path):
        mlog.warn("Cannot parse Command: {}".format(self.stmt))
        return Paths([path])


class EmptyDirective(ParserData):
    def __init__(self, stmt, paths, solver, zvars):
        assert isinstance(stmt, parserdata.EmptyDirective), stmt
        super(EmptyDirective, self).__init__(stmt, paths, solver, zvars)

    def parse_single(self, path):
        mlog.warn("Cannot parse EmptyDirective: {}".format(self.stmt))
        return Paths([path])


class Kbuild:
    def __init__(self, makefile):
        assert os.path.isfile(makefile), makefile

        makefile_ = open(makefile, "rU")
        stmts = makefile_.read()
        makefile_.close()
        self.stmts = parser.parsestring(stmts, makefile_.name)

        self.topdir = os.path.dirname(makefile)
        self.makefile = makefile
        self.zvars = OrderedDict()
        self.solver = ZSolver()
        # store individual states collected at __TRACE__ points
        self.traces = OrderedDict()

    def symexe(self, cond):
        assert z3.is_expr(cond), cond
        st = time()
        mlog.info("{}: symexe '{}'".format(
            datetime.now().strftime("%Y-%m-%d %H:%M"), self.makefile))

        path = Path.get_default(cond, self.topdir)
        stmts = StatementList(self.stmts, Paths([path]),
                              self.solver, self.zvars)
        self.paths = stmts.parse()

        mlog.info("found {} paths ({}s)".format(
            len(self.paths), time() - st))
        mlog.debug(self.paths)


class Run:
    def __init__(self, makefile_paths):
        """makefile_paths is a list of makefile path (either a real makefile
        or directory)

        """
        self.makefile_paths = makefile_paths

    def go(self):

        def get_makefiles(file_paths, cond):
            makefiles = [self.get_makefile(p) for p in file_paths]
            return [(makefile, cond) for makefile in makefiles if makefile]

        def analyze(makefile, cond):
            assert os.path.isfile(makefile), makefile
            assert cond is None or z3.is_expr(cond), cond
            kbuild = Kbuild(makefile)
            kbuild.symexe(cond)
            return kbuild

        kbuilds = []  # results
        makefiles = get_makefiles(self.makefile_paths, cond=zsolver.T)
        while makefiles:

            # parallel
            kbuilds_ = [analyze(makefile, cond)
                        for makefile, cond in makefiles]
            kbuilds.extend(kbuilds_)

            # recurse to subdirs if any
            makefiles = []
            for kbuild in kbuilds_:
                for path in kbuild.paths:
                    makefiles_ = get_makefiles(
                        path.subdirs(kbuild.topdir), path.cond)
                    makefiles.extend(makefiles_)

        mlog.info("analyzed {} kbuild makefiles".format(len(kbuilds)))
        return kbuilds

    @classmethod
    def get_makefile(cls, makefile_path):
        # use Kbuild file if found, otherwise try Makefile
        if not os.path.exists(makefile_path):
            mlog.warn("{} does not exist".format(makefile_path))
            return None

        makefile = makefile_path
        if os.path.isdir(makefile_path):
            makefile = os.path.join(makefile_path, "Kbuild")
            if not os.path.isfile(makefile):
                makefile = os.path.join(makefile_path, "Makefile")

        if not os.path.isfile(makefile):
            mlog.warn("{} has no makefile".format(makefile_path))
            return None

        return os.path.abspath(makefile)
