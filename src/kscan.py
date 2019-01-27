#! /usr/bin/env python

from collections import namedtuple, OrderedDict
import itertools
from time import time
import os.path
import pdb

from pymake import parser, parserdata, data, functions
import z3

import vcommon as CM

from zsolver import ZSolver
import zsolver

trace = pdb.set_trace
pause = CM.pause
logger_level = 3


class Settings:
    target_vars = frozenset(["obj-", "lib-"])
    ignore_vars = frozenset(["src"])
    do_mp = True
    mp_task_len = 50  # start parallel processing when having >= mp_task_len
    trace_target = "__TRACE__"
    sym_prefix = "CONFIG_"


BaseVar = namedtuple("BaseVar", "name val flavor")


class Var(BaseVar):
    RECURSE = "RECURSE"   # =, define
    SIMPLY = "SIMPLY"  # := , ::=

    def fork(self):
        return Var(self.name, self.val, self.flavor)

    def fork_val(self, val):
        return Var(self.name, val, self.flavor)

    def __str__(self):
        token = "=" if self.flavor == Var.RECURSE else ":="
        return "{} {} {}".format(self.name, token, self.val)

    @property
    def ignorable(self):
        return self.name in Settings.ignore_vars

    def subdirs(self, topdir):
        sd = [os.path.join(topdir, v)
              for v in self.val.split() if v.endswith("/")]
        return sd

    @staticmethod
    def get_flavor(token):
        if token == "=":
            flavor = Var.RECURSE
        elif token in set([":=", "::="]) or token in set(["+="]):
            flavor = Var.SIMPLY
        else:
            raise NotImplementedError("token {}".format(token))

        return flavor

    @staticmethod
    def src_var(topdir):
        assert os.path.isdir(topdir), topdir
        return Var("src", topdir, Var.RECURSE)


class Path:

    __ct__ = 0

    def __init__(self, cond, states):
        assert isinstance(states, dict)
        self.cond = cond
        self.states = states
        Path.__ct__ += 1

    def __del__(self):
        Path.__ct__ -= 1

    def __str__(self):

        ss = (v for v in self.states.itervalues() if not v.ignorable)
        ss = '; '.join(map(str, ss))
        if ss:
            ss = "{} => {}".format(self.cond, ss)
        return ss

    def subdirs(self, topdir):
        subdirs_ = [self.states[v].subdirs(topdir) for v in self.states]
        return list(itertools.chain(*subdirs_))

    def fork(self, newcond, ignore_targets=False):
        """
        Create a new path with newcond
        """
        new_states = OrderedDict()
        for name, v in self.states.iteritems():
            if ignore_targets and Path.is_target(name):
                continue
            new_states[name] = v.fork()
        return Path(newcond, new_states)

    def set_var(self, name, token, val):
        assert isinstance(name, str), name
        assert isinstance(token, str)  # and token in {'='}, token
        assert isinstance(val, str), val

        if name not in self.states or token in set(["=", ":="]):
            if name in self.states:
                mlog.warn('need more precise semantics of {}'.format(token))
            self.states[name] = Var(name, uniq(val), Var.get_flavor(token))
        else:
            if token == "+=":
                new_val = self.states[name].val + ' ' + val
                new_val = uniq(new_val)
                self.states[name] = self.states[name].fork_val(
                    new_val)  # append(val)
            else:
                raise NotImplementedError

    @property
    def state_hash(self):
        fs = frozenset(sorted(self.states.items()))
        ret = hash(fs)
        return ret

    @staticmethod
    def is_target(t):
        return any(t.startswith(x) for x in Settings.target_vars)

    @staticmethod
    def is_not_target(t):
        return not Path.is_target(t)

    @classmethod
    def get_default(cls, cond, src_dir):
        assert cond is None or z3.is_expr(cond), cond
        assert os.path.isdir(src_dir)

        states = {'src': Var.src_var(src_dir)}
        return cls(zsolver.T if cond is None else cond, states)


