from collections import namedtuple, OrderedDict
import itertools
import pdb
import z3

import settings
import helpers.vcommon as CM
from helpers.miscs import Miscs
import helpers.zsolver as zsolver

mlog = CM.getLogger(__name__, settings.logger_level)

DBG = pdb.set_trace

BaseVar = namedtuple("BaseVar", "name vals flavor")


class Var(BaseVar):
    RECURSE = "RECURSE"   # =, define
    SIMPLY = "SIMPLY"  # := , ::=

    def __init__(self, name, vals, flavor):
        assert isinstance(name, str) and name, name
        assert isinstance(vals, frozenset), vals
        assert flavor in set([Var.RECURSE, Var.SIMPLY]), flavor

        super().__init__()

    @property
    def vals_str(self):
        return ' '.join(sorted(self.vals))

    @property
    def is_recurse(self):
        return self.flavor == self.RECURSE

    def issubset(self, name, values):
        assert isinstance(values, frozenset), values
        return self.name == name and values.issubset(self.values)

    def fork(self):
        return Var(self.name, self.vals, self.flavor)

    def fork_val(self, vals):
        assert isinstance(vals, frozenset) and vals, vals
        return Var(self.name, vals, self.flavor)

    def __str__(self):
        token = "=" if self.flavor == Var.RECURSE else ":="
        return "{} {} {}".format(
            self.name, token, ' '.join(sorted(self.vals)))

    @property
    def ignorable(self):
        return self.name in settings.ignore_vars

    def subdirs(self, topdir):
        assert topdir.is_dir(), topdir
        assert not self.ignorable
        subdirs = [topdir / d for d in self.vals if d.endswith("/")]
        return subdirs

    @staticmethod
    def get_flavor(token):
        if token in set([":=", "::="]) or token in set(["+="]):
            flavor = Var.SIMPLY
        else:
            assert token == "=", token
            flavor = Var.RECURSE

        return flavor

    @staticmethod
    def src_var(topdir):
        assert topdir.is_dir(), topdir
        return Var("src", frozenset([topdir]), Var.RECURSE)


class Path:
    __ct__ = 0

    def __init__(self, cond, states):
        assert z3.is_expr(cond), cond
        assert isinstance(states, dict), states

        self.cond = cond
        self.states = states
        Path.__ct__ += 1

    def __del__(self):
        Path.__ct__ -= 1

    def __str__(self):

        ss = (v for v in self.states.values() if not v.ignorable)
        ss = '; '.join(map(str, ss))
        if ss:
            ss = "{} => {}".format(self.cond, ss)
        return ss

    def subdirs(self, topdir):
        subdirs_ = [self.states[v].subdirs(topdir)
                    for v in self.states
                    if not self.states[v].ignorable]
        return frozenset(itertools.chain(*subdirs_))

    def fork(self, new_cond, ignore_targets=False):
        """
        Create a new path with newcond
        """
        assert z3.is_expr(new_cond), new_cond

        new_states = OrderedDict()
        for name, v in self.states.items():
            if ignore_targets and Path.is_target(name):
                continue
            new_states[name] = v.fork()
        return Path(new_cond, new_states)

    def set_var(self, name, token, val):
        assert isinstance(name, str), name
        assert isinstance(token, str) and token, token
        assert isinstance(val, str), val

        vals = val.split()
        if name not in self.states or token in set(["=", ":="]):
            v = Var(name, frozenset(vals), Var.get_flavor(token))
            self.states[name] = v
        else:
            myvar = self.states[name]
            if token == "+=":
                new_vals = frozenset(list(myvar.vals) + vals)
                self.states[name] = myvar.fork_val(new_vals)
            else:
                raise NotImplementedError

    def split(self):
        assert self.states

        new_paths = []
        for name in self.states:
            if Path.is_not_target(name):  # don't split
                continue

            myvar = self.states[name]
            if not myvar.vals:
                new_path = self.fork(self.cond, ignore_targets=True)
                new_path.states[name] = myvar.fork()
                new_paths.append(new_path)
            else:
                for v in myvar.vals:
                    new_path = self.fork(
                        self.cond, ignore_targets=True)
                    new_path.states[name] = myvar.fork_val(frozenset([v]))
                    new_paths.append(new_path)

        if not new_paths:
            new_paths.append(self)  # keep path as is
        return new_paths

    def merge_states(self, other):
        for name in other.states:
            other_var = other.states[name]
            assert isinstance(other_var, Var), other_var
            if name in self.states:
                vals = frozenset(
                    list(self.states[name].vals) + list(other_var.vals))
                self.states[name] = self.states[name].fork_val(vals)
            else:
                self.states[name] = other_var

    @property
    def state_vals(self):
        vals = []
        for symbol in self.states:
            vals.extend(self.states[symbol].vals)
        return frozenset(vals)

    @property
    def state_hash(self):
        fs = frozenset(sorted(self.states.items()))
        return hash(fs)

    @property
    def target_files(self):
        return [self.states[name] for name in self.states
                if Path.is_target(name)]

    @staticmethod
    def is_target(t):
        return any(t.startswith(x) for x in settings.target_vars)

    @staticmethod
    def is_not_target(t):
        return not Path.is_target(t)

    @classmethod
    def get_default(cls, cond, src_dir):
        assert z3.is_expr(cond), cond
        assert isinstance(src_dir, Var) or src_dir.is_dir(), src_dir

        states = {'src': src_dir if isinstance(
            src_dir, Var) else Var.src_var(src_dir)}
        return cls(cond, states)


class Paths(list):
    def __str__(self):
        paths = [str(path) for path in self]
        paths = [path for path in paths if path]
        ss = ["{}. {}".format(i+1, path)
              for i, path in enumerate(sorted(paths))]

        n_paths = len(self)
        diff = n_paths - len(paths)
        if diff:
            ss.append("Paths: shown {}, hidden {}, total {}".format(
                len(paths), diff, n_paths))
        return '\n'.join(ss)

    def split(self):
        assert self, self

        new_paths = Paths()
        for path in self:
            new_paths_ = path.split()
            new_paths.extend(new_paths_)

        assert new_paths
        return new_paths

    def merge(self):
        assert self, self

        groups = {}
        for path in self:
            groups.setdefault(path.state_hash, []).append(path)

        if len(groups) == len(self):
            return self

        simplified_paths = []
        other_paths = []
        for gpaths in groups.values():
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

            def _f(tasks):
                rs = [(i, _simplify(i)) for i in tasks]
                return rs

            wrs = Miscs.run_mp('merge', list(
                range(len(other_paths))), _f, do_mp=settings.do_mp)
            for i, cond_str in wrs:
                cond = zsolver.from_smt2_str(cond_str)
                if other_paths[i].cond not in zsolver.__simplify_cache__:
                    zsolver.__simplify_cache__[
                        other_paths[i].cond] = cond

                other_paths[i].cond = cond

        merge_paths = Paths(simplified_paths + other_paths)
        return merge_paths

    @staticmethod
    def save_info(paths):
        """
        savable info
        """
        assert isinstance(paths, Paths), paths
        paths_info = [(zsolver.to_smt_str(path.cond), path.states)
                      for path in paths]
        return paths_info

    @staticmethod
    def load_info(f):
        assert f.is_file(), f

        paths_info = CM.vload(f)
        paths = [Path(zsolver.from_smt_str(smt_str), states)
                 for smt_str, states in paths_info]
        return Paths(paths)
