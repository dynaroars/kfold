import tempfile
from time import time
import pathlib
import pdb

import helpers.vcommon as CM
from casestudy import CaseStudy
from kbuild import Kbuild

import settings
mlog = CM.getLogger(__name__, settings.logger_level)


class Run:
    def __init__(self, paths, casestudy):
        """
        paths is a list of paths to either makefiles or directories
        """
        assert all(isinstance(path, pathlib.Path) for path in paths), paths
        assert isinstance(casestudy, CaseStudy), casestudy

        self.paths = paths
        self.casestudy = casestudy

    def go(self):
        st = time()
        prefix = "skbuild_{}_".format(self.casestudy.__class__.__name__)
        self.tmpdir = pathlib.Path(tempfile.mkdtemp(
            dir=settings.tmpdir, prefix=prefix))

        default_cond = None
        results = {}  # [makefile][cond]
        makefiles = [(makefile, default_cond)
                     for makefile in self.get_makefiles(self.paths)]
        while makefiles:
            kbuilds = []
            for makefile, cond in makefiles:
                if makefile in results:
                    assert default_cond in results[makefile]

                    if cond not in results[makefile]:
                        assert cond is not default_cond
                        kbuild = results[makefile][default_cond]
                        results[makefile][cond] = kbuild.fork(cond)
                        kbuilds.append(results[makefile][cond])
                else:
                    kbuild = self.analyze(makefile)
                    results[makefile] = {default_cond: kbuild}
                    if cond is not default_cond:
                        results[makefile][cond] = kbuild.fork(cond)

                    kbuilds.append(results[makefile][cond])

            # recurse to subdirs if any
            makefiles = [(path.subdirs(kbuild.topdir), path.cond)
                         for kbuild in kbuilds for path in kbuild.paths]
            makefiles = [(makefile, cond)
                         for paths, cond in makefiles
                         for makefile in self.get_makefiles(paths)]

        mlog.info("done in {:.2f}s".format(time() - st))
        return self.tmpdir

    def analyze(self, makefile):
        assert makefile.is_file(), makefile

        result_dir = self.tmpdir
        assert result_dir.is_dir()

        kbuild = Kbuild(makefile, self.casestudy)
        kbuild.symexe()

        tofile = str(kbuild.makefile).replace("/", "_") + settings.RESULT_EXT
        kbuild.save(result_dir / tofile)
        return kbuild

    @classmethod
    def get_makefiles(cls, paths):
        assert all(isinstance(p, pathlib.Path) for p in paths), paths

        makefiles = [cls.get_makefile(p) for p in paths]
        return [makefile for makefile in makefiles if makefile]

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
