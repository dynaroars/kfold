import copy
from collections import OrderedDict
import itertools
import time

import os.path
import pdb
trace = pdb.set_trace

from pymake import parser, parserdata, data, functions
import z3
import vcommon as CM
pause = CM.pause

logger_level = 3
class  ZSolver:
    __config_ct__ = 0
    T = z3.BoolVal(True)
    F = z3.BoolVal(False)        

    def __init__(self):
        self.solver = z3.Solver()

    def check(self, f):
        self.solver.push()
        self.solver.add(f)
        ret = self.solver.check()
        self.solver.pop()        
        return ret

    def is_sat(self, f):
        if f is None:  #equiv to True
            return True
        ret = self.check(f)
        #print f, ret
        return ret == z3.sat
    
    @staticmethod
    def conj(p,q):
        if p is None:
            return q
        elif q is None:
            return p
        else:
            return z3.simplify(z3.And(p, q))

    @staticmethod
    def mconj(cs):
        assert cs
        return reduce(lambda p, q: ZSolver.conj(p,q), cs[1:], cs[0])        

    @staticmethod
    def disj(p,q):
        if p is None or q is None:
            return None
        else:
            return z3.simplify(z3.Or(p, q))

    @staticmethod
    def mdisj(cs):
        assert cs
        return reduce(lambda p, q: ZSolver.disj(p,q), cs[1:], cs[0])
        

    @staticmethod
    def get_tristate_sort(name):
        vs = ["y", "m"]
        ttyp, tvals = z3.EnumSort(name, vs)
        rs = [v for v in zip(vs, tvals)]
        rs.append(('typ', ttyp))
        ZSolver.__config_ct__ += 1
        return z3.Const(name, ttyp), dict(rs)

    @staticmethod
    def get_comparison_pair(s1, s2, d):
        assert z3.is_expr(s1) or (isinstance(s1, str) and s1), s1
        assert z3.is_expr(s2) or (isinstance(s2, str) and s2), s2

        if z3.is_expr(s1) and z3.is_expr(s2):
            return (s1, s2)
        elif not z3.is_expr(s1) and not z3.is_expr(s2):
            raise NotImplementedError
        elif z3.is_expr(s1) and not z3.is_expr(s2):
            #figure the type of s1
            _, d_ = d[str(s1)]
            if s2 not in d_:
                raise NotImplementedError
            return s1, d_[s2]
        else:
            assert not z3.is_expr(s1) and z3.is_expr(s2)
            _, d_ = d[str(s2)]
            if s1 not in d_:
                raise NotimplementedError
            return d_[s1], s2


