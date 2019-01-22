import copy
from collections import OrderedDict, namedtuple
import itertools
from time import time
import os.path
import pdb
trace = pdb.set_trace
from multiprocessing import Pool
from pymake import parser, parserdata, data, functions
import z3
import vcommon as CM
pause = CM.pause

logger_level = 3
class Settings:
    target_vars = set(['obj-', 'lib-'])
    do_mp = True
    
class ZSolver:
    __config_ct__ = 0
    __simplify_cache__ = {}
    T = z3.BoolVal(True)
    F = z3.BoolVal(False)


    #COptVals = ["y", "m", "undef"]
    COptVals = ["y", "m"]
    COptTyp, COptSymVals = z3.EnumSort("TriState", COptVals)
    COptD = dict(zip(COptVals, COptSymVals))

    def __init__(self):
        self.solver = z3.Solver()

    @staticmethod
    def to_smt2_str(f, status="unknown", name="benchmark", logic=""):
        v = (z3.Ast * 0)()
        s = z3.Z3_benchmark_to_smtlib_string(f.ctx_ref(), name, logic, status, "", 0, v, f.as_ast())
        return s
        
    @staticmethod
    def from_stmt2_str(s):
        return z3.parse_smt2_string(s)[0]
    
    @staticmethod
    def simplify(f):
        assert z3.is_expr(f), f
        if f in ZSolver.__simplify_cache__:
            #print 'in cache {}'.format(f)
            return ZSolver.__simplify_cache__[f]
            
        assert z3.is_expr(f), f
        t = z3.Tactic('ctx-solver-simplify')
        f_ = t(f).as_expr()

        ZSolver.__simplify_cache__[f] = f_
        #mlog.debug("{} =>\n{}".format(f, f_))
        return f_
    
    def check(self, f):
        assert z3.is_expr(f), f
        
        st = time()
        self.solver.push()
        self.solver.add(f)
        ret = self.solver.check()
        self.solver.pop()
        return ret

    def is_sat(self, f):
        assert z3.is_expr(f), f
        if f is ZSolver.T:
            return True
        elif f is ZSolver.F:
            return False
        else:
            ret = self.check(f)
            return ret == z3.sat
    
    @staticmethod
    def conj(p, q):
        assert z3.is_expr(p), p
        assert z3.is_expr(q), q
        
        if p is ZSolver.T:
            return q
        elif q is ZSolver.T:
            return p
        else:
            return z3.simplify(z3.And(p, q))

    @staticmethod
    def mconj(cs):
        assert cs
        return reduce(lambda p, q: ZSolver.conj(p,q), cs[1:], cs[0])        

    @staticmethod
    def disj(p, q):
        assert z3.is_expr(p), p
        assert z3.is_expr(q), q
        
        if p is ZSolver.T or q is ZSolver.T:
            return ZSolver.T
        else:
            return z3.simplify(z3.Or(p, q))

    @staticmethod
    def mdisj(cs):
        assert cs
        f = reduce(lambda p, q: ZSolver.disj(p,q), cs[1:], cs[0])
        return f
        
    @staticmethod
    def get_tristate_sort(name):
        ZSolver.__config_ct__ += 1
        return z3.Const(name, ZSolver.COptTyp)

    
    @staticmethod
    def get_val_expr(name, val):
        if val not in ZSolver.COptD:
            raise NotImplementedError
        return ZSolver.COptD[val]
    

    @staticmethod
    def get_comparison_pair(s1, s2):
        assert z3.is_expr(s1) or (isinstance(s1, str) and s1), s1
        assert z3.is_expr(s2) or (isinstance(s2, str) and s2), s2

        if z3.is_expr(s1) and z3.is_expr(s2):
            return (s1, s2)
        
        elif not z3.is_expr(s1) and not z3.is_expr(s2):
            raise NotImplementedError
        
        elif z3.is_expr(s1) and not z3.is_expr(s2):
            #figure the type of s1
            val = ZSolver.get_val_expr(s1, s2)
            return s1, val
        
        else:
            assert not z3.is_expr(s1) and z3.is_expr(s2)
            val = ZSolver.get_val_expr(s2, s1, d)
            return s2, val
        
