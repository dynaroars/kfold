import pathlib
import pdb
import z3

from pymake3 import parser, parserdata

import helpers.vcommon as CM
import helpers.zsolver as zsolver

from ds import SState, DState
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

    def preprocess(self):
        stmts = parser.parsestring(
            self.makefile.read_text(), self.makefile)
        mystmts = SE.StatementList.create(stmts, sid=tuple())
        siz = mystmts.siz
        mlog.debug("Preprocessing {} stmts".format(siz))
        mystmts.set_solver(self.solver)
        dstate = DState.get_default(self.makefile.parent, self.mysettings)
        mystmts.dexe(dstate, frozenset())
        dstate.compute_used_vars()
        reduced = mystmts.myreduce(dstate.ddb)
        if reduced is None:
            # The whole file turned out irrelevant to any target var (e.g.
            # a Makefile that only sets variables no obj-/lib- var of ours
            # depends on): keep an empty, harmless statement list rather
            # than crashing.
            mystmts = SE.StatementList.create(parserdata.StatementList(), sid=tuple())
            mystmts.set_solver(self.solver)
        else:
            mystmts = reduced
        nremoved = siz - mystmts.siz
        mlog.debug("After processing {} remain {}".format(
            mystmts.siz, "({} removed)".format(nremoved) if nremoved else ''))
        mystmts.set_preds(pred=None)

        self.stmts = mystmts
        self.dstate = dstate

    def symexe(self):
        mlog.debug("Symexe ({} used vars) ...".format(
            len(self.dstate.ddb.used_vars)))
        state = SState.get_default(self.makefile.parent, self.mysettings)
        self.stmts.sexe(state, zsolver.T, self.dstate.ddb)
        self.state = state

    def fork(self, new_cond):
        """Return a new Kbuild sharing this one's (already computed) state,
        restricted to an additional external condition -- e.g. this
        Makefile's directory was reached under some parent guard. Replaces
        the old per-Path ``fork``, which forked every remaining ``Path``."""
        assert z3.is_expr(new_cond), new_cond

        kbuild = self.__class__(self.makefile, self.mysettings)
        kbuild.state = self.state.restrict(new_cond, self.solver)
        return kbuild

    def save(self, tofile):
        """
        save info to file / load info from file
        note things are a bit complex because
        Z3 data structures cannot be saved directly to file
        """
        assert (isinstance(tofile, pathlib.Path)
                and not tofile.exists() and tofile), tofile
        kinfo = (self.makefile,
                 self.state.to_savable(),
                 list(self.solver.__config_vars__.keys()))

        CM.vsave(tofile, kinfo)

    @staticmethod
    def load(fromfile, mysettings):
        assert fromfile.is_file(), fromfile
        assert isinstance(mysettings, settings.Settings), mysettings

        kinfo = CM.vload(fromfile)
        makefile, state_info, config_names = kinfo

        kbuild = Kbuild(makefile, mysettings)
        state = SState.from_savable(state_info, mysettings)
        kbuild.solver.reconstruct(config_names)
        kbuild.state = state
        return kbuild
