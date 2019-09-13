import itertools
import pdb
import os.path
import pathlib
import z3
from ds import Var

import helpers.vcommon as CM
import helpers.zsolver as zsolver
from kbuild import Kbuild

import settings
mlog = CM.getLogger(__name__, settings.logger_level)

DBG = pdb.set_trace


class Analysis:
    def __init__(self, result_dir):
        assert result_dir.is_dir(), result_dir

        self.kbuilds = self.load(result_dir)
        assert len(self.kbuilds)

        self.mysettings = self.kbuilds[0].mysettings
        self.COptTyp, self.COptD, config_vars = self.kbuilds[0].typ_info
        self.config_vars = {c: config_vars[c] for c in config_vars}

        for kbuild in self.kbuilds[1:]:
            t, d, config_vars = kbuild.typ_info
            assert t == self.COptTyp
            assert d == self.COptD
            assert self.mysettings == kbuild.mysettings
            for c in config_vars:
                if c not in self.config_vars:
                    self.config_vars[c] = config_vars[c]

        mlog.debug("{}: {}, {} kbuilds, {} config vars".format(
            result_dir, self.mysettings.zstate.__class__.__name__,
            len(self.kbuilds), len(self.config_vars)))

        self.files_d = self.get_target_files(None)
        self.all_files = frozenset(itertools.chain(*self.files_d.values()))

        # remove files in lib- or obj-
        self.target_files = self.remove_files(self.files_d)
        assert (self.target_files == self.all_files)

    def go(self, args):
        if args.src_dir:
            src_dir = pathlib.Path(args.src_dir).resolve()
            assert src_dir.is_dir()

            mlog.info("*** Check Coverage over '{}' ***".format(src_dir))
            self.check_src_dir(src_dir)

        if args.build_dir:
            build_dir = pathlib.Path(args.build_dir).resolve()
            self.check_build_dir(build_dir)

    def check_src_dir(self, src_dir):
        """
        Obtain all C programs and check
        """
        assert os.path.isdir(src_dir), src_dir

        # get all src files from src_dir
        src_dir_len = len(str(src_dir))
        sfiles = {}

        def get_includes(f):
            includes = set()
            try:
                ls = list(CM.iread(f))
            except UnicodeDecodeError as ex:
                mlog.warn("cannot parse '{}': {}".format(f, ex))
                return includes

            for l in ls:
                l = l.strip()
                if l.startswith("#include") and '<' not in l and '.c' in l:
                    l = l.replace("#include", '').replace('"', '').strip()
                    ifile = os.path.join(os.path.split(f)[0], l)
                    assert os.path.isfile(ifile), ifile
                    includes.add(ifile[src_dir_len:])

            return includes

        for root, subdirs, files in os.walk(src_dir):
            # ignore .hidden dirs and files
            subdirs[:] = [d for d in subdirs if not d.startswith('.')]
            files[:] = [f for f in files
                        if os.path.splitext(f)[1] == '.c' and not f.startswith('.')]
            for f in files:
                f = os.path.join(root, f)
                assert os.path.isfile(f), "{}: not exist".format(f)

                f_ = f[src_dir_len:]
                assert f_ not in sfiles

                sfiles[f_] = get_includes(pathlib.Path(f))

        mlog.debug("{} files".format(len(sfiles)))

        # remove target and include files
        tfiles = set(str(f).replace('.o', '.c')
                     for f in self.target_files)

        removes = set()
        for f in tfiles:
            DBG()
            assert f in sfiles
            removes.add(f)
            for f_ in sfiles[f]:
                assert f_ in sfiles, f_
                removes.add(f_)

        for f in removes:
            sfiles.pop(f)

        mlog.debug("{} files (- {} targets)".format(len(sfiles), len(removes)))

        # remove files not in topdirs
        def in_topdirs(f):
            s = f.split(os.path.sep)[0] + os.path.sep
            return s in self.casestudy.topdirs

        removes = set(f for f in sfiles if not in_topdirs(f))
        for f in removes:
            sfiles.pop(f)

        mlog.debug(
            "{} files (- {} not in topdir)".format(len(sfiles), len(removes)))

        # remove util-linux/volume_id/unused_*.c
        removes = set(f for f in sfiles if 'used_' in f)
        for f in removes:
            sfiles.pop(f)

        mlog.debug(
            "{} files (- {} unsed)".format(len(sfiles), len(removes)))

        print('\n'.join(sorted(sfiles)))

    def check_build_dir(self, build_dir):
        assert build_dir.is_dir(), build_dir

        # get groundtruth results
        g_files = self.get_files_from_dir(
            build_dir, self.mysettings.ignore_dirs,
            self.mysettings.ignore_files)
        g_files = self.remove_common_prefix(g_files)

        # get results from kbuild constraints
        c_files = self.get_files_from_config(
            build_dir / '.config', self.mysettings.zstate.undef_val)
        c_files = self.remove_files(c_files)
        c_files = self.remove_common_prefix(c_files)

        if c_files != g_files:
            only_in_c = c_files - g_files
            if only_in_c:
                mlog.warn("only in c_files: ", ','.join(sorted(only_in_c)))

            only_in_g = g_files - c_files
            if only_in_g:
                mlog.warn("only in g_files: ", ','.join(sorted(only_in_g)))

        else:
            mlog.info("all {} files matched".format(len(c_files)))

    def remove_files(self, files_d):
        # remove files in lib- or obj-
        target_files = [files_d[target] for target in files_d
                        if target not in self.mysettings.target_vars]
        return frozenset(itertools.chain(*target_files))

    def get_target_files(self, constraint):
        assert constraint is None or z3.is_expr(constraint), constraint

        solver = zsolver.ZSolver(
            self.mysettings.zstate) if z3.is_expr(constraint) else None

        files_d = {}
        for kbuild in self.kbuilds:
            paths = [path for path in kbuild.paths if constraint is None or
                     solver.is_valid(z3.Implies(constraint, path.cond))]
            for path in paths:
                tfiles = path.target_files
                assert all(isinstance(v, Var) for v in tfiles), tfiles
                for v in tfiles:
                    tfiles_ = [kbuild.makefile.parent / f for f in v.vals]
                    files_d.setdefault(v.name, []).extend(tfiles_)

        return files_d

    @classmethod
    def load(cls, result_dir):
        assert result_dir.is_dir(), result_dir
        assert all(f.is_file() for f in result_dir.iterdir())

        return [Kbuild.load(result_dir / f) for f in result_dir.iterdir()]

    @classmethod
    def get_files_from_dir(cls, build_dir, ignore_dirs, ignore_files):
        """
        Obtained built objs
        """

        assert build_dir.is_dir(), build_dir

        # ignores = {'.cmd', '.a', '.h', '.in', '.c', '.out', '.net', '.log',
        #            '.html', '.txt', '.map', '.1', '.method', '.pod', '.d'}

        fs = [f for f in build_dir.rglob('*.*')
              if f.suffix == '.o']
        fs = [f.relative_to(build_dir) for f in fs]
        fs = [f for f in fs
              if all(p.name not in ignore_dirs for p in f.parents)]
        fs = [f for f in fs
              if f.name not in ignore_files]
        return frozenset(fs)

    def get_files_from_config(self, config_file, undef_val):
        """
        return files that will be built from config_file
        """

        assert config_file.is_file(), config_file
        contents = [l.split("=") for l in CM.iread_strip(config_file)]

        myconfig = {}
        for s, v in contents:
            assert s not in myconfig
            try:
                myconfig[s] = self.COptD[v]
            except KeyError:
                assert s not in self.config_vars
                mlog.warn("ignore {} = {}".format(s, v))

        undef = self.COptD[undef_val]
        for s in self.config_vars:
            if s not in myconfig:
                myconfig[s] = undef

        constraint = [
            z3.Const(s, self.COptTyp) == v for s, v in myconfig.items()
        ]
        constraint = z3.simplify(z3.And(*constraint))
        files_d = self.get_target_files(constraint)

        # mlog.debug(', '.join("{}={}".format(s, v) for s, v in contents))
        # mlog.debug("{} targets\n{}".format(
        #     len(constraint_files), '\n'.join("{} ({}) = {}".format(
        #         name, len(constraint_files[name]),
        #         ', '.join(constraint_files[name])) for name in constraint_files)))
        return files_d

    @classmethod
    def remove_common_prefix(self, files):
        commonprefix = pathlib.Path(os.path.commonprefix(list(files)))
        return frozenset(f.relative_to(commonprefix) for f in files)
