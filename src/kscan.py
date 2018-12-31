from collections import OrderedDict
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

    def zcheck(self, f):
        self.solver.push()
        self.solver.add(f)
        ret = self.solver.check()
        self.solver.pop()
        return ret

class Results:
    def __init__(self):
        self.conds = OrderedDict()  # file1.o -> z3expr
        self.goals = OrderedDict()   # obj-y -> [file1.o, file2.o]
        
        self.subdirs = []

    def __str__(self):
        ss = []
        # for typ in self.objs:
        #     if self.objs[typ]:
        #         ss.append("{}: {}".format(typ, ', '.join(self.objs[typ])))

        if self.conds:
            ss.append("individual files ({}):".format(len(self.conds)))
            for i, ifile in enumerate(self.conds):
                ss.append("{}. {}:".format(i + 1, ifile))
                for goal in self.conds[ifile]:
                    ss.append("- {}: {}".format(
                        goal, self.conds[ifile][goal]))

        if self.subdirs:
            ss.append("subdirs ({}): {}".format(
                len(self.subdirs), ','.join(self.subdirs)))

        if self.goals:
            ss.append("goals ({}):".format(len(self.goals)))
            for i, goal in enumerate(self.goals):
                ss.append("{}. {} ({}): {}".format(
                    i, goal, len(self.goals[goal]), ', '.join(self.goals[goal])))
                
        return '\n'.join(ss)

class ConfigDef(tuple):
    def __new__(cls, mdef, cond):
        return super(ConfigDef, cls).__new__(cls, (mdef, cond))

    def __init__(self, mdef, cond):
        assert z3.is_expr(cond)
        assert isinstance(mdef, str) and mdef in set(['y','m']), mdef
        self.mdef = mdef        
        self.cond = cond

    def __str__(self):
        return "({}, {})".format(self.mdef, self.cond)


class MakefileSkanner:
    def __init__(self, makefile):

        
        makefile_ = open(makefile, "rU")
        stmts = makefile_.read()
        makefile_.close()

        self.topdir = os.path.dirname(makefile)
        self.results = Results()
        self.cvars = {}
        self.stmts = parser.parsestring(stmts, makefile_.name)

        
    def go(self):
        self.parse_stmts(self.stmts, ZSolver.T)
        return self.results

    def parse_stmts(self, stmts, cond):
        for stmt in stmts:
            if isinstance(stmt, parserdata.SetVariable):
                self.parse_setvar(stmt, cond)
            # elif isinstance(stmt, parserdata.ConditionBlock):
            #     self.parse_conditionblock(stmt, cond, zcond)
            # elif isinstance(s, (parserdata.Rule, parserdata.StaticPatternRule)):
            #     self.parse_rule(s, cond, zcond)
            # elif (isinstance(s, parserdata.Include)):
            #     self.parse_include(s, cond, zcond)
            else:
                raise NotImplementedError("cannot parse {}".format(stmt))
            
    def parse_setvar(self, stmt, cond):
        """
        obj-y = foo.o
        """
        assert isinstance(stmt, parserdata.SetVariable), setvar
        assert z3.is_expr(cond), cond

        goals = self.parse_expansion(stmt.vnameexp) #'obj-y'
        token = stmt.token  #'+='
        vals = stmt.value  # foo.o
        vals = [obj for obj in vals.split()]
        vals = [os.path.join(self.topdir, obj) for obj in vals]
        #assert token == ":=", token
        # assert all(val.endswith(".o") or
        #            val.endswith("/") for val in vals), vals


        #TODO: only for certain goals (e.g., obj-*, lib-*)
        subdirs = [val for val in vals if val.endswith("/")]
        self.results.subdirs.extend(subdirs)

        def add_goal(goal, val, cond):
            self.results.conds[val][goal] = cond
            
            if goal not in self.results.goals:
                self.results.goals[goal] = []
            self.results.goals[goal].append(val)


        if isinstance(goals, str):  #obj-y  
            # if typ not in self.results.objs:
            #     self.results.objs[typ] = []

            for val in vals:  #file1.o, file2.o
                # if obj not in self.results.objs[typ]:
                #     self.results.objs[typ].append(obj)

                assert file not in self.results.conds
                self.results.conds[val] = OrderedDict()
                add_goal(goals, val, cond)
                
        else:  #obj-$(CONFIG_FOO)
            assert isinstance(goals, list), goals
            for val in vals:
                assert file not in self.results.conds
                self.results.conds[val] = OrderedDict()

                for (goal, cond) in goals:
                    add_goal(goal, val, cond)
                    

    def parse_expansion(self, expansion):
        #obj-y
        #obj-$(CONFIG_FOO)
        
        if isinstance(expansion, data.StringExpansion): #'obj-y'
            return expansion.s
        else:
            #obj-$(CONFIG_FOO)
            #['obj-', [('y', CONFIG_FOO=y), ('m', CONFIG_FOO=m)]]
            elems = [self.parse_elem(elem, isfun) for elem, isfun in expansion]
            assert len(elems) == 2
            goal = elems[0] #'obj-y'
            rest = elems[1] #[('y', CONFIG_FOO=y), ('m', CONFIG_FOO=m)]

            assert isinstance(goal, str) and goal, goal
            assert isinstance(rest, list) and len(rest) == 2, rest

            return [("{}{}".format(goal, defval), cond) for
                    defval, cond in rest]
        

    def parse_elem(self, elem, isfun):
        if isinstance(elem, str):  #"obj-"
            return elem
        elif isfun: 
            if isinstance(elem, functions.VariableRef):
                return self.parse_fun_VariableRef(elem)
            else:
                raise NotImplementedError
        else:
            return self.parse_expansion(elem)
        
    def parse_fun_VariableRef(self, fun):
        #VariableRef<../tests/makefiles/ex3.1b:1:4>(Exp<None>('CONFIG_FOO'))

        name = self.parse_expansion(fun.vname) #CONFIG_FOO
        cds = self.parse_variableref(name)
        return cds

    def parse_variableref(self, name):
        #return possible conditions for name
        
        assert isinstance(name, str) and name

        if not name.startswith("CONFIG_"):
            mlog.warn("Cannot evaluate variable '{}'".format(name))
            
        defy = "y"
        condy = z3.Bool("{}={}".format(name, defy))

        defm = "m"
        condm = z3.Bool("{}={}".format(name, defm))

        return [(defy, condy), (defm, condm)]
            



class Run:
    def __init__(self, paths):
        self.paths = paths
        
    def go(self):

        remaining = list(self.paths)
        results = []
        while remaining:
            results_ = [self.extract(path) for path in remaining] #parallel
            results_ = [r for r in results_ if r]
            remaining = []
            
            for result in results_:
                results.append(result)
                remaining.extend(result.subdirs)
        return results

    def extract(self, path):
        makefile = self.get_makefile(path)
        if not makefile:
            mlog.warn("{}: cannot process".format(path))            
            return None
        
        skanner = MakefileSkanner(makefile)
        results = skanner.go()
        mlog.info("{}'s results:\n{}".format(makefile, results))
        return results
    
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
    
    args = aparser.parse_args()

    from vcommon import getLogLevel , getLogger
    if args.log_level != logger_level and 0 <= args.log_level <= 4:
        logger_level = args.log_level

    logger_level = getLogLevel(logger_level)
    mlog = getLogger(__name__, logger_level)    
    if __debug__:
        mlog.warn("DEBUG MODE ON. Can be slow! (Use python -O ... for optimization)")

    myrun = Run(args.paths)
    myrun.go()
    
    
    
