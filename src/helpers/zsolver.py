from collections import OrderedDict
from functools import reduce
import pdb
import z3

import helpers.vcommon as CM
import settings
mlog = CM.getLogger(__name__, settings.logger_level)

DBG = pdb.set_trace


__simplify_cache__ = {}
T = z3.BoolVal(True)
F = z3.BoolVal(False)


def get_from_simplify_cache(f):
    assert z3.is_expr(f), f
    return __simplify_cache__.get(f)  # ret None if not found


def to_smt2_str(f, status="unknown", name="benchmark", logic=""):
    v = (z3.Ast * 0)()
    s = z3.Z3_benchmark_to_smtlib_string(
        f.ctx_ref(), name, logic, status, "", 0, v, f.as_ast())
    return s


def from_smt2_str(s):
    assertions = z3.parse_smt2_string(s)
    expr = T if not assertions else assertions[0]
    assert z3.is_expr(expr), expr
    return expr


def simplify(f):
    assert z3.is_expr(f), f

    f_ = get_from_simplify_cache(f)
    if f_ is not None:
        return f_

    assert z3.is_expr(f), f
    t = z3.Tactic('ctx-solver-simplify')
    #t = z3.Tactic('ctx-simplify')
    f_ = t(f).as_expr()

    __simplify_cache__[f] = f_
    return f_


def neg(p):
    assert z3.is_expr(p), p
    if p is T:
        return F
    elif p is F:
        return T
    else:
        return z3.simplify(z3.Not(p))


def conj(p, q):
    assert z3.is_expr(p), p
    assert z3.is_expr(q), q

    if p is T:
        return q
    elif q is T:
        return p
    else:
        return z3.simplify(z3.And(p, q))


def mconj(cs):
    assert cs
    return reduce(lambda p, q: conj(p, q), cs[1:], cs[0])


def disj(p, q):
    assert z3.is_expr(p), p
    assert z3.is_expr(q), q

    if p is T or q is T:
        return T
    else:
        f = z3.simplify(z3.Or(p, q))
        return f


def mdisj(cs):
    assert cs
    f = reduce(lambda p, q: disj(p, q), cs[1:], cs[0])
    return f


class ZSolver:
    __config_vars__ = OrderedDict()

    def __init__(self, zstate):
        names, vals = zip(*zstate.states.items())
        self.COptTyp, exprs = z3.EnumSort(zstate.name, names)
        self.COptD = dict(zip(vals, exprs))
        self.undef_val = zstate.states['undef']
        self.solver = z3.Solver()

    def check(self, f):
        assert z3.is_expr(f), f
        self.solver.push()
        self.solver.add(f)
        ret = self.solver.check()
        self.solver.pop()
        return ret

    def is_sat(self, f):
        assert z3.is_expr(f), f
        if f is T:
            return True
        elif f is F:
            return False
        else:
            ret = self.check(f)
            return ret == z3.sat

    def is_valid(self, f):
        assert z3.is_expr(f), f
        if f is T:
            return True
        elif f is F:
            return False
        else:
            ret = self.check(z3.Not(f))
            return ret == z3.unsat

    def get_tristate_sort(self, name):
        assert isinstance(name, str) and name, name
        if name not in self.__config_vars__:
            self.__config_vars__[name] = z3.Const(name, self.COptTyp)
        return self.__config_vars__[name]

    @property
    def typ_info(self):
        """
        type information that can be saved to file
        """

        typ = (self.COptTyp.name(),
               [(v, e.decl().name()) for v, e in
                self.COptD.items()],
               list(self.__config_vars__))
        return typ

    @staticmethod
    def load_obj(typ_info):
        """
        reconstruct type info from object
        """
        name, vals_exprs, config_vars = typ_info
        vals, exprs = zip(*vals_exprs)

        cOptTyp, exprs = z3.EnumSort(name, exprs)
        cOptD = dict(zip(vals, exprs))
        config_vars = OrderedDict((name, cOptTyp) for name in config_vars)

        return cOptTyp, cOptD, config_vars
