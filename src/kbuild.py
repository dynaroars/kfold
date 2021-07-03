import pathlib
import pdb
import z3

from pymake3 import parser

import helpers.vcommon as CM
import helpers.zsolver as zsolver

from ds import SPath, DPath, Paths
import symexe as SE

import settings
mlog = CM.getLogger(__name__, settings.logger_level)

DBG = pdb.set_trace

class Kbuild:
    default_cond = None

    def __init__(self, makefile, mysettings, precond_hash):
        assert makefile.is_file(), makefile
        assert isinstance(mysettings, settings.Settings), mysettings

        self.precond_hash = precond_hash
        self.makefile = makefile
        self.mysettings = mysettings
        self.solver = zsolver.ZSolver(self.mysettings)

    def preprocess(self):
        stmts = parser.parsestring(
            self.makefile.read_text(), self.makefile)
        mystmts = SE.StatementList.create(stmts, tuple(), self.solver)
        siz = mystmts.siz
        mlog.debug("Preprocessing {} stmts".format(siz))
        dpath = DPath.get_default(self.makefile.parent, self.mysettings)
        mystmts.dexe(dpath, frozenset())

        ddb = dpath.ddb
        ddb.compute_used_vars(self.mysettings.target_vars)
        mystmts = mystmts.myreduce(ddb)
        newsiz = mystmts.siz if mystmts else 0
        nremoved = siz - newsiz
        mlog.debug("After preprocessing {} stmts remain {}".format(
            newsiz, "({} removed)".format(nremoved) if nremoved else ''))

        if mystmts:
            mystmts.set_preds(pred=None)
            # preds = {}
            # mystmts.set_all_preds(preds)
            # ddb.set_preds(preds)

        self.stmts = mystmts
        self.ddb = ddb

    def symexe(self):
        mlog.debug("Symexe ({} used vars) ...".format(
            len(self.ddb.used_vars)))
        spath = SPath.get_default(self.makefile.parent, self.mysettings)
        paths = Paths([spath])
        if self.stmts:
            self.paths = self.stmts.sexe(paths, self.ddb)
        else:
            self.paths = paths

    def fork(self, new_cond):
        assert z3.is_expr(new_cond), new_cond

        kbuild = self.__class__(self.makefile, self.mysettings, hash(new_cond))

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
        assert (isinstance(tofile, pathlib.Path)
                and not tofile.exists() and tofile), tofile
        kinfo = (self.makefile, self.precond_hash,
                 [(zsolver.to_smt2_str(p.cond), p.states) for p in self.paths],
                 list(self.solver.__config_vars__.keys()))

        CM.vsave(tofile, kinfo)

    @staticmethod
    def load(fromfile, mysettings):
        assert fromfile.is_file(), fromfile
        assert isinstance(mysettings, settings.Settings), mysettings

        kinfo = CM.vload(fromfile)
        makefile, precond_hash, paths_info, config_names = kinfo

        paths = Paths([
            SPath(zsolver.from_smt2_str(cond), states, mysettings)
            for cond, states in paths_info
        ])
        kbuild = Kbuild(makefile, mysettings, precond_hash)
        kbuild.solver.reconstruct(config_names)
        kbuild.paths = paths
        return kbuild
