from abc import ABC, abstractmethod
from collections import OrderedDict
import itertools
import pdb

from pymake3 import parser, parserdata, data, functions

import helpers.vcommon as CM
import helpers.zsolver as zsolver

import settings
mlog = CM.getLogger(__name__, settings.logger_level)

DBG = pdb.set_trace


class ExpansionBase(ABC):
    def __init__(self, solver):
        self.solver = solver

    @classmethod
    def combine(cls, ts, delim=''):
        """
        take in a list of list of tuple(str, cond) and
        combine the strs if cond is satisfied
        Example 1
        ts = [[('my-', None)], [('on', None)], [('-', None)],
                [('y', CONFIG_A == y), ('m', CONFIG_A == m)]]
        output = [('my-on-y', CONFIG_A == y), ('my-on-m', CONFIG_A == m)]
        """
        assert ts, ts

        def uniq(l):
            s = set()
            ret = []
            for e in l:
                if e not in s:
                    s.add(e)
                    ret.append(e)
            return ret

        ts = [uniq(t) for t in ts]
        ts = [t for t in ts if t]

        if not ts:
            return []
        elif len(ts) == 1:
            return ts[0]
        comb = []
        for pair in itertools.product(*ts):
            ss, cs = list(zip(*pair))
            c = zsolver.mconj(cs)
            comb.append((delim.join(ss), c))

        return comb

    def do_val(self, val, states):
        """
        t1 := 1 2 3
        obj-y += $(t1) $(t1)
        """
        assert isinstance(val, str), val
        ret = self.do_fake_expansion(val.strip(), states)
        return ret

    def do_fake_expansion(self, expansion, states):
        expansion = str(expansion)
        stmts = parser.parsestring(expansion, None)

        if not stmts:
            return []

        if not isinstance(stmts[0], parserdata.EmptyDirective):
            # linux-3.19/drivers/isdn/hisax/Makefile
            mlog.warn("NotImplemented: {}: {}".format(
                stmts[0].__class__.__name__, stmts[0].to_source()))
            return []

        ret = self.do_expansion(stmts[0].exp, states)
        # print('do_fake_expansion ret', ret)
        return ret

    def do_expansion(self, expansion, states):
        #print('do_expansion', expansion)
        if isinstance(expansion, data.StringExpansion):  # 'x'
            ret = [(expansion.s, zsolver.T)]
        else:
            assert isinstance(expansion, data.Expansion), expansion
            elems = [self.do_elem(elem, isfun, states)
                     for elem, isfun in expansion]
            #print('mycombine', elems)
            ret = self.combine(elems)

        #print('do_expansion result', ret)
        return ret

    def do_elem(self, elem, isfun, states):
        # print('do_elem', elem)
        if isinstance(elem, str):
            #print('do_elem_str', elem)
            return [(elem, zsolver.T)]
        elif isfun:
            #print('do_elem_str fun', elem)
            try:
                if isinstance(elem, functions.VariableRef):
                    return self.do_fun_VariableRef(elem, states)
                elif isinstance(elem, functions.SubstFunction):
                    return self.do_fun_SubstFunction(elem, states)
                elif isinstance(elem, functions.PatSubstFunction):
                    return self.do_fun_PatSubstFunction(elem, states)
                elif isinstance(elem, functions.WildcardFunction):
                    return self.do_fun_WildcardFunction(elem, states)
                elif isinstance(elem, functions.FilteroutFunction):
                    return self.do_fun_Filterout(elem, states)
                elif isinstance(elem, functions.AddPrefixFunction):
                    return self.do_fun_AddPrefixFunction(elem, states)
                elif isinstance(elem, functions.CallFunction):
                    return self.do_CallFunction(elem, states)
                else:
                    raise NotImplementedError()
            except NotImplementedError:
                mlog.warn("NotImplemented: {}: {}".format(
                    elem.__class__.__name__, elem.to_source()))
                return []

        else:
            return self.do_expansion(elem, states)

    def do_CallFunction(self, fun, states):
        assert isinstance(fun, functions.CallFunction), fun

        # In /arch/x86/crypto
        # sha256_ni_supported :=$(call as-instr,sha256msg1 %xmm0$(comma)%xmm1,yes,no)
        if (len(fun._arguments) == 4 and
            isinstance(fun._arguments[0], data.StringExpansion) and
            'as-instr' == fun._arguments[0].s and
            isinstance(fun._arguments[2], data.StringExpansion) and
            'yes' == fun._arguments[2].s and
            isinstance(fun._arguments[3], data.StringExpansion) and
                'no' in fun._arguments[3].s):
            return [('yes', zsolver.T), ('no', zsolver.T)]

        raise NotImplementedError()

    def do_fun_AddPrefixFunction(self, fun, states):
        """
        $(addprefix src/,foo bar)
        produces the result 'src/foo src/bar'.
        """
        assert isinstance(fun, functions.AddPrefixFunction), fun

        # Note: $(addprefix pfx/  , g) is diff than $(addprefix pfx/,  g)

        combines = self.get_fun_arg_vals(fun, 2, states)
        d = OrderedDict()
        for (pv, pc), (nv, nc) in combines:
            cond = zsolver.conj(pc, nc)
            if self.solver.is_sat(cond):
                v = " ".join(pv + n for n in nv.split())
                d[v] = cond

        rs = list(d.items())
        return rs

    def do_fun_Filterout(self, fun, states):
        assert isinstance(fun, functions.FilteroutFunction), fun
        combines = self.get_fun_arg_vals(fun, 2, states)

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

    def do_fun_WildcardFunction(self, fun, states):
        assert isinstance(fun, functions.WildcardFunction), fun

        exps = self.do_expansion(fun._arguments[0], states)
        d = OrderedDict()
        import fnmatch
        import os
        for wc, cond in exps:
            if self.solver.is_sat(cond):
                dir_ = list(states['src'].vals)[0]
                assert dir_.is_dir(), dir_
                v = ' '.join(fnmatch.filter(os.listdir(dir_), wc))
                if v not in d:
                    d[v] = cond

        rs = list(d.items())
        return rs

    def do_fun_PatSubstFunction(self, fun, states):
        assert isinstance(fun, functions.PatSubstFunction), fun
        import re

        combines = self.get_fun_arg_vals(fun, 3, states)
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

    def do_fun_SubstFunction(self, fun, states):
        assert isinstance(fun, functions.SubstFunction), fun
        combines = self.get_fun_arg_vals(fun, 3, states)

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

    @abstractmethod
    def do_fun_VariableRef(self, fun, states):
        assert isinstance(fun, functions.VariableRef), fun
        assert isinstance(states, dict), states

        # print('do_fun_VariableRef', fun)
        names = self.do_expansion(fun.vname, states)
        #print('do_fun_VariableRef names', fun, names)
        rs = []
        for name, cond in names:
            if name in states:
                myvar = states[name]
                vals = []
                for val in myvar.vals:
                    if myvar.is_recurse:
                        vals.extend(self.do_fake_expansion(val, states))
                    else:
                        vals.append((val, zsolver.T))

            elif (self.solver.mysettings.is_copt(name) or
                  self.solver.mysettings.is_xopt(name)):
                vals = self.do_config_var(name)

            else:
                mlog.debug("'{}' undefined in path".format(name))
                vals = []

            vals = [(v_, zsolver.mconj([cond, cond_])) for v_, cond_ in vals]
            rs.extend(vals)
        #print('do_fun_VariableRef return', fun, rs)
        return rs, names

    def do_config_var(self, name):
        assert (self.solver.mysettings.is_copt(name) or
                self.solver.mysettings.is_xopt(name)), name

        symbol, optd = self.solver.get_sort(name)
        ret = [(k, symbol == optd[k]) for k in optd]
        # print('do_config_var', name, ret)
        return ret

    def get_fun_arg_vals(self, fun, nargs, states):
        assert nargs >= 1, nargs
        fargs = [fun._arguments[i] for i in range(nargs)]
        expansions = [self.do_expansion(farg, states) for farg in fargs]
        return itertools.product(*expansions)


class ExpansionSExe(ExpansionBase):

    def do_fun_VariableRef(self, fun, states):
        rs, names = super().do_fun_VariableRef(fun, states)
        return rs


class ExpansionDExe(ExpansionBase):
    def __init__(self, solver):
        super().__init__(solver)
        self.deps = set()

    def do_fun_VariableRef(self, fun, states):
        rs, names = super().do_fun_VariableRef(fun, states)
        for name, _ in names:
            self.deps.add(name)
        return rs
