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

BaseVar = namedtuple("BaseVar", "name vals flavor mysettings")


class Var(BaseVar):
    RECURSE = "RECURSE"   # =, define
    SIMPLY = "SIMPLY"  # := , ::=

    def __init__(self, name, vals, flavor, mysettings):
        assert isinstance(name, str) and name, name
        assert isinstance(vals, frozenset), vals
        assert flavor in set([self.RECURSE, self.SIMPLY]), flavor
        assert isinstance(mysettings, settings.Settings), mysettings

        super().__init__()

    @property
    def vals_str(self):
        return ' '.join(sorted(map(str, self.vals)))

    @property
    def is_recurse(self):
        return self.flavor == self.RECURSE

    def issubset(self, name, values):
        assert isinstance(values, frozenset), values
        return self.name == name and values.issubset(self.values)

    def fork_vals(self, vals):
        assert isinstance(vals, frozenset), vals
        return self.__class__(self.name, vals, self.flavor, self.mysettings)

    def __str__(self):
        token = "=" if self.flavor == self.RECURSE else ":="
        return "{} {} {}".format(
            self.name, token, ' '.join(sorted(self.vals)))

    @property
    def ignorable(self):
        return self.name in self.mysettings.ignore_vars

    @property
    def is_undef_target(self):  # obj-, lib-
        return self.name in self.mysettings.target_vars

    @property
    def subdir_names(self):
        assert not self.ignorable
        return [d for d in self.vals if d.endswith('/')]

    def subdirs(self, topdir):
        assert topdir.is_dir(), topdir
        assert not self.ignorable

        subdirs = [topdir / d for d in self.subdir_names]

        return subdirs

    @classmethod
    def get_flavor(cls, token):
        if token in set([":=", "::="]) or token in set(["+="]):
            flavor = cls.SIMPLY
        else:
            assert token == "=", token
            flavor = cls.RECURSE

        return flavor

    @classmethod
    def src_var(cls, topdir, mysettings):
        assert topdir.is_dir(), topdir
        assert isinstance(mysettings, settings.Settings), mysettings

        return cls("src", frozenset([topdir]), cls.RECURSE, mysettings)


class BasePath:
    __ct__ = 0

    def __init__(self, cond, states, mysettings):
        assert z3.is_expr(cond), cond
        assert isinstance(states, dict), states
        assert isinstance(mysettings, settings.Settings), mysettings

        self.cond = cond
        self.states = states
        self.mysettings = mysettings

        self.__ct__ += 1

    def __del__(self):
        self.__ct__ -= 1

    def __str__(self):

        ss = (v for v in self.states.values() if not v.ignorable)
        ss = '; '.join(map(str, ss))
        if ss:
            ss = "{} => {}".format(self.cond, ss)
        return ss

    def fork(self, new_cond, ignore_targets=False):
        """
        Create a new path with newcond
        """
        assert z3.is_expr(new_cond), new_cond

        new_states = OrderedDict()
        for name, v in self.states.items():
            if ignore_targets and self.is_target(name):
                continue
            new_states[name] = v
        return self.__class__(new_cond, new_states, self.mysettings)

    def set_var(self, name, token, val):
        assert isinstance(name, str), name
        assert isinstance(token, str) and token, token
        assert isinstance(val, str), val

        vals = frozenset(val.split())

        if name not in self.states or token in set(["=", ":="]):
            new_var = Var(name, vals,
                          Var.get_flavor(token), self.mysettings)
        else:
            assert token == "+=", token
            v = self.states[name]
            new_var = v.fork_vals(v.vals | vals)

        self.states[name] = new_var

    def is_target(self, t):
        return any(t.startswith(x) for x in self.mysettings.target_vars)

    @classmethod
    def get_default(cls, src_dir, mysettings):
        assert isinstance(src_dir, Var) or src_dir.is_dir(), src_dir
        assert isinstance(mysettings, settings.Settings), mysettings

        states = {'src': src_dir if isinstance(
            src_dir, Var) else Var.src_var(src_dir, mysettings)}
        return cls(zsolver.T, states, mysettings)


