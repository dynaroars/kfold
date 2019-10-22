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
    SINFO_FILE = 'sinfo'  # orig input path, mysettings
    DONE_FILE = 'done'
    KBUILD_DIR = 'kbuilds'  # dir consisting of symlinks of kbuilds
    CACHE_DIR = 'cache'

    def __init__(self, path, tmpdir=None, cache={}):
        """
        paths is a list of paths to either makefiles or directories
        cache =  {makefile -> {hash_cond -> kbuild file}}
        """
        assert path.exists(), path
        assert tmpdir is None or tmpdir.is_dir(), tmpdir

        self.path = path.resolve()
        self.maindir = self.get_maindir(self.path)
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

        if not tmpdir:  # first time running
            self.tmpdir = pathlib.Path(tempfile.mkdtemp(
                dir=settings.tmpdir, prefix="kb_{}_".format(self.path.name)))
            mlog.info("tmpdir '{}'".format(self.tmpdir))

        else:  # continue from previous run
            self.tmpdir = tmpdir

        self.cache = cache
        self.kbuilds_dir, self.cache_dir = self.get_dirs(self.tmpdir)
        self.sinfo_file, self.done_file = self.get_files(self.tmpdir)
        if not self.sinfo_file.exists():
            CM.vsave(self.sinfo_file, (self.path, self.mysettings))

    @classmethod
    def get_files(cls, dir_):
        sinfo_file = dir_ / cls.SINFO_FILE
        done_file = dir_ / cls.DONE_FILE
        return sinfo_file, done_file

    @classmethod
    def get_dirs(cls, dir_):
        kbuilds_dir = dir_ / cls.KBUILD_DIR
        if not kbuilds_dir.exists():
            kbuilds_dir.mkdir()
        cache_dir = dir_ / cls.CACHE_DIR
        if not cache_dir.exists():
            cache_dir.mkdir()

        return kbuilds_dir, cache_dir

    def go(self):
        def symlink(kfile):
            assert kfile.is_file(), kfile

            kfile_lnk = self.kbuilds_dir / kfile.name
            if not kfile_lnk.exists():
                kfile_lnk.symlink_to(kfile)

        st = time()

        nkfiles = 0
        makefiles = self.makefiles
        while makefiles:
            subdirss = []
            for makefile, cond in makefiles:
                kfile, subdirs = self.go_makefile(makefile, cond)
                symlink(kfile)
                nkfiles += 1

                subdirss.extend(subdirs)

            makefiles = self.get_makefiles_from_subdirs(subdirss)

        mlog.info("analyzed {} kfiles in {:.2f}s".format(nkfiles, time() - st))

        assert not self.done_file.exists(), self.done_file
        self.done_file.touch()
        return self.tmpdir

    def go_makefile(self, makefile, cond):

        cond_hash = hash(cond)
        default_cond_hash = hash(Kbuild.default_cond)

        def write(kbuild):

            kfile = '_'.join(kbuild.makefile.parts).replace('/', '_')
            kfile = "{}_{}".format(kfile, kbuild.precond_hash)
            kfile = self.cache_dir / kfile
            assert kbuild.precond_hash not in self.cache[kbuild.makefile],\
                (kbuild.makefile, kbuild.precond_hash, kfile)

            assert not kfile.exists(), kfile
            kbuild.save(kfile)

            self.cache[kbuild.makefile][kbuild.precond_hash] = kfile

        def fork(kbuild, cond):
            assert cond is not Kbuild.default_cond
            kbuild = kbuild.fork(cond)
            assert cond_hash == kbuild.precond_hash
            return kbuild

        if makefile not in self.cache:
            kbuild = self.analyze(makefile)
            self.cache[kbuild.makefile] = {}
            write(kbuild)
            assert default_cond_hash in self.cache[kbuild.makefile]

            if cond_hash != kbuild.precond_hash:
                kbuild = fork(kbuild, cond)
                write(kbuild)
                assert cond_hash in self.cache[kbuild.makefile]
        else:
            mlog.warn('{} already in cache1'.format(makefile))
            if cond_hash in self.cache[makefile]:
                mlog.warn(
                    '{} also in cache 2. Nothing to do'.format(makefile))
                kfile = self.cache[makefile][cond_hash]
                kbuild = Kbuild.load(kfile, self.mysettings)
            else:
                assert default_cond_hash in self.cache[makefile]
                kfile = self.cache[makefile][default_cond_hash]
                kbuild = Kbuild.load(kfile, self.mysettings)
                kbuild = fork(kbuild, cond)
                write(kbuild)
                assert cond_hash in self.cache[kbuild.makefile]

        subdirss = [(path.subdirs(kbuild.makefile.parent), path.cond)
                    for path in kbuild.paths]
        subdirss = [(subdirs, pcond) for subdirs, pcond in subdirss if subdirs]

        kfile = self.cache[makefile][cond_hash]
        assert kfile.is_file(), kfile
        return kfile, subdirss

    def analyze(self, makefile):
        assert makefile.is_file(), makefile

        st = time()
        mlog.info("analyzing '{}'".format(makefile))
        kbuild = Kbuild(makefile, self.mysettings, hash(Kbuild.default_cond))
        kbuild.preprocess()
        kbuild.symexe()
        mlog.info("{}: {} paths ({:.2f}s)".format(
            makefile, len(kbuild.paths), time() - st))

        if settings.detail:
            print(kbuild.paths)

        return kbuild

    # @classmethod
    # def load(cls, result_dir):
    #     assert result_dir.is_dir(), result_dir

    #     kbuilds_dir, cache_dir, sinfo_file, done_file = \
    #         cls.get_files(result_dir)

    #     done = done_file.exists()
    #     if done:
    #         orig_path, mysettings = CM.vload(sinfo_file)
    #         kbuilds = [Kbuild.load(f.resolve(), mysettings)
    #                    for f in kbuilds_dir.iterdir()]

    #     else:
    #         kbuilds = [(f, Kbuild.load(f, mysettings))
    #                    for f in result_dir.iterdir()
    #                    if f.is_file() and f.suffix == cls.kbuild_suffix]
    #         cache = {}
    #         for f, kbuild in kbuilds:
    #             makefile = kbuild.makefile
    #             cond_hash = kbuild.precond_hash
    #             if makefile not in cache:
    #                 cache[makefile] = {}
    #             if cond_hash not in cache[makefile]:
    #                 cache[makefile][cond_hash] = f

    #     return done, orig_path, mysettings, kbuilds

    # @classmethod
    # def load_from_cachedir(cls, old_cachedir, cachedir, cache, mysettings):
    #     assert old_cachedir.is_dir(), old_cachedir
    #     assert cachedir.is_dir(), cachedir
    #     assert isinstance(cache, dict), cache

    #     import shutil
    #     for from_f in old_cachedir.iterdir():
    #         to_f = cachedir / (from_f.relative_to(old_cachedir))
    #         assert from_f.is_file(), from_f
    #         assert not to_f.exists(), to_f
    #         shutil.copy(from_f, to_f)
    #         kbuild = Kbuild.load(from_f, mysettings)
    #         makefile = kbuild.makefile

    #         assert makefile not in cache, makefile
    #         cache[makefile] = to_f

    @classmethod
    def get_makefiles(cls, paths):
        assert all(isinstance(p, pathlib.Path) for p in paths), paths

        makefiles = [cls.get_makefile(p) for p in paths]
        return [makefile for makefile in makefiles if makefile]

    @classmethod
    def get_makefiles_from_subdirs(cls, subdirss):
        makefiles = [(makefile, cond)
                     for subdirs, cond in subdirss
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

    @classmethod
    def get_maindir(self, path):
        return path.parent if path.is_file() else path

    @classmethod
    def doit(cls, path, args):
        """
        Return
        1. None: not a result dir
        2. : result dir, but incomplete
        3. : result dir, completed
        """

        sinfo_file, done_file = cls.get_files(path)
        if done_file.exists():  # completed run
            kbuilds_dir, _ = cls.get_dirs(path)
            orig_path, mysettings = CM.vload(sinfo_file)
            kbuilds = [Kbuild.load(f.resolve(), mysettings)
                       for f in kbuilds_dir.iterdir()]
            from analysis import Analysis
            mycls = Analysis(cls.get_maindir(orig_path), mysettings, kbuilds)
            return mycls.go(args)

        else:
            if sinfo_file.exists():  # incompleted run
                _, cache_dir = cls.get_dirs(path)
                orig_path, mysettings = CM.vload(sinfo_file)

                kbuilds = [(kfile, Kbuild.load(kfile, mysettings))
                           for kfile in cache_dir.iterdir()]
                cache = {}
                for kfile, kbuild in kbuilds:
                    makefile = kbuild.makefile
                    cond_hash = kbuild.precond_hash

                    # if 'libarchive' in str(makefile):
                    #     print('hi', makefile, cond_hash, kfile)
                    #     DBG()
                    if makefile not in cache:
                        cache[makefile] = {}
                    if cond_hash not in cache[makefile]:
                        cache[makefile][cond_hash] = kfile

                mycls = cls(orig_path, tmpdir=path, cache=cache)
                tmpdir = mycls.go()
                return tmpdir

            else:  # new run
                mycls = cls(path)
                tmpdir = mycls.go()
                return tmpdir
