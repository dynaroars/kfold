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

    def __init__(self, path, recursive: bool = False, use_tristate: bool = False):
        """
        paths is a list of paths to either makefiles or directories
        """
        self.path = path.resolve()
        self.maindir = self.path.parent if self.path.is_file() else self.path
        self.mysettings = settings.Settings(self.maindir, use_tristate=use_tristate)
        self.recursive = recursive

        if self.path.is_file():  # explicit Makefile input
            makefiles = [(self.path, self.default_cond)]
        elif recursive:
            discovered = []
            for p in sorted(self.maindir.rglob("*")):
                if p.is_file() and (p.name in ("Makefile", "Kbuild", "Makefile.inc") or p.name.startswith("Kbuild") or p.name.startswith("Makefile")):
                    if not p.name.endswith(".o") and not p.name.endswith(".cmd") and not p.name.endswith(".d"):
                        discovered.append(p)
            makefiles = [(mk, self.default_cond) for mk in discovered]
        else:
            if self.mysettings.topdirs:
                # Entries may be globs, mirroring $(wildcard src/drivers/*).
                names, patterns = [], {}
                for d in sorted(self.mysettings.topdirs):
                    matches = ([str(p.relative_to(self.maindir))
                                for p in sorted(self.maindir.glob(d)) if p.is_dir()]
                               if any(c in d for c in "*?[") else
                               ([d] if (self.maindir / d).is_dir() else []))
                    for m in matches:
                        if m not in patterns:
                            names.append(m)
                            patterns[m] = d
            else:
                names, patterns = ["."], {".": "."}

            solver = zsolver.ZSolver(self.mysettings)
            makefiles = []
            for d in names:
                guard = self.default_cond
                syms = self.mysettings.topdir_guards.get(patterns[d])
                if syms:
                    guards = []
                    # Top-level lists such as drivers-$(CONFIG_X) enter the
                    # directory when the option is y or m.
                    for sym in syms:
                        zvar, values = solver.get_sort(sym)
                        guards.append(zvar != values[''])
                    guard = zsolver.mdisj(guards)
                for makefile in self.get_makefiles([self.maindir / d], self.mysettings):
                    makefiles.append((makefile, guard))

            if not makefiles:
                # Fallback: discover all makefile candidates in directory
                discovered = []
                for p in sorted(self.maindir.rglob("*")):
                    if p.is_file() and (p.name in ("Makefile", "Kbuild", "Makefile.inc") or p.name.startswith("Kbuild") or p.name.startswith("Makefile")):
                        if not p.name.endswith(".o") and not p.name.endswith(".cmd") and not p.name.endswith(".d"):
                            discovered.append(p)
                makefiles = [(mk, self.default_cond) for mk in discovered]

        assert makefiles, f"No Makefiles found in {self.path}"
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
        reached = {}  # makefile -> union of conditions already propagated
        skipped_revisits = 0
        reach_solver = zsolver.ZSolver(self.mysettings)
        self.all_kbuilds = []
        makefiles = self.makefiles
        while makefiles:
            tmp_kbuilds = []
            for makefile, cond in makefiles:
                incoming = zsolver.T if cond is self.default_cond else cond
                previous = reached.get(makefile, zsolver.F)
                # Propagate only configurations that have not reached this
                # Makefile before. A back edge in the directory graph then
                # contributes no new work once its guard is covered.
                delta = zsolver.conj(incoming, zsolver.neg(previous))
                if not reach_solver.is_sat(delta):
                    skipped_revisits += 1
                    continue
                reached[makefile] = zsolver.disj(previous, incoming)
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

                if delta is not zsolver.T:
                    kbuild = kbuild.fork(delta)

                tmp_kbuilds.append(kbuild)
                kbuild.save(self.tmpdir / 'kbuild_{}'.format(nkbuilds))

            self.all_kbuilds.extend(tmp_kbuilds)
            makefiles = self.get_makefiles_from_kbuilds(tmp_kbuilds, self.mysettings)

        self.reached_conditions = reached
        self.skipped_revisits = skipped_revisits
        mlog.info("analyzed {} kbuilds from {} makefiles; skipped {} covered revisits in {:.2f}s".format(
            nkbuilds, len(cache), skipped_revisits, time() - st))

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
    def get_makefiles(cls, paths, mysettings=None):
        assert all(isinstance(p, pathlib.Path) for p in paths), paths

        makefiles = [cls.get_makefile(p, mysettings) for p in paths]
        return [makefile for makefile in makefiles if makefile]

    @classmethod
    def get_makefiles_from_kbuilds(cls, kbuilds, mysettings=None):
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
            makefile = cls.get_makefile(subdir, mysettings)
            if makefile:
                cache.setdefault(makefile, []).append(cond)

        makefiles = [(makefile, zsolver.simplify(z3.Or(cache[makefile])))
                     for makefile in sorted(cache)]
        return makefiles

    @classmethod
    def get_makefile(cls, path, mysettings=None):
        """
        use Kbuild / Makefile / Makefile.inc as configured
        """
        assert isinstance(path, pathlib.Path), path

        if not path.exists():
            mlog.warn("{} does not exist".format(path))
            return None

        makefile = path
        if path.is_dir():
            entry_files = mysettings.entry_files if mysettings and hasattr(mysettings, 'entry_files') else ["Kbuild", "Makefile", "Makefile.inc"]
            makefile = None
            for fname in entry_files:
                candidate = path / fname
                if candidate.is_file():
                    makefile = candidate
                    break

        if not makefile or not makefile.is_file():
            mlog.warn("{} has no makefile".format(path))
            return None

        return makefile.resolve()