BaseVar = namedtuple("BaseVar","name val flavor")

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


    @staticmethod
    def get_flavor(token):
        if token == "=":
            flavor = Var.RECURSE
        elif token in set([":=", "::="]) or token in set(["+="]):
            flavor = Var.SIMPLY
        else:
            raise NotImplementedError("token {}".format(token))

        return flavor

class Path:
    
    __ct__ = 0
    
    def __init__(self, cond, states):
        assert isinstance(states, dict)
        self.cond = cond
        self.states = states
        Path.__ct__ += 1        

    def __del__(self):
        Path.__ct__ -= 1

    def fork(self, newcond, ignore_targets=False):
        """
        Create a new path with newcond
        """
        newstates = {}
        for name, v in self.states.iteritems():
            if ignore_targets and Path.is_target(name):
                continue
            newstates[name] = v.fork()
        return Path(newcond, newstates)

    def __str__(self):
        ss = []
        ss.append("cond: {}".format(self.cond))
        ss.append('; '.join(str(self.states[v]) for v in self.states))
        return '\n'.join(ss)

    def set_var(self, name, token, val):
        assert isinstance(name, str), name
        assert isinstance(token, str) # and token in {'='}, token
        assert isinstance(val, str), val

        if name not in self.states or token in set(["=", ":="]):
            if name in self.states:
                mlog.warn('need more precise semantics of {}'.format(token))
            self.states[name] = Var(name, uniq(val), Var.get_flavor(token)) 
        else:
            if token == "+=":
                new_val = self.states[name].val + ' ' +  val
                new_val = uniq(new_val)
                self.states[name] = self.states[name].fork_val(new_val) #append(val)
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

class Paths(list):
    def __str__(self):
        return '\n'.join("*** path {} ***\n{}".format(i + 1, path)
                         for i, path in enumerate(self))

    def split(self):
        assert self, self
        new_paths = Paths()
        
        for path in self:
            if (not path.states or #no state
                all(Path.is_not_target(name) for name in path.states)):
                new_paths.append(path)  #keep path as is
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
                            new_path = path.fork(path.cond, ignore_targets=True)
                            new_path.states[name] = myvar.fork_val(v)
                            new_paths.append(new_path)
                            
        assert new_paths
        return new_paths
        
    def merge(self):
        assert self, self

        groups = {}
        for path in self:
            state_hash = path.state_hash
            if state_hash not in groups:
                groups[state_hash] = []
            groups[state_hash].append(path)

        if len(groups) == len(self):
            return self


        # tasks = groups.values()
        # assert tasks

        def _merge(gpaths):
            assert len(gpaths)
            merge_paths = []
            path = gpaths[0]
            if len(gpaths) > 1:
                gcond = ZSolver.mdisj([path.cond for path in gpaths])
                path.cond = ZSolver.simplify(gcond)
            return path


            
        # def wprocess(tasks, Q):
        #     rs = [z3.BoolVal("1") for _ in tasks]

        #     if Q is None:
        #         return rs
        #     else:
        #         Q.put(rs)

        # wrs = CM.Miscs.runMP('merge', tasks, wprocess, chunksiz=2,
        #                      doMP=Settings.do_mp and len(tasks) >= 2)

        #merge_paths = Paths()
        # for mpath in wrs:
        #     merge_paths.append(mpath)
        
        # 
        merge_paths = Paths(_merge(gpaths) for gpaths in groups.itervalues())
        return merge_paths


    def merge_mp(self):
        assert self, self

        st_0 = time()
        groups = {}
        for path in self:
            state_hash = path.state_hash
            if state_hash not in groups:
                groups[state_hash] = []
            groups[state_hash].append(path)

        if len(groups) == len(self):
            return self

        et_0 = time()-st_0

        st_1 = time()
        simplified_paths = []
        other_paths = []
        for gpaths in groups.itervalues():
            path = gpaths[0]
            if len(gpaths) > 1:
                path.cond = ZSolver.mdisj([path.cond for path in gpaths])
                other_paths.append(path)
            else:
                simplified_paths.append(path)

        et_1 = time()-st_1


        st_2 = time()
        if other_paths:
            for path in other_paths:
                path.cond = ZSolver.simplify(path.cond)


        # tasks = other_paths
        # if tasks:
        #     def _simplify(i):
        #         gcond = ZSolver.simplify(other_paths[i].cond)
        #         #print "{} => \n{}".format(other_paths[i].cond, gcond)
        #         other_paths[i].cond = gcond

        #     def wprocess(tasks, Q):
        #         rs = [_simplify(i) for i in range(len(tasks))]

        #         if Q is None:
        #             return rs
        #         else:
        #             Q.put(rs)

        #     wrs = CM.Miscs.runMP('merge', tasks, wprocess, chunksiz=2,
        #                          doMP=Settings.do_mp and len(tasks) >= 2)

        #     for i in range(len(tasks)):
        #         _simplify(i)

        et_2 = time()-st_2
                
        merge_paths = Paths(simplified_paths + other_paths)
        mlog.debug('t0 {}, t1 {}, t2 {}, total {}'.format(et_0,et_1,et_2,time()-et_2))
        return merge_paths
    
        