class Paths(list):
    def __str__(self):
        n_paths = len(self)

        paths = []
        for path in self:
            s = str(path)
            if s:
                paths.append(s)

        ss = ["{}. {}".format(i+1, path)
              for i, path in enumerate(paths)]

        diff = n_paths - len(paths)
        if diff:
            ss.append("Paths: shown {}, hidden {}, total {}".format(
                len(paths), diff, n_paths))
        return '\n'.join(ss)

    def split(self):
        assert self, self
        new_paths = Paths()

        for path in self:
            if (not path.states or  # no state
                    all(Path.is_not_target(name) for name in path.states)):
                new_paths.append(path)  # keep path as is
            else:
                for name in path.states:
                    if Path.is_not_target(name):
                        continue
                    myvar = path.states[name]
                    vals = myvar.val.split()
                    if not vals:
                        new_path = path.fork(path.cond, ignore_targets=True)
                        new_path.states[name] = myvar.fork()
                        new_paths.append(new_path)
                    else:
                        for v in vals:
                            new_path = path.fork(
                                path.cond, ignore_targets=True)
                            new_path.states[name] = myvar.fork_val(v)
                            new_paths.append(new_path)

        assert new_paths
        return new_paths

    def merge_mp(self):
        assert self, self

        groups = {}
        for path in self:
            state_hash = path.state_hash
            if state_hash not in groups:
                groups[state_hash] = []
            groups[state_hash].append(path)

        if len(groups) == len(self):
            return self

        simplified_paths = []
        other_paths = []
        for gpaths in groups.itervalues():
            path = gpaths[0]
            if len(gpaths) == 1:
                simplified_paths.append(path)
            else:
                path.cond = zsolver.mdisj([p.cond for p in gpaths])
                assert path.cond is not zsolver.F
                if (path.cond is zsolver.T or
                        path.cond.decl().kind() == z3.Z3_OP_EQ):
                    simplified_paths.append(path)
                else:
                    scond = zsolver.get_from_simplify_cache(path.cond)
                    if scond is not None:
                        path.cond = scond
                        simplified_paths.append(path)
                    else:
                        other_paths.append(path)

        if other_paths:
            def _simplify(i):
                gcond = zsolver.simplify(other_paths[i].cond)
                return zsolver.to_smt2_str(gcond)

            def wprocess(tasks, Q):
                rs = [(i, _simplify(i)) for i in tasks]
                if Q is None:
                    return rs
                else:
                    Q.put(rs)

            wrs = CM.Miscs.runMP('merge', range(len(other_paths)),
                                 wprocess, chunksiz=2,
                                 doMP=Settings.do_mp and
                                 len(other_paths) >= Settings.mp_task_len)

            for i, cond_str in wrs:
                cond = zsolver.from_smt2_str(cond_str)
                if other_paths[i].cond not in zsolver.__simplify_cache__:
                    zsolver.__simplify_cache__[other_paths[i].cond] = cond

                other_paths[i].cond = cond

        merge_paths = Paths(simplified_paths + other_paths)
        return merge_paths


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
        assert cond is None or z3.is_expr(cond), cond

        mlog.info("symexe '{}'".format(self.makefile))

        path = Path.get_default(cond, self.topdir)
        self.paths = self.parse_stmts(self.stmts, path)

        mlog.debug("'{}' has {} paths:\n{}".format(
            self.makefile, len(self.paths), self.paths))

    @staticmethod
    def get_trace_loc(stmt):
        """Return the trace location if stmt is a trace command. Otherwise
        return None.
        """
        if (isinstance(stmt, parserdata.Rule) and
                stmt.targetexp.s == Settings.trace_target):
            return str(stmt.targetexp.loc)
        else:
            return None

    def parse_stmts(self, stmts, path):

        paths = Paths()
        paths.append(path)

        for i, stmt in enumerate(stmts):
            st = time()
            mlog.debug("{}/{}: '{}' with {} paths".format(
                i + 1, len(stmts), stmt.to_source(), len(paths)))

            new_paths = Paths()
            for i, path in enumerate(paths):
                if isinstance(stmt, parserdata.SetVariable):
                    new_paths_ = self.parse_setvar(stmt, path)

                elif isinstance(stmt, parserdata.ConditionBlock):
                    new_paths_ = self.parse_conditionblock(stmt, path)

                elif isinstance(stmt, (parserdata.Rule,
                                       parserdata.StaticPatternRule)):
                    new_paths_ = self.parse_rule(stmt, path)

                elif isinstance(stmt, parserdata.Command):
                    mlog.warn("Cannot parse Command: {}".format(stmt))
                    new_paths_ = [path]

                elif isinstance(stmt, parserdata.Include):
                    new_paths_ = self.parse_include(stmt, path)

                else:
                    raise NotImplementedError(
                        "cannot parse {}".format(stmt))

                new_paths.extend(new_paths_)

            et_mk = time() - st

            # print '--- ORIG ---'
            # print paths
            # print '--- NEW ---'
            # print new_paths

            st_split = time()
            split_paths = new_paths.split()
            et_split = time() - st_split

            # print '--- SPLIT ---'
            # print split_paths

            st_merge = time()
            merge_paths = split_paths.merge_mp()
            et_merge = time() - st_merge

            # print '--- MERGE ---'
            # print merge_paths

            paths = merge_paths

            mlog.debug("paths: orig {}, new {} ({:2f}), split {} ({:02f}), merge {} ({:02f}), mem {}, config {}, time {:02f}".format(
                len(paths), len(new_paths), et_mk,
                len(split_paths), et_split,
                len(merge_paths), et_merge,
                Path.__ct__,  ZSolver.__config_ct__,
                time() - st))

            tloc = self.get_trace_loc(stmt)
            if tloc:
                mlog.debug("Symbolic traces at '{}'\n{}".format(
                    tloc, self.traces[tloc]))

        return paths

    def parse_rule(self, stmt, path):
        assert isinstance(
            stmt, (parserdata.Rule, parserdata.StaticPatternRule)), stmt
        tloc = self.get_trace_loc(stmt)
        if tloc:
            if tloc not in self.traces:
                self.traces[tloc] = Paths()
            self.traces[tloc].append(path)

        else:
            mlog.warn("Cannot parse Rule: {}".format(stmt))

        new_paths = [path]
        return new_paths

    def parse_include(self, stmt, path):

        assert isinstance(stmt, parserdata.Include), stmt

        exp = self.eval_expansion(stmt.exp, path)
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
            paths_ = self.parse_stmts(stmts, new_path)

            paths.extend(paths_)

        return paths

    def get_new_path(self, path, cond):
        newcond = zsolver.conj(path.cond, cond)
        if self.solver.is_sat(newcond):
            new_path = path.fork(newcond)
            return new_path
        else:
            return None

    def add_paths(self, path, cond, stmts):
        new_path = self.get_new_path(path, cond)
        if new_path:
            paths = self.parse_stmts(stmts, new_path)
            return paths
        else:
            return []

    def parse_conditionblock(self, stmt, path):
        assert isinstance(stmt, parserdata.ConditionBlock), stmt

        if_cond, then_stmts = stmt[0]  # if/then branch
        if_cond = self.eval_condition(if_cond, path)

        paths = self.add_paths(path, if_cond, then_stmts)

        # else branch
        else_cond = zsolver.neg(if_cond)
        if len(stmt) == 1:  # no else branch, treats as else: empty
            else_stmts = []
        elif len(stmt) == 2:  # else branch
            _, else_stmts = stmt[1]
        else:
            raise NotImplementedError("{} stmts".format(len(stmt)))

        paths_ = self.add_paths(path, else_cond, else_stmts)
        paths.extend(paths_)
        return paths

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

    def eval_condition(self, cond, path):
        """
        evaluation arguments of the condition and return a Z3 condition
        """
        if isinstance(cond, parserdata.EqCondition):
            exps1 = self.eval_expansion(cond.exp1, path)
            exps2 = self.eval_expansion(cond.exp2, path)

            eq_cond = self.get_eq_cond(exps1, exps2)

            return eq_cond if cond.expected else zsolver.neg(eq_cond)

        elif isinstance(cond, parserdata.IfdefCondition):
            assert isinstance(cond.exp, data.StringExpansion), cond.exp
            exp = "$({})".format(cond.exp.s)
            exp = self.eval_fake_expansion(exp, path)

            exp_undef = [(zsolver.Undef_Val, zsolver.T)]
            undef_cond = self.get_eq_cond(exp, exp_undef)

            return zsolver.neg(undef_cond) if cond.expected else undef_cond

        else:
            raise NotImplementedError(
                "Cannot parse condition: {}".format(repr(cond)))

    def parse_setvar(self, stmt, path):
        assert isinstance(stmt, parserdata.SetVariable), stmt

        nameexp = stmt.vnameexp
        token = stmt.token
        value = stmt.value
        names = self.eval_expansion(nameexp, path)
        values = self.eval_value(value, path)

        new_paths = []
        for (name, ncond), (val, vcond) in itertools.product(*[names, values]):
            newcond = zsolver.conj(path.cond, zsolver.conj(ncond, vcond))

            if self.solver.is_sat(newcond):
                new_path = path.fork(newcond)
                new_path.set_var(name, token, val)
                new_paths.append(new_path)

        return new_paths

    def combine(self, ts, delim=''):
        """
        take in a list of tuple(str, cond) and
        combine the strs if cond is satisfied
        Example 1
        ts = [[('my-', None)], [('on', None)], [('-', None)],
                [('y', CONFIG_A == y), ('m', CONFIG_A == m)]]
        output = [('my-on-y', CONFIG_A == y), ('my-on-m', CONFIG_A == m)]
        """
        assert ts

        if len(ts) == 1:
            return ts[0]

        # print 'ts', ts

        comb = []
        for pair in itertools.product(*ts):
            ss, cs = zip(*pair)
            c = zsolver.mconj(cs)
            comb.append((delim.join(ss), c))

        return comb

    def eval_value(self, value, path):
        assert isinstance(value, str), value

        value = value.strip()
        if not value:
            return [('', zsolver.T)]
        else:
            val = self.eval_fake_expansion(value, path)
            return val

    def eval_fake_expansion(self, expansion, path):
        assert isinstance(expansion, str), expansion

        stmts = parser.parsestring(expansion, None)
        assert len(stmts) == 1 and isinstance(
            stmts[0], parserdata.EmptyDirective), stmts
        ret = self.eval_expansion(stmts[0].exp, path)

        return ret

    def eval_expansion(self, expansion, path):
        if isinstance(expansion, data.StringExpansion):  # 'x'
            return [(expansion.s, zsolver.T)]
        else:
            assert isinstance(expansion, data.Expansion), expansion

            elems = [self.eval_elem(elem, isfun, path)
                     for elem, isfun in expansion]
            comb = self.combine(elems)
            return comb

    def eval_elem(self, elem, isfun, path):
        if isinstance(elem, str):
            return [(elem, zsolver.T)]
        elif isfun:
            if isinstance(elem, functions.VariableRef):
                return self.eval_fun_VariableRef(elem, path)
            elif isinstance(elem, functions.SubstFunction):
                return self.eval_fun_SubstFunction(elem, path)
            elif isinstance(elem, functions.AddPrefixFunction):
                return self.eval_fun_AddPrefixFunction(elem, path)
            else:
                raise NotImplementedError(type(elem))
        else:
            return self.eval_expansion(elem)

    def eval_fun_AddPrefixFunction(self, fun, path):
        """
        $(addprefix src/,foo bar)
        produces the result 'src/foo src/bar'.
        """
        assert isinstance(fun, functions.AddPrefixFunction), fun

        # [('pfx/', True)]
        prefixes = self.eval_expansion(fun._arguments[0], path)

        # [(' first second y', CONFIG_G == y), (' first second ',
        # CONFIG_G == undef), (' first second m', CONFIG_G == m)]
        names = self.eval_expansion(fun._arguments[1], path)

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

    def eval_fun_SubstFunction(self, fun, path):
        assert isinstance(fun, functions.SubstFunction), fun
        from_vals = self.eval_expansion(fun._arguments[0], path)
        to_vals = self.eval_expansion(fun._arguments[1], path)
        in_vals = self.eval_expansion(fun._arguments[2], path)

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

    def eval_fun_VariableRef(self, fun, path):
        assert isinstance(fun, functions.VariableRef), fun

        names = self.eval_expansion(fun.vname, path)
        rs = []
        for name, _ in names:
            if name in path.states:
                val = path.states[name].val
                vals = [(val, zsolver.T)]

            elif name.startswith(Settings.sym_prefix):
                vals = self.eval_config_var(name)
            else:
                mlog.warn("'{}' undefined in path".format(name))
                vals = [(zsolver.Undef_Val, zsolver.T)]
            rs.extend(vals)

        return rs

    def eval_config_var(self, name):
        assert name.startswith(Settings.sym_prefix), name

        if name not in self.zvars:
            self.zvars[name] = ZSolver.get_tristate_sort(name)
        s = self.zvars[name]

        vals = [(k, s == zsolver.COptD[k]) for k in zsolver.COptD]
        return vals


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
        makefiles = get_makefiles(self.makefile_paths, cond=None)
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