class SPath(BasePath):

    def __init__(self, cond, states, mysettings):
        super().__init__(cond, states, mysettings)

    def subdirs(self, topdir):
        subdirs_ = [self.states[v].subdirs(topdir)
                    for v in self.states
                    if not (self.states[v].ignorable
                            or self.states[v].is_undef_target)]
        return frozenset(itertools.chain(*subdirs_))

    def split(self):
        assert self.states

        new_paths = []
        for name in self.states:
            if self.is_not_target(name):  # don't split
                continue

            myvar = self.states[name]
            if not myvar.vals:
                new_path = self.fork(self.cond, ignore_targets=True)
                new_path.states[name] = myvar
                new_paths.append(new_path)
            else:
                for v in myvar.vals:
                    new_path = self.fork(self.cond, ignore_targets=True)
                    new_path.states[name] = myvar.fork_vals(frozenset([v]))
                    new_paths.append(new_path)

        if not new_paths:
            new_paths.append(self)  # keep path as is
        return new_paths

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
                if self.is_target(name)]

    @property
    def vals_d(self):
        return {self.states[name].name: self.states[name].vals
                for name in self.states}

    def is_not_target(self, t):
        return not self.is_target(t)


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
        paths = [SPath(zsolver.from_smt_str(smt_str), states)
                 for smt_str, states in paths_info]
        return Paths(paths)


class DPath(BasePath):
    def __init__(self, cond, states, mysettings):
        super().__init__(cond, states, mysettings)
        self.deps = {}

    def merge(self, path):
        assert isinstance(path, self.__class__), path

        for name in path.states:
            path_var = path.states[name]
            assert isinstance(path_var, Var), path_var
            if name in self.states:
                vals = self.states[name].vals | path_var.vals
                self.states[name] = self.states[name].fork_vals(vals)
            else:
                self.states[name] = path_var

        self.deps.update(path.deps)

    @property
    def dgraph(self):
        try:
            return self._dgraph
        except AttributeError:
            _dgraph = {}
            for name in self.deps:
                _dgraph.setdefault(name, set()).update(self.deps[name])

            for name in self.states:
                myvar = self.states[name]
                _dgraph.setdefault(name, set()).update(myvar.vals)

            for name in _dgraph:
                if name in _dgraph[name]:
                    _dgraph[name].remove(name)

            self._dgraph = _dgraph
            return self._dgraph

    @property
    def target_deps(self):
        try:
            return self._target_deps
        except AttributeError:
            target_names = [
                name for name in self.dgraph if self.is_target(name)]
            d = {}
            for name in target_names:
                deps = set()
                self.find_deps(name, deps)
                d[name] = deps
            self._target_deps = d

            return self._target_deps

    @property
    def used_vars(self):
        try:
            return self._used_vars
        except AttributeError:
            _used_vars = [self.target_deps[name]
                          for name in self.target_deps]
            _used_vars.append(list(self.target_deps.keys()))

            # also consider name if name is assigned to a subdir, e.g.,
            # libs-y := subdir/
            _used_vars.append(
                name for name in self.dgraph
                if any(isinstance(d, str) and d.endswith('/')
                       for d in self.dgraph[name]))

            self._used_vars = frozenset(itertools.chain(*_used_vars))
            return self._used_vars

    def find_deps(self, name, deps):
        assert name in self.dgraph, name

        dep_names = set()
        for dname in self.dgraph[name]:
            if dname in deps:
                mlog.warn('Potential dep cycle: {}'.format(dname))
            else:
                dep_names.add(dname)

        deps.update(dep_names)
        for dname in dep_names:
            if dname not in self.dgraph:
                continue
            self.find_deps(dname, deps)
