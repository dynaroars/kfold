import itertools
from time import time
import pathlib
import pdb

from pymake3 import parser, parserdata, data

import helpers.vcommon as CM
import helpers.zsolver as zsolver

import expansion
from ds import Path, Paths, DepPath

import settings
mlog = CM.getLogger(__name__, settings.logger_level)

DBG = pdb.set_trace


class Exe:
    def __init__(self, stmt, solver, mysettings):
        assert isinstance(solver, zsolver.ZSolver), solver
        assert isinstance(mysettings, settings.Settings), mysettings

        self.stmt = stmt
        self.solver = solver
        self.mysettings = mysettings


class StatementList(Exe):
    def __init__(self, stmt, solver, mysettings):
        assert isinstance(stmt, parserdata.StatementList), stmt
        super().__init__(stmt, solver, mysettings)

    def get_cls(self, stmt):
        DBG()
        if isinstance(stmt, parserdata.SetVariable):
            cls = mymodule.SetVariable

        elif isinstance(stmt, parserdata.ConditionBlock):
            cls = mymodule.ConditionBlock

        elif isinstance(
                stmt, (parserdata.Rule, parserdata.StaticPatternRule)):
            cls = mymodule.Rule

        elif isinstance(stmt, parserdata.Include):
            cls = mymodule.Include

        elif isinstance(stmt, parserdata.Command):
            cls = mymodule.Command

        elif isinstance(stmt, parserdata.EmptyDirective):
            cls = mymodule.EmptyDirective

        else:
            raise NotImplementedError("cannot parse {}".format(stmt))

        return cls

    @classmethod
    def get_clss(cls, stmts):
        DBG()
        clss = []
        for i, stmt in enumerate(stmts):
            mlog.debug("{}/{}. hit {} smt '{}'".format(
                i + 1, len(stmts),  stmt.__class__.__name__,
                stmt.to_source().strip()))
            clss.append((cls.get_cls(stmt), stmt))
        return clss
