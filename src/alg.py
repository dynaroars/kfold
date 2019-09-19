import tempfile
from time import time
import pathlib
import pdb

import z3

import settings
import helpers.vcommon as CM
import helpers.zsolver as zsolver
from kbuild import Kbuild

mlog = CM.getLogger(__name__, settings.logger_level)


DBG = pdb.set_trace


class Run:
    def __init__(self, main_dir):
        """
        paths is a list of paths to either makefiles or directories
        """
        self.main_dir = main_dir.resolve()
        self.mysettings = settings.Settings(
            self.main_dir / settings.settings_file)

    def go(self):
        st = time()
        self.tmpdir = pathlib.Path(tempfile.mkdtemp(
            dir=settings.tmpdir, prefix="skbuild"))

        default_cond = None

        if self.mysettings.top_dirs:
            top_dirs = [self.main_dir / d for d in self.mysettings.top_dirs]
            top_dirs = [d for d in top_dirs if d.is_dir()]
        else:
            top_dirs = [self.main_dir]

        makefiles = [(makefile, default_cond) for makefile in
                     self.get_makefiles(top_dirs)]

        results = set()  # (makefile, cond)
        mycache = {}  # makefile -> kbuild
        while makefiles:
            kbuilds = []
            for makefile, cond in makefiles:
                kbuild = mycache.setdefault(
                    makefile, self.analyze(makefile))

                if cond is not default_cond:
                    kbuild = kbuild.fork(cond)

                kbuilds.append(kbuild)
                results.add(kbuild)

            makefiles = self.get_makefiles_from_kbuilds(kbuilds)

        mlog.info("obtain {} kbuilds in {:.2f}s".format(
            len(results), time() - st))
        self.save(results)
        return self.tmpdir

    def analyze(self, makefile):
        assert makefile.is_file(), makefile
        kbuild = Kbuild(makefile, self.mysettings)
        kbuild.symexe()
        return kbuild

    def save(self, kbuilds):
        assert isinstance(kbuilds, set) and kbuilds, kbuilds

        result_dir = self.tmpdir
        assert result_dir.is_dir()

        sinfo = (self.main_dir, self.mysettings)
        CM.vsave(result_dir / settings.RESULT_SINFO, sinfo)
        for i, kbuild in enumerate(kbuilds):
            kbuild.save(result_dir / "kbuild_{}".format(i))

    @staticmethod
    def load(result_dir):
        assert result_dir.is_dir(), result_dir

        main_dir, mysettings = CM.vload(result_dir / settings.RESULT_SINFO)
        kbuilds = [Kbuild.load(result_dir/f, mysettings)
                   for f in result_dir.iterdir()
                   if f.name != settings.RESULT_SINFO]

        return (main_dir, mysettings, kbuilds)

    @classmethod
    def get_makefiles(cls, paths):
        assert all(isinstance(p, pathlib.Path) for p in paths), paths

        makefiles = [cls.get_makefile(p) for p in paths]
        return [makefile for makefile in makefiles if makefile]

    @classmethod
    def get_makefiles_from_kbuilds(cls, kbuilds):
        makefiles = [(path.subdirs(kb.topdir), path.cond)
                     for kb in kbuilds for path in kb.paths]
        makefiles = [(subdirs, cond)
                     for subdirs, cond in makefiles if subdirs]
        makefiles = [(makefile, cond)
                     for subdirs, cond in makefiles
                     for makefile in cls.get_makefiles(subdirs)]

        cache = {}
        for makefile, cond in makefiles:
            cache.setdefault(makefile, []).append(cond)
        makefiles = [(makefile, zsolver.simplify(z3.Or(cache[makefile])))
                     for makefile in cache]
        return makefiles

    @classmethod
    def get_makefile(cls, path):
        """
        use Kbuild file if found, otherwise try Makefile
        """
        assert isinstance(path, pathlib.Path), path

        if not path.exists():
            mlog.warn("{} does not exist".format(path))
            return None

        makefile = path
        if path.is_dir():
            makefile = path / "Kbuild"
            if not makefile.is_file():
                makefile = path / "Makefile"

        if not makefile.is_file():
            mlog.warn("{} has no makefile".format(path))
            return None

        return makefile.resolve()
