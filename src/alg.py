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
    cache = "cache"

    def __init__(self, path):
        """
        paths is a list of paths to either makefiles or directories
        """
        assert path.exists(), path
        self.path = path.resolve()
        self.maindir = self.path.parent if self.path.is_file() else self.path
        self.mysettings = settings.Settings(self.maindir)

        if self.path.is_file():  # explicit Makefile input
            makefiles = [self.path]
        else:
            if self.mysettings.topdirs:
                topdirs = [self.maindir /
                           d for d in self.mysettings.topdirs]
                topdirs = [d for d in topdirs if d.is_dir()]
            else:
                topdirs = [self.maindir]

            makefiles = self.get_makefiles(topdirs)

        assert makefiles
        self.makefiles = [(f, Kbuild.default_cond) for f in makefiles]

        # tmp dirs
        self.tmpdir = pathlib.Path(tempfile.mkdtemp(
            dir=settings.tmpdir, prefix="kb_{}_".format(self.path.name)))
        mlog.info("tmpdir '{}'".format(self.tmpdir))
        self.cachedir = self.tmpdir / self.cache
        pathlib.Path.mkdir(self.cachedir)

    def go(self, args):

        st = time()
        cache = {}  # {makefile -> {hash_cond -> kbuild file}}
        if args.partial_cachedir:
            self.load_from_cachedir(pathlib.Path(args.partial_cachedir),
                                    self.cachedir, cache, self.mysettings)

            mlog.debug('loaded {} cached files'.format(len(cache)))

        sinfo = (self.maindir, self.mysettings)
        CM.vsave(self.tmpdir / settings.RESULT_SINFO, sinfo)

        makefiles = self.makefiles
        while makefiles:
            tmp_kbuilds = []
            for makefile, cond in makefiles:
                kbuild = self.go_makefile(makefile, cond, tmp_kbuilds, cache)
                tmp_kbuilds.append(kbuild)

            makefiles = self.get_makefiles_from_kbuilds(tmp_kbuilds)

        msg = "analyzed {} makefiles in {:.2f}s".format(
            len(cache), time() - st)
        mlog.info(msg)

        CM.vsave(self.tmpdir / 'done', msg)
        return self.tmpdir

    def go_makefile(self, makefile, cond, tmp_kbuilds, cache):

        cond_hash = hash(cond)

        def write(kbuild):
            kfile = '_'.join(kbuild.makefile.parts).replace('/', '_')
            kfile = "{}_{}".format(kfile, kbuild.precond_hash)
            kfile = (self.cachedir / kfile).with_suffix('.kbuild')
            assert not kfile.exists(), kfile
            kbuild.save(kfile)
            cache[kbuild.makefile][kbuild.precond_hash] = kfile

        def fork(kbuild, cond):
            assert cond is not Kbuild.default_cond
            kbuild = kbuild.fork(cond)
            assert cond_hash == kbuild.precond_hash
            return kbuild

        if makefile not in cache:
            kbuild = self.analyze(makefile)
            cache[kbuild.makefile] = {}
            write(kbuild)
            assert hash(Kbuild.default_cond) in cache[kbuild.makefile]

            if cond_hash != kbuild.precond_hash:
                kbuild = fork(kbuild, cond)
                write(kbuild)
                assert cond_hash in cache[kbuild.makefile]
        else:
            mlog.warn('{} already in cache1'.format(makefile))
            if cond_hash in cache[makefile]:
                mlog.warn(
                    '{} also in cache 2. Nothing to do'.format(makefile))
                kfile = cache[makefile][cond_hash]
                kbuild = Kbuild.load(kfile, self.mysettings)
            else:
                assert hash(Kbuild.default_cond) in cache[kbuild.makefile]
                kbuild = cache[makefile][hash(Kbuild.default_cond)]
                kbuild = fork(kbuild, cond)
                write(kbuild)
                assert cond_hash in cache[kbuild.makefile]

        return kbuild

    def analyze(self, makefile):
        assert makefile.is_file(), makefile

        st = time()
        mlog.info("analyzing '{}'".format(makefile))
        kbuild = Kbuild(makefile, self.mysettings)
        kbuild.preprocess()
        kbuild.symexe()
        mlog.info("{}: {} paths ({:.2f}s)".format(
            makefile, len(kbuild.paths), time() - st))

        if settings.detail:
            print(kbuild.paths)

        return kbuild

    @staticmethod
    def load(result_dir):
        assert result_dir.is_dir(), result_dir

        maindir, mysettings = CM.vload(result_dir / settings.RESULT_SINFO)
        kbuilds = [Kbuild.load(f, mysettings)
                   for f in result_dir.iterdir()
                   if f.is_file() and f.name != settings.RESULT_SINFO]

        return (maindir, mysettings, kbuilds)

    @classmethod
    def load_from_cachedir(cls, old_cachedir, cachedir, cache, mysettings):
        assert old_cachedir.is_dir(), old_cachedir
        assert cachedir.is_dir(), cachedir
        assert isinstance(cache, dict), cache

        import shutil
        for from_f in old_cachedir.iterdir():
            to_f = cachedir / (from_f.relative_to(old_cachedir))
            assert from_f.is_file(), from_f
            assert not to_f.exists(), to_f
            shutil.copy(from_f, to_f)
            kbuild = Kbuild.load(from_f, mysettings)
            makefile = kbuild.makefile

            assert makefile not in cache, makefile
            cache[makefile] = to_f

    @classmethod
    def get_makefiles(cls, paths):
        assert all(isinstance(p, pathlib.Path) for p in paths), paths

        makefiles = [cls.get_makefile(p) for p in paths]
        return [makefile for makefile in makefiles if makefile]

    @classmethod
    def get_makefiles_from_kbuilds(cls, kbuilds):
        makefiles = [(path.subdirs(kb.makefile.parent), path.cond)
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
