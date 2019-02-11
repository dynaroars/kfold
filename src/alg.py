#! /usr/bin/env python

from collections import OrderedDict
import itertools
from time import time
from datetime import datetime
import os.path
import pdb

import z3

import vcommon as CM
import zsolver
from kbuild import Kbuild

import settings
mlog = CM.getLogger(__name__, settings.logger_level)

trace = pdb.set_trace
pause = CM.pause


class Run:
    def __init__(self, makefile_paths):
        """makefile_paths is a list of makefile path (either a real makefile
        or directory)

        """
        self.makefile_paths = makefile_paths

    def go(self):

        def get_makefiles(file_paths, cond):
            makefiles = [self.get_makefile(p) for p in file_paths]
            return [(makefile, cond) for makefile in makefiles if makefile]

        def analyze(makefile, cond):
            assert os.path.isfile(makefile), makefile
            assert cond is None or z3.is_expr(cond), cond
            kbuild = Kbuild(makefile)
            kbuild.symexe(cond)
            return kbuild

        st = time()
        kbuilds = []  # results
        makefiles = get_makefiles(self.makefile_paths, cond=zsolver.T)
        while makefiles:

            # parallel
            kbuilds_ = [analyze(makefile, cond)
                        for makefile, cond in makefiles]
            kbuilds.extend(kbuilds_)

            # recurse to subdirs if any
            makefiles = []
            for kbuild in kbuilds_:
                for path in kbuild.paths:
                    makefiles_ = get_makefiles(
                        path.subdirs(kbuild.topdir), path.cond)
                    makefiles.extend(makefiles_)

        mlog.info("analyzed {} kbuild makefiles in {}s".format(
            len(kbuilds), time() - st))

        import tempfile
        self.tmpdir = tempfile.mkdtemp(dir=settings.tmpdir, prefix="Symmake_")
        self.save(os.path.join(self.tmpdir, "results"), kbuilds)
        return self.tmpdir

    def postprocessing(self):
        pass

    @classmethod
    def get_makefile(cls, makefile_path):
        # use Kbuild file if found, otherwise try Makefile
        if not os.path.exists(makefile_path):
            mlog.warn("{} does not exist".format(makefile_path))
            return None

        makefile = makefile_path
        if os.path.isdir(makefile_path):
            makefile = os.path.join(makefile_path, "Kbuild")
            if not os.path.isfile(makefile):
                makefile = os.path.join(makefile_path, "Makefile")

        if not os.path.isfile(makefile):
            mlog.warn("{} has no makefile".format(makefile_path))
            return None

        return os.path.abspath(makefile)

    @staticmethod
    def save(f, kbuilds):
        assert all(isinstance(kbuild, Kbuild)
                   for kbuild in kbuilds) and kbuilds, kbuilds
        sinfo = []
        for kbuild in kbuilds:
            kinfo = (
                kbuild.makefile,
                kbuild.topdir,
                kbuild.se_time,
                [(zsolver.to_smt2_str(path.cond), path.states)
                 for path in kbuild.paths]
            )
            sinfo.append(kinfo)

        CM.vsave(f, sinfo)

    @staticmethod
    def load(f):
        assert os.path.isfile(f), f
        return CM.vload(f)
