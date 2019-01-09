from collections import OrderedDict
import itertools

import os.path
import pdb
trace = pdb.set_trace

from pymake import parser, parserdata, data, functions
import z3
import vcommon as CM

logger_level = 3
class  ZSolver:
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

    @staticmethod
    def conj(p,q):
        if p is None:
            return q
        elif q is None:
            return p
        else:
            return z3.And(p,q)

    @staticmethod
    def get_tristate_sort(name):
        vs = ["y", "m"]
        ttyp, tvals = z3.EnumSort(name, vs)
        rs = [v for v in zip(vs, tvals)]
        rs.append(('typ', ttyp))
        return z3.Const(name, ttyp), dict(rs)

    
class Var(tuple):
    RECURSE = "RECURSE"   # =, define
    SIMPLY = "SIMPLY"  # := , ::=

    def __new__(cls, name, val, flavor):
        return super(Var, cls).__new__(cls, (name, val, flavor))
    
    def __init__(self, name, val, flavor):
        self.name = name
        self.val = val
        self.flavor = flavor

    def __str__(self):
        token = "=" if self.flavor == Var.RECURSE else ":="
        return "{} {} {}".format(self.name, token, self.val)

    @staticmethod
    def get_flavor(token):
        return Var.RECURSE if token == "=" else Var.SIMPLY
    
class Path:
    def __init__(self, cond, locals):
        self.cond = cond
        self.locals = locals

    def fork(self, newcond):
        """
        Create a new path with newcond
        """
        newlocals = OrderedDict()
        for k,v in self.locals.iteritems():
            newlocals[k] = v

        return Path(newcond, newlocals)
        
    def __str__(self):
        ss = ["cond: {}".format(self.cond)]
        for v in self.locals:
            ss.append(self.locals[v])

        return '\n'.join(map(str,ss))

    def set_var(self, name, token, val):
        assert isinstance(name, str), name
        assert isinstance(token, str) and token in {'='}, token
        assert isinstance(val, str) and val, val

        v = Var(name, val, Var.get_flavor(token))

        assert name not in self.locals, (name, self.locals)
        self.locals[name] = v
            
        
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
        paths = [Path(None, {})]
        paths = self.parse_stmts(self.stmts, paths)
        return paths, []

    def parse_stmts(self, stmts, paths):
        for stmt in stmts:
            if isinstance(stmt, parserdata.SetVariable):
                paths = self.parse_setvar(stmt, paths)
            elif isinstance(stmt, parserdata.ConditionBlock):
                paths = self.parse_conditionblock(stmt, paths)
                
            elif isinstance(stmt, (parserdata.Rule,
                                   parserdata.StaticPatternRule)):
                mlog.warn("Cannot parse Rule: {}".format(stmt))

            elif isinstance(stmt, parserdata.Command):
                mlog.warn("Cannot parse Command: {}".format(stmt))
                
            else:
                raise NotImplementedError(
                    "cannot parse {}".format(stmt))
            
        return paths
    
    def parse_conditionblock(self, stmt):
        assert isinstance(stmt, parserdata.ConditionBlock), stmt

        ss = []
        #if/then branch
        if_cond, then_stmts = stmt[0]

        if_cond_s = self.parse_condition(if_cond)
        ss.append(if_cond_s)
        then_stmts_s = self.parse_stmts(then_stmts)
        ss.append(then_stmts_s)
        
        #else branch
        if len(stmt) == 2:
            else_cond, else_stmts = stmt[1]
            #not much interesting info about else cond (just negation of if)
            else_cond_s = "else"
            ss.append(else_cond_s)
            else_stmts_s = self.parse_stmts(else_stmts)
            ss.append(else_stmts_s)
            
        return '\n'.join(ss)

    def parse_condition(self):
        if isinstance(cond, parserdata.EqCondition):
            exp1_s = self.parse_expansion(cond.exp1)
            exp2_s = self.parse_expansion(cond.exp2)
            return "ifeq ({},{})".format(exp1_s, exp2_s)
        else:
            mlog.warn("Cannot parse condition: {}".format(repr(cond)))


    def parse_setvar(self, stmt, paths):
        assert isinstance(stmt, parserdata.SetVariable), stmt

        nameexp = stmt.vnameexp
        token = stmt.token
        value = stmt.value

        newpaths = []        
        for path in paths:
            names = self.parse_expansion(nameexp, path)
            for name, cond in names:
                newcond = ZSolver.conj(path.cond, cond)
                if newcond is None or self.solver.check(newcond) == z3.sat:
                    newpath = path.fork(newcond)
                    newpath.set_var(name, token, value)
                    newpaths.append(newpath)

        return newpaths

    def parse_expansion(self, expansion, path):
        if isinstance(expansion, data.StringExpansion): #'x'
            return [(expansion.s, None)]
        else:
            assert isinstance(expansion, data.Expansion), expansion
                
            elems = [self.parse_elem(elem, isfun, path)
                     for elem, isfun in expansion]
            rs = []
            for pair in itertools.product(*elems):
                pair = zip(*pair)
                names, conds = pair
                name = ''.join(names)
                cond = None
                for c in conds:
                    cond = ZSolver.conj(cond, c)
                    
                rs.append((name, cond))
            
            return rs
        
    def parse_elem(self, elem, isfun, path):
        if isinstance(elem, str):  
            return [(elem, None)]
        elif isfun: 
            if isinstance(elem, functions.VariableRef):
                return self.parse_fun_VariableRef(elem, path)
            else:
                raise NotImplementedError
        else:
            return self.parse_expansion(elem)
        
    def parse_fun_VariableRef(self, fun, path):
        assert isinstance(fun, functions.VariableRef), fun
        
        names = self.parse_expansion(fun.vname, path) #CONFIG_FOO
        rs = []
        for name, _ in names:
            if name in path.locals:
                val = path.locals[name].val
                vals = [(val, None)]


            elif name.startswith("CONFIG_"):
                if name not in self.zvars:
                    self.zvars[name] = ZSolver.get_tristate_sort(name)
                s, d = self.zvars[name]
                vals = [(k, s == d[k]) for k in d
                        if k != "typ"]
                
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

        for path in paths:
            print path
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
    
    
