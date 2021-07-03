import itertools
from time import time
import pathlib
import pdb

from pymake3 import parser, parserdata, data

import helpers.vcommon as CM
import helpers.zsolver as zsolver

import expansion
from ds import Path, Paths, DepPath
import bexe

import settings
mlog = CM.getLogger(__name__, settings.logger_level)

DBG = pdb.set_trace


class Exe(bexe.Exe):

    def exe(self, path, deps):
        assert isinstance(path, DepPath), path
        assert isinstance(deps, frozenset), deps
        try:
            self.exe_i(path, deps)
        except NotImplementedError as ex:
            mlog.warn(ex)

    def exe_i(self, spath, deps):
        pass


class StatementList(bexe.StatementList, Exe):
    def exe_i(self, path, deps):
        stmts = self.stmt
        for cls, stmt in self.get_clss(stmts):
            cls(stmt, self.solver, self.mysettings).spy(path, deps)
