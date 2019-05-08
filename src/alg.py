import itertools
import tempfile
from time import time
import pathlib
import pdb
import z3
import vcommon as CM
import zsolver
from casestudy import CaseStudy
from kbuild import Kbuild

import settings
mlog = CM.getLogger(__name__, settings.logger_level)

trace = pdb.set_trace
pause = CM.pause


class Run:
    def __init__(self, paths, casestudy):
        """
        paths is a list of paths to either makefiles or directories
        """
        assert paths, paths
        assert isinstance(casestudy, CaseStudy), casestudy

        self.paths = [pathlib.Path(p) for p in paths]
        self.casestudy = casestudy

    def go(self):
        st = time()
        prefix = "skbuild_{}_".format(self.casestudy.__class__.__name__)
        self.tmpdir = pathlib.Path(tempfile.mkdtemp(
            dir=settings.tmpdir, prefix=prefix))

        results = []
        files = self.get_makefiles(self.paths, cond=zsolver.T)
        while files:
            # parallel
            kbuilds = [self.analyze(makefile, cond, self.tmpdir)
                       for makefile, cond in files]
            results.extend(kbuilds)

            # recurse to subdirs if any
            files = [self.get_makefiles(path.subdirs(kbuild.topdir), path.cond)
                     for kbuild in kbuilds for path in kbuild.paths]
            files = list(itertools.chain(*files))

        mlog.info("analyzed {} kbuild makefiles in {}s".format(
            len(results), time() - st))

        return self.tmpdir

    def analyze(self, makefile, cond, result_dir):
        assert makefile.is_file(), makefile
        assert cond is None or z3.is_expr(cond), cond
        assert result_dir.exists(), result_dir

        kbuild = Kbuild(makefile, self.casestudy)
        kbuild.symexe(cond)
        tofile = str(kbuild.makefile).replace("/", "_") + settings.results_ext
        kbuild.save(result_dir / tofile)
        return kbuild

    @classmethod
    def get_makefiles(cls, paths, cond):
        assert all(isinstance(p, pathlib.Path) for p in paths), paths
        assert cond is None or z3.is_expr(cond), cond

        makefiles = [cls.get_makefile(p) for p in paths]
        return [(makefile, cond) for makefile in makefiles if makefile]

    @classmethod
    def get_makefile(cls, path):
        """
        use Kbuild file if found, otherwise try Makefile
        """
        assert isinstance(path, pathlib.Path)

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