class Var(tuple):
    RECURSE = "RECURSE"   # =, define
    SIMPLY = "SIMPLY"  # := , ::=

    def __new__(cls, name, val, flavor):
        cache = set()
        vals = []
        for v in val.split():
            if v not in cache:
                cache.add(v)
                vals.append(v)
                
        val = ' '.join(vals)
        ret =  super(Var, cls).__new__(cls, (name, val, flavor))
        return ret

    def __init__(self, name, val, flavor):
        self.name = name
        self._val = val
        self.flavor = flavor

    def fork(self):
        return Var(self.name, self.val, self.flavor)

    def fork_val(self, val):
        return Var(self.name, val, self.flavor)

    @property
    def val(self):
        return self._val

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
        #mlog.debug("# of paths {}".format(Path.__ct__))

    def __del__(self):
        Path.__ct__ -= 1

    def fork(self, newcond):
        """
        Create a new path with newcond
        """
        newstates = {}
        for k,v in self.states.iteritems():
            newstates[k] = v.fork()
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

        if name not in self.states or token in set(["="]):
            if name in self.states:
                mlog.warn('need more precise semantics of {}'.format(token))
            self.states[name] = Var(name, val, Var.get_flavor(token))                
        else:
            if token == "+=":
                new_val = self.states[name].val + ' ' +  val
                self.states[name] = self.states[name].fork_val(new_val) #append(val)
                #self.states[name].append(val)
            else:
                raise NotImplementedError
                
    def has_similar_state(self, other):
        if len(self.states) != len(other.states):
            return False

        if set(self.states) != set(other.states):
            return False

        return all(self.states[k] == other.states[k] for k in self.states)

    @property
    def state_hash(self):
        fs = frozenset(sorted(self.states.items()))
        ret = hash(fs)
        return ret
        
    @staticmethod
    def merge(paths):
        assert paths, paths
        st = time.time()

        groups = {}
        for path in paths:
            state_hash = path.state_hash
            if state_hash not in groups:
                groups[state_hash] = []
            groups[state_hash].append(path)

        if len(groups) == len(paths):
            return paths

        merge_paths = []
        for gpaths in groups.itervalues():
            gcond = ZSolver.mdisj([path.cond for path in gpaths])
            path = gpaths[0]
            path.cond = gcond
            merge_paths.append(path)

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
        paths = self.parse_stmts(self.stmts, Path(None, {}))
        return paths, []

    def parse_stmts(self, stmts, path):

        paths = [path]
        for stmt in stmts:
            st = time.time()
            mlog.debug("processing '{}' with {} paths".format(stmt.to_source(), len(paths)))
            
            newpaths = []
            for i, path in enumerate(paths):
                if isinstance(stmt, parserdata.SetVariable):
                    newpaths_ = self.parse_setvar(stmt, path)
                    newpaths.extend(newpaths_)

                elif isinstance(stmt, parserdata.ConditionBlock):
                    newpaths_ = self.parse_conditionblock(stmt, path)
                    newpaths.extend(newpaths_)
                    
                elif isinstance(stmt, (parserdata.Rule,
                                       parserdata.StaticPatternRule)):
                    mlog.warn("Cannot parse Rule: {}".format(stmt))
                    newpaths.append(path)
                    
                elif isinstance(stmt, parserdata.Command):
                    mlog.warn("Cannot parse Command: {}".format(stmt))
                    newpaths.append(path)

                else:
                    raise NotImplementedError(
                        "cannot parse {}".format(stmt))

            merge_paths = Path.merge(newpaths)            
            mlog.debug("paths: orig {}, generated {}, merged {}, in memory {} , config vars {}".format(
                len(paths), len(newpaths), len(merge_paths), Path.__ct__,  ZSolver.__config_ct__))

            paths = merge_paths
                
        return paths
    
    def parse_conditionblock(self, stmt, path):
        assert isinstance(stmt, parserdata.ConditionBlock), stmt
        
        def add_paths(cond, stmts):
            newcond = ZSolver.conj(path.cond, cond)
            if self.solver.is_sat(newcond):
                newpath = path.fork(newcond)
                paths = self.parse_stmts(stmts, newpath)
                return paths

            
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
            #[('CONFIG_A', None)]
            assert len(exp1) == 1 and exp1[0][1] is None, exp1
            exp1 = exp1[0][0]
            
            exp2 = self.eval_expansion(cond.exp2, path, do_eval=False)
            #[('y', None)])
            assert len(exp2) == 1 and exp2[0][1] is None, exp2            
            exp2 = exp2[0][0]

            exp1, exp2 = ZSolver.get_comparison_pair(exp1, exp2, self.zvars)
            cond = exp1 == exp2
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
        
        newpaths = []        
        for (name, ncond), (val, vcond) in itertools.product(*[names, values]):
            newcond = ZSolver.conj(path.cond, ZSolver.conj(ncond, vcond))
            if self.solver.is_sat(newcond):
                newpath = path.fork(newcond)
                newpath.set_var(name, token, val)
                newpaths.append(newpath)

        return newpaths


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

        #print 'comb', comb
        return comb
        
    def eval_value(self, value, path):
        value = value.strip()
        if not value:
            return [('', None)]
        
        values = []
        for value in value.split():
            values_ = self.eval_fake_expansion(value, path)
            values.append(values_)

        comb = self.combine(values, delim=" ")
        return comb
        
    def eval_fake_expansion(self, expansion, path):
        if not '$' in expansion:
            return [(expansion, None)]
        else:
            stmts = parser.parsestring(expansion, None)
            assert len(stmts) == 1 and isinstance(stmts[0], parserdata.EmptyDirective), stmts
            ret = self.eval_expansion(stmts[0].exp, path)
            #print 'expansion {} evals to {}'.format(expansion, ret)
            return ret

    def eval_expansion(self, expansion, path, do_eval=True):
        if isinstance(expansion, data.StringExpansion): #'x'
            return [(expansion.s, None)]
        else:
            assert isinstance(expansion, data.Expansion), expansion
                
            elems = [self.eval_elem(elem, isfun, path, do_eval)
                     for elem, isfun in expansion]
            return self.combine(elems)
        
    def eval_elem(self, elem, isfun, path, do_eval=True):
        if isinstance(elem, str):  
            return [(elem, None)]
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
                vals = [(val, None)]

            elif name.startswith("CONFIG_"):
                if name not in self.zvars:
                    self.zvars[name] = ZSolver.get_tristate_sort(name)
                s, d = self.zvars[name]
                
                if do_eval:
                    vals = [(k, s == d[k]) for k in d
                            if k != "typ"]
                else:
                    vals = [(s, None)]
            else:
                mlog.warn('cannot eval {}'.format(name))
                vals = [('', None)]
                
            rs.extend(vals)

        return rs
    

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

        mlog.info("obtained {} paths".format(len(paths)))
        # mlog.debug('\n'.join("*** path {} ***\n{}".format(i, path)
        #                      for i, path in enumerate(paths)))
        mlog.info("total {} paths".format(len(paths)))            
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
