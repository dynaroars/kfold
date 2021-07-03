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
    def exe(self, paths):
        st = time()
        new_paths = Paths()
        for i, path in enumerate(paths):
            try:
                new_paths_ = self.exe_i(path)
            except NotImplementedError as ex:
                mlog.warn(ex)
                new_paths_ = Paths([path])

            new_paths.extend(new_paths_)

        if isinstance(self, StatementList):
            return new_paths

        et_mk = time() - st

        if settings.detail:
            print('--- ORIG --- ({} paths)'.format(len(paths)))
            print(paths)
            print('--- NEW --- ({} paths)'.format(len(new_paths)))
            print(new_paths)

        st_split = time()
        split_paths = new_paths.split()
        et_split = time() - st_split

        if settings.detail:
            print('--- SPLIT --- ({} paths)'.format(len(split_paths)))
            print(split_paths)

        st_merge = time()
        merge_paths = split_paths.merge()
        et_merge = time() - st_merge

        if settings.detail:
            print("--- MERGE --- ({} paths):\n{}".format(
                len(merge_paths), merge_paths))

        mlog.debug("paths: orig {}, new {} ({:2f}), "
                   "split {} ({:02f}), "
                   "merge {} ({:02f}), "
                   "mem {}, configs {}, time {:02f}".format(
                       len(paths),
                       len(new_paths), et_mk,
                       len(split_paths), et_split,
                       len(merge_paths), et_merge,
                       Path.__ct__, len(zsolver.ZSolver.__config_vars__),
                       time() - st))

        return merge_paths

    def symexe_i(self, path):
        return Paths([path])

    def get_new_path(self, path, cond):
        newcond = zsolver.conj(path.cond, cond)
        if self.solver.is_sat(newcond):
            return path.fork(newcond)
        else:
            return None
