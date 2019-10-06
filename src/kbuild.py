import pathlib
import pdb
import z3

from pymake3 import parser

import helpers.vcommon as CM
import helpers.zsolver as zsolver

from ds import Path, Paths
import symexe as SE

import settings
mlog = CM.getLogger(__name__, settings.logger_level)

DBG = pdb.set_trace


class Kbuild:
    def __init__(self, makefile, mysettings):
        assert makefile.is_file(), makefile
        assert isinstance(mysettings, settings.Settings), mysettings

        self.makefile = makefile
        self.mysettings = mysettings
        self.solver = zsolver.ZSolver(self.mysettings)
        self.stmts = parser.parsestring(
            self.makefile.read_text(), self.makefile)

    def symexe(self):
        stmts = SE.StatementList(self.stmts, self.solver, self.mysettings)

        dpath = Path.get_default(self.makefile.parent, self.mysettings)
        stmts.spy_i(dpath, frozenset())
        print(dpath.deps)
        DBG()
        spath = Path.get_default(self.makefile.parent, self.mysettings)
        self.paths = stmts.symexe(Paths([spath]))

    def fork(self, new_cond):
        assert z3.is_expr(new_cond), new_cond

        kbuild = self.__class__(self.makefile, self.mysettings)

        paths = []
        for path in self.paths:
            cond = zsolver.conj(path.cond, new_cond)
            if self.solver.is_sat(cond):
                cond = zsolver.simplify(cond)
                new_path = path.fork(cond)
                paths.append(new_path)
        kbuild.paths = Paths(paths)
        return kbuild

    def save(self, tofile):
        """
        save info to file / load info from file
        note things are a bit complex because
        Z3 data structures cannot be saved directly to file
        """
        assert isinstance(tofile, pathlib.Path) and tofile, tofile

        kinfo = (self.makefile,
                 [(zsolver.to_smt2_str(p.cond), p.states) for p in self.paths],
                 list(self.solver.__config_vars__.keys()))

        assert not tofile.exists(), tofile
        CM.vsave(tofile, kinfo)

    @staticmethod
    def load(fromfile, mysettings):
        assert fromfile.is_file(), fromfile
        assert isinstance(mysettings, settings.Settings), mysettings

        kinfo = CM.vload(fromfile)
        makefile, paths_info, config_names = kinfo

        paths = Paths([
            Path(zsolver.from_smt2_str(cond), states, mysettings)
            for cond, states in paths_info
        ])
        kbuild = Kbuild(makefile, mysettings)
        kbuild.solver.reconstruct(config_names)
        kbuild.paths = paths
        return kbuild