class Skanner:
    def __init__(self, makefile):
        assert os.path.isfile(makefile), makefile

        self.solver = ZSolver()
        
        makefile_ = open(makefile, "rU")
        stmts = makefile_.read()
        makefile_.close()

        mlog.info("parsing: '{}'".format(makefile))
        self.topdir = os.path.dirname(makefile)
        self.zvars = {}
        
        self.stmts = parser.parsestring(stmts, makefile_.name)

        self.subdirs = []
        
    def go(self):
        paths = self.parse_stmts(self.stmts, Path(ZSolver.T, {}))
        return paths, self.subdirs


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
                    new_paths.extend(new_paths_)

                elif isinstance(stmt, parserdata.ConditionBlock):
                    new_paths_ = self.parse_conditionblock(stmt, path)
                    new_paths.extend(new_paths_)
                    
                elif isinstance(stmt, (parserdata.Rule,
                                       parserdata.StaticPatternRule)):
                    mlog.warn("Cannot parse Rule: {}".format(stmt))
                    new_paths.append(path)
                    
                elif isinstance(stmt, parserdata.Command):
                    mlog.warn("Cannot parse Command: {}".format(stmt))
                    new_paths.append(path)

                else:
                    raise NotImplementedError(
                        "cannot parse {}".format(stmt))

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
            merge_paths = split_paths.merge()
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

        return paths
    
    def parse_conditionblock(self, stmt, path):
        assert isinstance(stmt, parserdata.ConditionBlock), stmt
        
        def add_paths(cond, stmts):
            newcond = ZSolver.conj(path.cond, cond)

            # new_path = path.fork(newcond)
            # paths = self.parse_stmts(stmts, new_path)
            # return paths
            
            if self.solver.is_sat(newcond):
                new_path = path.fork(newcond)
                paths = self.parse_stmts(stmts, new_path)
                return paths
            else:
                return []
            
        if_cond, then_stmts = stmt[0] #if/then branch
        if_cond = self.eval_condition(if_cond, path)

        paths = add_paths(if_cond, then_stmts)

        else_cond = z3.Not(if_cond)
        
        if len(stmt) == 1:  #no else branch, treats as else: empty
            else_stmts = []
            paths_ = [path]  #continue with original path
            paths_ = add_paths(else_cond, else_stmts)
            paths.extend(paths_)
        elif len(stmt) == 2: #else branch
            _, else_stmts = stmt[1]
            paths_ = add_paths(else_cond, else_stmts)
            paths.extend(paths_)
        else:
            raise NotImplementedError
            
        return paths
    
    def eval_condition(self, cond, path):
        """
        evaluation arguments of the condition and return a Z3 condition
        """
        if isinstance(cond, parserdata.EqCondition):
            exp1 = self.eval_expansion(cond.exp1, path, do_eval=False)
            #[(CONFIG_A, True)]
            assert len(exp1) == 1 and exp1[0][1] is ZSolver.T, exp1
            exp1 = exp1[0][0]
            
            exp2 = self.eval_expansion(cond.exp2, path, do_eval=False)
            #[('y', True)])
            assert len(exp2) == 1 and exp2[0][1] is ZSolver.T, exp2            
            exp2 = exp2[0][0]

            exp1, exp2 = ZSolver.get_comparison_pair(exp1, exp2)
            cond = exp1 == exp2
            return cond
        
        elif isinstance(cond, parserdata.IfdefCondition):
            assert isinstance(cond.exp, data.StringExpansion), cond.exp
            exp = "$({})".format(cond.exp.s)
            exp = self.eval_fake_expansion(exp, path, do_eval=False)
            assert len(exp) == 1 and exp[0][1] is ZSolver.T, exp
            exp = exp[0][0]
            undef_val = ZSolver.get_val_expr(exp, 'undef') 
            if cond.expected:
                cond = exp != undef_val
            else:  #ifndef ..
                cond = exp == undef_val

            return cond
        else:
            mlog.warn("Cannot parse condition: {}".format(repr(cond)))


    def parse_setvar(self, stmt, path):
        assert isinstance(stmt, parserdata.SetVariable), stmt

        nameexp = stmt.vnameexp
        token = stmt.token
        value = stmt.value
        names = self.eval_expansion(nameexp, path)
        values = self.eval_value(value, path)
        
        new_paths = []
        for (name, ncond), (val, vcond) in itertools.product(*[names, values]):
            newcond = ZSolver.conj(path.cond, ZSolver.conj(ncond, vcond))

            # new_path = path.fork(newcond)
            # new_path.set_var(name, token, val)
            # new_paths.append(new_path)

            if self.solver.is_sat(newcond):
                new_path = path.fork(newcond)
                new_path.set_var(name, token, val)
                new_paths.append(new_path)
            else:
                mlog.debug('unsat: cond len {}'.format(len(str(newcond))))
        return new_paths


    def combine(self, ts, delim=''):
        """
        take in a list of tuple(str, cond) and 
        combine the strs if cond is satisfied
        Example 1
        ts = [[('my-', None)], [('on', None)], [('-', None)], [('y', CONFIG_A == y), ('m', CONFIG_A == m)]]
        output = [('my-on-y', CONFIG_A == y), ('my-on-m', CONFIG_A == m)]
        """
        assert ts

        if len(ts) == 1:
            return ts[0]

        #print 'ts', ts
        
        comb = []
        for pair in itertools.product(*ts):
            ss, cs = zip(*pair)
            c = ZSolver.mconj(cs)
            comb.append((delim.join(ss), c))

        return comb
        
    def eval_value(self, value, path):
        value = value.strip()
        if not value:
            return [('', ZSolver.T)]
        
        values = []
        for value in value.split():
            values_ = self.eval_fake_expansion(value, path)
            values.append(values_)

        comb = self.combine(values, delim=" ")
        return comb
        
    def eval_fake_expansion(self, expansion, path, do_eval=True):
        if not '$' in expansion:
            return [(expansion, ZSolver.T)]
        else:
            stmts = parser.parsestring(expansion, None)
            assert len(stmts) == 1 and isinstance(stmts[0], parserdata.EmptyDirective), stmts
            ret = self.eval_expansion(stmts[0].exp, path, do_eval)
            #print 'expansion {} evals to {}'.format(expansion, ret)
            return ret

    def eval_expansion(self, expansion, path, do_eval=True):
        if isinstance(expansion, data.StringExpansion): #'x'
            return [(expansion.s, ZSolver.T)]
        else:
            assert isinstance(expansion, data.Expansion), expansion
                
            elems = [self.eval_elem(elem, isfun, path, do_eval)
                     for elem, isfun in expansion]
            return self.combine(elems)
        
    def eval_elem(self, elem, isfun, path, do_eval=True):
        if isinstance(elem, str):  
            return [(elem, ZSolver.T)]
        elif isfun: 
            if isinstance(elem, functions.VariableRef):
                return self.eval_fun_VariableRef(elem, path, do_eval)
            else:
                raise NotImplementedError
        else:
            return self.eval_expansion(elem)
        
    def eval_fun_VariableRef(self, fun, path, do_eval=True):
        assert isinstance(fun, functions.VariableRef), fun
        
        names = self.eval_expansion(fun.vname, path) #CONFIG_FOO
        rs = []
        for name, _ in names:
            if name in path.states:
                val = path.states[name].val
                vals = [(val, ZSolver.T)]

            elif name.startswith("CONFIG_"):
                vals = self.eval_var(name, do_eval)
            else:
                mlog.warn('cannot eval {}'.format(name))
                vals = [('', ZSolver.T)]
                
            rs.extend(vals)

        return rs

    def eval_var(self, name, do_eval):
        
        if name not in self.zvars:
            self.zvars[name] = ZSolver.get_tristate_sort(name)
        s = self.zvars[name]

        if do_eval:
            #vals = [(k, s == d['vals'][k]) for k in d['vals']]
            vals = [(k, s == ZSolver.COptD[k]) for k in ZSolver.COptD]
        else:
            vals = [(s, ZSolver.T)]

        return vals
    
