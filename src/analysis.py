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

        self.config = self.kbuilds[0].config
        self.COptTyp, self.COptD, config_vars = self.kbuilds[0].typ_info
        self.config_vars = {c: config_vars[c] for c in config_vars}

        for kbuild in self.kbuilds[1:]:
            t, d, config_vars = kbuild.typ_info
            assert t == self.COptTyp
            assert d == self.COptD
            assert self.config == kbuild.config
            for c in config_vars:
                if c not in self.config_vars:
                    self.config_vars[c] = config_vars[c]

        self.files_d = self.get_target_files(None)
        self.all_files = frozenset(itertools.chain(*self.files_d.values()))

        # remove files in lib- or obj-
        self.target_files = self.remove_files(self.files_d)
        assert (self.target_files == self.all_files)

        mlog.debug("{}: config {}, "
                   "{} kbuilds, {} config vars, {} files".format(
                       result_dir, self.config.__class__.__name__,
                       len(self.kbuilds), len(self.config_vars),
                       len(self.all_files), len(self.target_files)))

    def go(self, args):
        if args.src_dir:
            src_dir = pathlib.Path(args.src_dir).resolve()
            assert src_dir.is_dir()

            mlog.info("*** Check Coverage over '{}' ***".format(src_dir))
            self.check_src_dir(src_dir)

        if args.build_dir:
            build_dir = pathlib.Path(args.build_dir).resolve()
            assert build_dir.is_dir()

            # get results from kbuild constraints
            c_files = self.get_files_from_config(build_dir / '.config')
            c_files = self.remove_files(c_files)

            # get groundtruth results
            ignore_dirs = self.config.ignore_build_dirs
            ignore_files = self.config.ignore_build_files
            g_files = self.get_files_from_dir(
                build_dir, ignore_dirs, ignore_files)
            DBG()
        return None

    @classmethod
    def remove_files(cls, files_d):
        # remove files in lib- or obj-
        target_files = [files_d[target] for target in files_d
                        if target not in settings.target_vars]
        return frozenset(itertools.chain(*target_files))

    def get_target_files(self, constraint):
        assert constraint is None or z3.is_expr(constraint), constraint

        solver = zsolver.ZSolver(self.config.__zstate__) \
            if z3.is_expr(constraint) else None

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
        fs = [pathlib.Path(str(f)[len(str(build_dir))+1:]) for f in fs]
        fs = [f for f in fs
              if all(d not in f.parents for d in ignore_dirs)]

        fs = [f for f in fs
              if f.name not in ignore_files]
        return frozenset(fs)

    def get_files_from_config(self, config_file):
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

        DBG()
        undef = self.COptD[config.undef_val]
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