def uniq(val):
    cache = set()
    vals = []
    for v in val.split():
        if v not in cache:
            cache.add(v)
            vals.append(v)

    val = ' '.join(vals)
    return val


if __name__ == '__main__':

    import argparse
    aparser = argparse.ArgumentParser(
        "find interactions from Kbuild Makefiles")
    ag = aparser.add_argument
    ag('paths',
       nargs="*",
       type=str,
       help="""paths to Linux Makefiles or dirs""")

    ag("--log_level", "-log_level",
       help="set logger info",
       type=int,
       choices=range(5),
       default=3)

    ag('--case-study',
       type=str,
       help="""avail options: busybox, linux, fromfile""")

    args = aparser.parse_args()

    from vcommon import getLogLevel, getLogger
    if args.log_level != logger_level and 0 <= args.log_level <= 4:
        logger_level = args.log_level

    logger_level = getLogLevel(logger_level)
    mlog = getLogger(__name__, logger_level)
    if __debug__:
        mlog.warn("DEBUG MODE ON. Can be slow! (Use python -O to optimize)")

    paths = args.paths
    case_study = args.case_study
    if case_study:
        case_study = case_study.lower()
        if case_study == "alldirs":
            path = args.paths[0]
            paths = [os.path.join(path, sdir) for sdir in os.listdir(path)]
            paths = [p for p in paths if os.path.isdir(p)]
        elif case_study == "fromfile":
            def _f(l):
                parts = l.split()
                if (not parts[0].startswith("#") and
                    len(parts) > 1 and parts[1].startswith('/') and
                    all(x not in parts[1] for x in set([
                        '/tools/'
                        '/arch/arm/', '/arch/arm64/',
                        '/arch/sh', '/arch/s390']))):
                    # 'Kbuild' in parts[1]):
                    return parts[1]
                else:
                    return None

            path = args.paths[0]
            paths = [_f(l) for l in CM.iread(path)]
            paths = [p for p in paths if p]

    myrun = Run(paths)
    myrun.go()


# exploit 1
# paths in makefiles have many same state contents, so can merge .  e.g.,  x$y  = ...  ,  2 diff paths but same state.
