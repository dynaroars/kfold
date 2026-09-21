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
        take in a list of tuple(str, cond) and
        combine the strs if cond is satisfied
        """
        assert ts, ts

        if len(ts) == 1:
            return ts[0]

        comb = ts[0]
        for next_t in ts[1:]:
            new_comb = []
            for s1, c1 in comb:
                for s2, c2 in next_t:
                    c = zsolver.conj(c1, c2)
                    if c is not zsolver.F:
                        new_comb.append((s1 + delim + s2, c))
            comb = new_comb
            if len(comb) > 64:
                # Bound large non-target combinatorics
                combined_str = " ".join(dict.fromkeys(s for s, _ in comb))
                comb = [(combined_str, zsolver.T)]

        return comb

    def do_val(self, val, states):
        assert isinstance(val, str), val

        val = val.strip()

        if val:
            return self.do_fake_expansion(val, states)
        else:
            return [('', zsolver.T)]

    def do_fake_expansion(self, expansion, states):
        assert isinstance(expansion, str), expansion

        d = parser.Data.fromstring(expansion, None)
        try:
            exp, token, offset = parser.parsemakesyntax(
                d, 0, (), parser.iterdata)
            return self.do_expansion(exp, states)
        except Exception:
            return [(expansion, zsolver.T)]

    def do_expansion(self, expansion, states):

        if isinstance(expansion, data.StringExpansion):  # 'x'
            return [(expansion.s, zsolver.T)]
        else:
            assert isinstance(expansion, data.Expansion), expansion
            elems = [self.do_elem(elem, isfun, states)
                     for elem, isfun in expansion]
            comb = self.combine(elems)
            return comb

    def do_elem(self, elem, isfun, states):
        if isinstance(elem, str):
            return [(elem, zsolver.T)]
        elif isfun:
            from census import GLOBAL_METRICS
            fname = getattr(elem, 'name', elem.__class__.__name__.replace('Function', '').lower())
            GLOBAL_METRICS.record_construct(f"Function:{fname}")
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
                elif isinstance(elem, functions.FilterFunction):
                    return self.do_fun_Filter(elem, states)
                elif isinstance(elem, functions.AddPrefixFunction):
                    return self.do_fun_AddPrefixFunction(elem, states)
                elif isinstance(elem, functions.AddSuffixFunction):
                    return self.do_fun_AddSuffixFunction(elem, states)
                elif isinstance(elem, functions.StripFunction):
                    return self.do_fun_Strip(elem, states)
                elif isinstance(elem, functions.FindstringFunction):
                    return self.do_fun_Findstring(elem, states)
                elif isinstance(elem, functions.SortFunction):
                    return self.do_fun_Sort(elem, states)
                elif isinstance(elem, functions.FirstWordFunction):
                    return self.do_fun_Firstword(elem, states)
                elif isinstance(elem, functions.LastWordFunction):
                    return self.do_fun_Lastword(elem, states)
                elif isinstance(elem, functions.WordsFunction):
                    return self.do_fun_Words(elem, states)
                elif isinstance(elem, functions.WordFunction):
                    return self.do_fun_Word(elem, states)
                elif isinstance(elem, functions.WordlistFunction):
                    return self.do_fun_Wordlist(elem, states)
                elif isinstance(elem, functions.DirFunction):
                    return self.do_fun_Dir(elem, states)
                elif isinstance(elem, functions.NotDirFunction):
                    return self.do_fun_NotDir(elem, states)
                elif isinstance(elem, functions.SuffixFunction):
                    return self.do_fun_Suffix(elem, states)
                elif isinstance(elem, functions.BasenameFunction):
                    return self.do_fun_Basename(elem, states)
                elif isinstance(elem, functions.IfFunction):
                    return self.do_fun_If(elem, states)
                elif isinstance(elem, functions.OrFunction):
                    return self.do_fun_Or(elem, states)
                elif isinstance(elem, functions.AndFunction):
                    return self.do_fun_And(elem, states)
                elif isinstance(elem, functions.ShellFunction):
                    return self.do_fun_ShellFunction(elem, states)
                elif isinstance(elem, functions.ErrorFunction):
                    return self.do_fun_Error(elem, states)
                elif isinstance(elem, functions.WarningFunction):
                    return self.do_fun_Warning(elem, states)
                elif isinstance(elem, functions.InfoFunction):
                    return self.do_fun_Info(elem, states)
                elif isinstance(elem, functions.CallFunction):
                    return self.do_CallFunction(elem, states)
                elif isinstance(elem, functions.ForEachFunction):
                    return self.do_fun_Foreach(elem, states)
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
        if not fun._arguments:
            return []

        vname_exps = self.do_expansion(fun._arguments[0], states)
        call_args = [self.do_expansion(arg, states) for arg in fun._arguments[1:]]

        d = OrderedDict()
        for vname, vcond in vname_exps:
            if not self.solver.is_sat(vcond):
                continue

            if vname == 'as-instr' and len(fun._arguments) >= 4:
                return [('yes', zsolver.T), ('no', zsolver.T)]
            elif vname in ('cc-option', 'cc-disable-warning', 'ld-option') and len(fun._arguments) >= 2:
                arg1 = fun._arguments[1].to_source().strip()
                d[arg1] = vcond
                continue
            elif vname == 'toupper' and len(call_args) >= 1:
                for arg_val, arg_c in call_args[0]:
                    d[arg_val.upper()] = zsolver.conj(vcond, arg_c)
                continue
            elif vname == 'tolower' and len(call_args) >= 1:
                for arg_val, arg_c in call_args[0]:
                    d[arg_val.lower()] = zsolver.conj(vcond, arg_c)
                continue
            elif vname == 'strip_quotes' and len(call_args) >= 1:
                for arg_val, arg_c in call_args[0]:
                    d[arg_val.strip('\'"')] = zsolver.conj(vcond, arg_c)
                continue
            elif vname in ('int-add', 'int-subtract', 'int-multiply') and call_args:
                try:
                    num = 0
                    for i, arg_res in enumerate(call_args):
                        v_str = arg_res[0][0] if arg_res else '0'
                        val_int = int(v_str, 0)
                        if i == 0 or vname == 'int-add':
                            num += val_int
                        elif vname == 'int-subtract':
                            num -= val_int
                        elif vname == 'int-multiply':
                            num *= val_int
                    d[hex(num)] = vcond
                except (ValueError, TypeError):
                    d['0'] = vcond
                continue
            elif vname == 'bool-to-mask' and len(call_args) >= 2:
                for var_val, var_c in call_args[0]:
                    for mask_val, mask_c in call_args[1]:
                        c = zsolver.mconj([vcond, var_c, mask_c])
                        if self.solver.is_sat(c):
                            v = mask_val if var_val.strip() == 'y' else '0'
                            d[v] = c
                continue

            if vname in states:
                local_states = dict(states)
                from ds import VarG
                for i, arg_res in enumerate(call_args, start=1):
                    arg_valconds = {v: c for v, c in arg_res}
                    local_states[str(i)] = VarG(
                        str(i), arg_valconds, VarG.SIMPLY, self.solver.mysettings)

                var_obj = states[vname]
                for word, wcond in var_obj.valconds.items():
                    total_cond = zsolver.conj(vcond, wcond)
                    if self.solver.is_sat(total_cond):
                        res = self.do_fake_expansion(str(word), local_states)
                        for rv, rc in res:
                            rc_tot = zsolver.conj(total_cond, rc)
                            if self.solver.is_sat(rc_tot):
                                d[rv] = rc_tot
            else:
                mlog.debug(f"$(call {vname}) undefined")
                d[''] = vcond

        return list(d.items()) if d else [('', zsolver.T)]

    def do_fun_Foreach(self, fun, states):
        assert isinstance(fun, functions.ForEachFunction), fun
        var_name = fun._arguments[0].to_source().strip()
        list_exps = self.do_expansion(fun._arguments[1], states)
        text_arg = fun._arguments[2]
        d = OrderedDict()
        from ds import VarG
        for list_str, list_cond in list_exps:
            if not self.solver.is_sat(list_cond):
                continue
            words = list_str.split()
            accum = []
            for w in words:
                local_states = dict(states)
                local_states[var_name] = VarG(
                    var_name, {w: zsolver.T}, VarG.SIMPLY, self.solver.mysettings)
                w_res = self.do_expansion(text_arg, local_states)
                accum.append(w_res)
            if not accum:
                d[''] = list_cond
            else:
                combined_words = []
                for w_res in accum:
                    for w_val, w_c in w_res:
                        if self.solver.is_sat(w_c) and w_val.strip():
                            combined_words.append(w_val.strip())
                d[" ".join(combined_words)] = list_cond
        return list(d.items()) if d else [('', zsolver.T)]

    def do_fun_ShellFunction(self, fun, states):
        assert isinstance(fun, functions.ShellFunction), fun
        combines = self.get_fun_arg_vals(fun, 1, states)
        d = OrderedDict()
        dir_ = None
        if 'src' in states:
            src_val = list(states['src'].vals)[0]
            if hasattr(src_val, 'is_dir') and src_val.is_dir():
                dir_ = str(src_val)
        import subprocess
        for ((cmd, cond),) in combines:
            if not self.solver.is_sat(cond):
                continue
            try:
                res = subprocess.run(
                    cmd, shell=True, cwd=dir_, capture_output=True, text=True, timeout=5
                )
                out = res.stdout.replace('\r\n', '\n').replace('\n', ' ').strip()
                d[out] = cond
            except Exception as e:
                mlog.debug(f"shell command failed: {cmd}: {e}")
                d[''] = cond
        return list(d.items()) if d else [('', zsolver.T)]

    def do_fun_Filter(self, fun, states):
        assert isinstance(fun, functions.FilterFunction), fun
        import re
        combines = self.get_fun_arg_vals(fun, 2, states)
        d = OrderedDict()
        for (pv, pc), (tv, tc) in combines:
            cond = zsolver.mconj([pc, tc])
            if self.solver.is_sat(cond):
                patterns = pv.split()
                matched = []
                for word in tv.split():
                    for pat in patterns:
                        if '%' in pat:
                            regex = '^' + re.escape(pat).replace(r'\%', '.*') + '$'
                            if re.match(regex, word):
                                matched.append(word)
                                break
                        elif pat == word:
                            matched.append(word)
                            break
                v = " ".join(matched)
                if v not in d:
                    d[v] = cond
                else:
                    d[v] = zsolver.disj(d[v], cond)
        return list(d.items())

    def do_fun_Filterout(self, fun, states):
        assert isinstance(fun, functions.FilteroutFunction), fun
        import re
        combines = self.get_fun_arg_vals(fun, 2, states)
        d = OrderedDict()
        for (pv, pc), (tv, tc) in combines:
            cond = zsolver.mconj([pc, tc])
            if self.solver.is_sat(cond):
                patterns = pv.split()
                kept = []
                for word in tv.split():
                    matches = False
                    for pat in patterns:
                        if '%' in pat:
                            regex = '^' + re.escape(pat).replace(r'\%', '.*') + '$'
                            if re.match(regex, word):
                                matches = True
                                break
                        elif pat == word:
                            matches = True
                            break
                    if not matches:
                        kept.append(word)
                v = " ".join(kept)
                if v not in d:
                    d[v] = cond
                else:
                    d[v] = zsolver.disj(d[v], cond)
        return list(d.items())

    def do_fun_Strip(self, fun, states):
        assert isinstance(fun, functions.StripFunction), fun
        combines = self.get_fun_arg_vals(fun, 1, states)
        d = OrderedDict()
        for ((val, cond),) in combines:
            if self.solver.is_sat(cond):
                stripped = " ".join(val.split())
                d[stripped] = cond
        return list(d.items())

    def do_fun_Findstring(self, fun, states):
        assert isinstance(fun, functions.FindstringFunction), fun
        combines = self.get_fun_arg_vals(fun, 2, states)
        d = OrderedDict()
        for (find_v, fc), (in_v, ic) in combines:
            cond = zsolver.conj(fc, ic)
            if self.solver.is_sat(cond):
                v = find_v if find_v in in_v else ''
                d[v] = cond
        return list(d.items())

    def do_fun_Sort(self, fun, states):
        assert isinstance(fun, functions.SortFunction), fun
        combines = self.get_fun_arg_vals(fun, 1, states)
        d = OrderedDict()
        for ((val, cond),) in combines:
            if self.solver.is_sat(cond):
                sorted_v = " ".join(sorted(list(set(val.split()))))
                d[sorted_v] = cond
        return list(d.items())

    def do_fun_Firstword(self, fun, states):
        combines = self.get_fun_arg_vals(fun, 1, states)
        d = OrderedDict()
        for ((val, cond),) in combines:
            if self.solver.is_sat(cond):
                words = val.split()
                v = words[0] if words else ''
                d[v] = cond
        return list(d.items())

    def do_fun_Lastword(self, fun, states):
        combines = self.get_fun_arg_vals(fun, 1, states)
        d = OrderedDict()
        for ((val, cond),) in combines:
            if self.solver.is_sat(cond):
                words = val.split()
                v = words[-1] if words else ''
                d[v] = cond
        return list(d.items())

    def do_fun_Words(self, fun, states):
        combines = self.get_fun_arg_vals(fun, 1, states)
        d = OrderedDict()
        for ((val, cond),) in combines:
            if self.solver.is_sat(cond):
                v = str(len(val.split()))
                d[v] = cond
        return list(d.items())

    def do_fun_Word(self, fun, states):
        combines = self.get_fun_arg_vals(fun, 2, states)
        d = OrderedDict()
        for (nv, nc), (tv, tc) in combines:
            cond = zsolver.conj(nc, tc)
            if self.solver.is_sat(cond):
                try:
                    idx = int(nv.strip())
                    words = tv.split()
                    v = words[idx - 1] if 1 <= idx <= len(words) else ''
                except ValueError:
                    v = ''
                d[v] = cond
        return list(d.items())

    def do_fun_Wordlist(self, fun, states):
        combines = self.get_fun_arg_vals(fun, 3, states)
        d = OrderedDict()
        for (sv, sc), (ev, ec), (tv, tc) in combines:
            cond = zsolver.mconj([sc, ec, tc])
            if self.solver.is_sat(cond):
                try:
                    s_idx = int(sv.strip())
                    e_idx = int(ev.strip())
                    words = tv.split()
                    v = " ".join(words[max(0, s_idx - 1):e_idx])
                except ValueError:
                    v = ''
                d[v] = cond
        return list(d.items())

    def do_fun_Dir(self, fun, states):
        combines = self.get_fun_arg_vals(fun, 1, states)
        d = OrderedDict()
        for ((val, cond),) in combines:
            if self.solver.is_sat(cond):
                res = []
                for word in val.split():
                    slash = word.rfind('/')
                    res.append(word[:slash + 1] if slash >= 0 else './')
                d[" ".join(res)] = cond
        return list(d.items())

    def do_fun_NotDir(self, fun, states):
        combines = self.get_fun_arg_vals(fun, 1, states)
        d = OrderedDict()
        for ((val, cond),) in combines:
            if self.solver.is_sat(cond):
                res = []
                for word in val.split():
                    slash = word.rfind('/')
                    res.append(word[slash + 1:] if slash >= 0 else word)
                d[" ".join(res)] = cond
        return list(d.items())

    def do_fun_Suffix(self, fun, states):
        import os.path
        combines = self.get_fun_arg_vals(fun, 1, states)
        d = OrderedDict()
        for ((val, cond),) in combines:
            if self.solver.is_sat(cond):
                res = [os.path.splitext(w)[1] for w in val.split()]
                d[" ".join(w for w in res if w)] = cond
        return list(d.items())

    def do_fun_Basename(self, fun, states):
        import os.path
        combines = self.get_fun_arg_vals(fun, 1, states)
        d = OrderedDict()
        for ((val, cond),) in combines:
            if self.solver.is_sat(cond):
                res = [os.path.splitext(w)[0] for w in val.split()]
                d[" ".join(res)] = cond
        return list(d.items())

    def do_fun_AddSuffixFunction(self, fun, states):
        combines = self.get_fun_arg_vals(fun, 2, states)
        d = OrderedDict()
        for (sv, sc), (nv, nc) in combines:
            cond = zsolver.conj(sc, nc)
            if self.solver.is_sat(cond):
                d[" ".join(n + sv for n in nv.split())] = cond
        return list(d.items())

    def do_fun_If(self, fun, states):
        cond_exps = self.do_expansion(fun._arguments[0], states)
        then_arg = fun._arguments[1] if len(fun._arguments) > 1 else None
        else_arg = fun._arguments[2] if len(fun._arguments) > 2 else None
        d = OrderedDict()
        for c_val, c_cond in cond_exps:
            if not self.solver.is_sat(c_cond):
                continue
            if c_val.strip():
                if then_arg is not None:
                    for tv, tc in self.do_expansion(then_arg, states):
                        total_c = zsolver.conj(c_cond, tc)
                        if self.solver.is_sat(total_c):
                            d[tv] = total_c
                else:
                    d[''] = c_cond
            else:
                if else_arg is not None:
                    for ev, ec in self.do_expansion(else_arg, states):
                        total_c = zsolver.conj(c_cond, ec)
                        if self.solver.is_sat(total_c):
                            d[ev] = total_c
                else:
                    d[''] = c_cond
        return list(d.items())

    def do_fun_Or(self, fun, states):
        d = OrderedDict()
        for arg in fun._arguments:
            for val, cond in self.do_expansion(arg, states):
                if self.solver.is_sat(cond) and val.strip():
                    d[val] = cond
                    return list(d.items())
        return [('', zsolver.T)]

    def do_fun_And(self, fun, states):
        last_val = ''
        last_cond = zsolver.T
        for arg in fun._arguments:
            res = self.do_expansion(arg, states)
            found = False
            for val, cond in res:
                if self.solver.is_sat(cond) and val.strip():
                    found = True
                    last_val = val
                    last_cond = zsolver.conj(last_cond, cond)
                    break
            if not found:
                return [('', zsolver.T)]
        return [(last_val, last_cond)]

    def do_fun_Error(self, fun, states):
        exps = self.do_expansion(fun._arguments[0], states)
        for msg, cond in exps:
            mlog.info(f"$(error {msg}) encountered under guard {cond}")
        return []

    def do_fun_Warning(self, fun, states):
        exps = self.do_expansion(fun._arguments[0], states)
        for msg, cond in exps:
            mlog.debug(f"$(warning {msg})")
        return [('', zsolver.T)]

    def do_fun_Info(self, fun, states):
        exps = self.do_expansion(fun._arguments[0], states)
        for msg, cond in exps:
            mlog.debug(f"$(info {msg})")
        return [('', zsolver.T)]

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

        names = self.do_expansion(fun.vname, states)

        rs = []
        for name, _ in names:
            if name in states:
                v = states[name]
                if not v.valconds:
                    vals = [('', zsolver.T)]
                elif v.is_recurse:
                    # Recurse ("=") variables store their raw, unexpanded
                    # text as words; each word may have been assigned under
                    # a different condition, so re-expand each separately
                    # and keep its guard, rather than joining every word
                    # into one string (which would silently drop
                    # conditioning between multiple conditional
                    # assignments).
                    vals = [
                        (val2, zsolver.conj(wcond, vcond2))
                        for word, wcond in v.valconds.items()
                        for val2, vcond2 in self.do_fake_expansion(str(word), states)
                    ]
                else:
                    # Each word is an independent alternative, tagged with
                    # its own membership condition -- this is what lets a
                    # list-valued variable (e.g. obj-y) stay a single
                    # symbolic value instead of exploding into one path per
                    # concrete subset of members.
                    vals = list(v.valconds.items())

            elif (self.solver.mysettings.is_copt(name) or
                  self.solver.mysettings.is_xopt(name)):
                vals = self.do_config_var(name)

            else:
                mlog.debug("'{}' undefined in path".format(name))
                vals = [(self.solver.undef_str, zsolver.T)]
            rs.extend(vals)

        return rs, names

    def do_config_var(self, name):
        assert (self.solver.mysettings.is_copt(name) or
                self.solver.mysettings.is_xopt(name)), name

        symbol, optd = self.solver.get_sort(name)

        vals = [(k, symbol == optd[k]) for k in optd]
        return vals

    def get_fun_arg_vals(self, fun, nargs, states):
        assert nargs >= 1, nargs
        fargs = [fun._arguments[i] for i in range(nargs)]
        expansions = [self.do_expansion(farg, states) for farg in fargs]
        return itertools.product(*expansions)


class ExpansionSExe(ExpansionBase):
    @classmethod
    def combine_helper(cls, comb, ss, c, delim):
        comb.append((delim.join(ss), c))

    def do_fun_VariableRef(self, fun, states):
        rs, names = super().do_fun_VariableRef(fun, states)
        return rs


class ExpansionDExe(ExpansionBase):
    def __init__(self, solver):
        super().__init__(solver)
        self.deps = set()

    @classmethod
    def combine_helper(cls, comb, ss, c, delim):
        comb.append((delim.join(ss), c))

    def do_fun_VariableRef(self, fun, states):
        rs, names = super().do_fun_VariableRef(fun, states)
        for name, _ in names:
            self.deps.add(name)
        return rs
