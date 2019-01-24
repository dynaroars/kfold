from time import time

import z3

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
    def get_from_simplify_cache(f):
        assert z3.is_expr(f), f
        if f in ZSolver.__simplify_cache__:
            return ZSolver.__simplify_cache__[f]
        else:
            return None

    @staticmethod
    def to_smt2_str(f, status="unknown", name="benchmark", logic=""):
        v = (z3.Ast * 0)()
        s = z3.Z3_benchmark_to_smtlib_string(f.ctx_ref(), name, logic, status, "", 0, v, f.as_ast())
        return s
        
    @staticmethod
    def from_smt2_str(s):
        e = z3.parse_smt2_string(s)
        if not e: # []
            e = ZSolver.T
        else:
            e = e[0]
        assert z3.is_expr(e), e
        return e
    
    @staticmethod
    def simplify(f):
        assert z3.is_expr(f), f

        f_ = ZSolver.get_from_simplify_cache(f)
        if f_ is not None:
            return f_
        
        assert z3.is_expr(f), f
        t = z3.Tactic('ctx-solver-simplify')
        f_ = t(f).as_expr()

        ZSolver.__simplify_cache__[f] = f_
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
            f =  z3.simplify(z3.Or(p, q))
            return f

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