class Run:
    def __init__(self, paths):
        self.paths = paths
        
    def go(self):
        results = []
        remaining = list(self.paths)
        while remaining:
            #parallel
            results_ = [self.extract(path) for path in remaining] 
            remaining = []
            for paths, subdirs in results_:
                results.append(paths)
                remaining.extend(subdirs)
        return results

    def extract(self, path):
        makefile = self.get_makefile(path)
        if not makefile:
            mlog.warn("{}: cannot process".format(path))
            return None
        
        skanner = Skanner(makefile)
        paths, subdirs = skanner.go()
        mlog.debug(paths)
        mlog.debug("total {} paths".format(len(paths)))
        return paths, subdirs
    
    @classmethod
    def get_makefile(cls, path):
        #use Kbuild file if found, otherwise try Makefile
        if not os.path.exists(path):
            return None

        makefile = path
        if os.path.isdir(path):
            makefile = os.path.join(path, "Kbuild")
            if not os.path.isfile(makefile):
                makefile = os.path.join(path, "Makefile")

        if not os.path.isfile(makefile):
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
    aparser = argparse.ArgumentParser("find interactions from Kbuild Makefiles")
    ag = aparser.add_argument
    ag('paths',
       nargs="*",
       type=str,
       help="""paths to Linux Makefiles or dirs""")
    
    ag("--log_level", "-log_level",
       help="set logger info",
       type=int, 
       choices=range(5),
       default = 3)

    ag('--case-study',
       type=str,
       help="""avail options: busybox/linux""")
    
    args = aparser.parse_args()

    from vcommon import getLogLevel , getLogger
    if args.log_level != logger_level and 0 <= args.log_level <= 4:
        logger_level = args.log_level

    logger_level = getLogLevel(logger_level)
    mlog = getLogger(__name__, logger_level)    
    if __debug__:
        mlog.warn("DEBUG MODE ON. Can be slow! (Use python -O ... for optimization)")

    paths = args.paths
    case_study = args.case_study
    if case_study:
        case_study = case_study.lower()
        if case_study == "alldirs":
            path = args.paths[0]
            paths = [os.path.join(path, sdir) for sdir in os.listdir(path)]
            paths = [p for p in paths if os.path.isdir(p)]

    myrun = Run(paths)        
    myrun.go()
    
    


#exploit 1
#paths in makefiles have many same state contents, so can merge .  e.g.,  x$y  = ...  ,  2 diff paths but same state.
