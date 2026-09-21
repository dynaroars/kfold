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
    default_cond = None

    def __init__(self, path):
        """
        paths is a list of paths to either makefiles or directories
        """
        self.path = path.resolve()
        self.maindir = self.path.parent if self.path.is_file() else self.path
        self.mysettings = settings.Settings(self.maindir)

        if self.path.is_file():  # explicit Makefile input
            makefiles = [(self.path, self.default_cond)]
        else:
            if self.mysettings.topdirs:
                topdirs = [self.maindir /
                           d for d in sorted(self.mysettings.topdirs)]
                topdirs = [d for d in topdirs if d.is_dir()]
            else:
                topdirs = [self.maindir]

            makefiles = [(makefile, self.default_cond) for makefile in
                         self.get_makefiles(topdirs)]

        assert makefiles
        self.makefiles = makefiles

    def go(self):
        st = time()
        self.tmpdir = pathlib.Path(tempfile.mkdtemp(
            dir=settings.tmpdir, prefix="skbuild_"))
        mlog.info("tmpdir '{}'".format(self.tmpdir))
        cachedir = self.tmpdir / 'cache'
        pathlib.Path.mkdir(cachedir)

        sinfo = (self.maindir, self.mysettings)
        CM.vsave(self.tmpdir / settings.RESULT_SINFO, sinfo)

        nkbuilds = 0  # number of created kbuilds
        cache = {}  # makefile -> kbuild file
        makefiles = self.makefiles
        while makefiles:
            tmp_kbuilds = []
            for makefile, cond in makefiles:
                nkbuilds += 1

                if makefile in cache:
                    saved_file = cache[makefile]
                    kbuild = Kbuild.load(saved_file, self.mysettings)
                else:
                    kbuild = self.analyze(makefile)

                    saved_file = cachedir / 'kbuild_{}'.format(nkbuilds)
                    assert not saved_file.exists(), saved_file
                    kbuild.save(saved_file)
                    cache[makefile] = saved_file

                if cond is not self.default_cond:
                    kbuild = kbuild.fork(cond)

                tmp_kbuilds.append(kbuild)
                kbuild.save(self.tmpdir / 'kbuild_{}'.format(nkbuilds))

            makefiles = self.get_makefiles_from_kbuilds(tmp_kbuilds)

        mlog.info("analyzed {} kbuilds from {} makefiles in {:.2f}s".format(
            nkbuilds, len(cache), time() - st))

        return self.tmpdir

    def analyze(self, makefile):
        assert makefile.is_file(), makefile

        st = time()
        mlog.info("analyzing '{}'".format(makefile))
        kbuild = Kbuild(makefile, self.mysettings)
        kbuild.preprocess()
        kbuild.symexe()
        mlog.info("{}: {} vars ({:.2f}s)".format(
            makefile, len(kbuild.state.states), time() - st))

        if settings.detail:
            print(kbuild.state)

        return kbuild

    @staticmethod
    def load(result_dir):
        assert result_dir.is_dir(), result_dir

        maindir, mysettings = CM.vload(result_dir / settings.RESULT_SINFO)

        kbuilds = [Kbuild.load(result_dir/f, mysettings)
                   for f in result_dir.iterdir()
                   if f.is_file() and f.name != settings.RESULT_SINFO]

        return (maindir, mysettings, kbuilds)

    @classmethod
    def get_makefiles(cls, paths):
        assert all(isinstance(p, pathlib.Path) for p in paths), paths

        makefiles = [cls.get_makefile(p) for p in paths]
        return [makefile for makefile in makefiles if makefile]

    @classmethod
    def get_makefiles_from_kbuilds(cls, kbuilds):
        subdir_conds = {}
        for kb in kbuilds:
            for subdir, cond in kb.state.subdirs_with_cond(
                    kb.makefile.parent).items():
                if subdir in subdir_conds:
                    subdir_conds[subdir] = zsolver.disj(
                        subdir_conds[subdir], cond)
                else:
                    subdir_conds[subdir] = cond

        cache = {}
        for subdir, cond in subdir_conds.items():
            makefile = cls.get_makefile(subdir)
            if makefile:
                cache.setdefault(makefile, []).append(cond)

        makefiles = [(makefile, zsolver.simplify(z3.Or(cache[makefile])))
                     for makefile in sorted(cache)]
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
