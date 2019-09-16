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

        from alg import Run
        self.main_dir, self.mysettings, self.kbuilds = Run.load(result_dir)
        assert len(self.kbuilds)

        self.mysettings = self.kbuilds[0].mysettings
        self.COptTyp, self.COptD, config_vars = self.kbuilds[0].typ_info
        self.config_vars = {c: config_vars[c] for c in config_vars}

        for kbuild in self.kbuilds[1:]:
            t, d, config_vars = kbuild.typ_info
            assert t == self.COptTyp
            assert d == self.COptD
            assert self.mysettings == kbuild.mysettings, \
                (self.mysettings, kbuild.mysettings)
            for c in config_vars:
                if c not in self.config_vars:
                    self.config_vars[c] = config_vars[c]

        mlog.debug("{}: {}, {} kbuilds, {} config vars".format(
            result_dir, self.mysettings.zstate.__class__.__name__,
            len(self.kbuilds), len(self.config_vars)))

        self.files_d = self.get_target_files(None, self.main_dir)
        self.all_files = frozenset(itertools.chain(*self.files_d.values()))
        # remove files in lib- or obj-
        mlog.info("{} Kbuilds, {} files".format(
            len(self.kbuilds), len(self.all_files)))

    def go(self, args):
        if args.src_dir:
            self.check_src_dir(pathlib.Path(args.src_dir).resolve())

        if args.build_dir:
            self.check_build_dir(pathlib.Path(args.build_dir).resolve())

    def check_src_dir(self, src_dir):
        """
        Obtain all C programs and check
        """
        assert os.path.isdir(src_dir), src_dir

        # all c files in dir
        g_files = [f for f in src_dir.rglob('*.*')
                   if f.suffix == '.c' and not f.name.startswith('.')]

        def get_includes(f):
            includes = set()
            for l in f.read_text().splitlines():
                l = l.strip()
                if l.startswith("#include") and '<' not in l and '.c' in l:
                    l = l.replace("#include", '').replace('"', '').strip()
                    include_f = f.parent / l
                    assert include_f.is_file(), include_f
                    includes.add(include_f)
            return includes

        g_files = {f.relative_to(src_dir):
                   set(f_.relative_to(src_dir) for f_ in get_includes(f))
                   for f in g_files}

        mlog.debug("{} has {} C files".format(src_dir, len(g_files)))

        # remove c files found from constraints and included files
        c_files = set(f.with_suffix('.c')
                      for f in self.all_files if f.suffix == '.o')

        removes = set()
        for f in c_files:
            assert f in g_files, f
            removes.add(f)
            for include_f in g_files[f]:
                assert include_f in g_files, include_f
                removes.add(include_f)

        for f in removes:
            g_files.pop(f)

        mlog.debug(
            "Excluding {} targets and includes, {} remains"
            .format(len(removes), len(g_files)))

        # remove files not in topdir
        removes = set(f for f in g_files
                      if f.parent not in self.mysettings.top_dirs)

        for f in removes:
            g_files.pop(f)

        mlog.debug(
            "Excluding {} files not in top_dir, {} remains"
            .format(len(removes), len(g_files)))

        # print(g_files)

        # # remove util-linux/volume_id/unused_*.c
        # removes = set(f for f in sfiles if 'used_' in f)
        # for f in removes:
        #     sfiles.pop(f)

        # mlog.debug(
        #     "{} files (- {} unsed)".format(len(sfiles), len(removes)))

        if g_files:
            mlog.debug("W: {} files unaccounted for\n{}"
                       .format(len(g_files), '\n'.join(map(str, g_files))))

        return g_files

    def check_build_dir(self, build_dir):
        assert build_dir.is_dir(), build_dir

        # get results from kbuild constraints
        config_constraint = self.config2constraint(
            build_dir / '.config', self.mysettings.zstate.undef_val)
        c_files = self.get_target_files(config_constraint, self.main_dir)
        c_files = frozenset(f for target in c_files for f in c_files[target])

        # get groundtruth results
        g_files = self.get_files_from_dir(
            build_dir, self.mysettings.ignore_dirs,
            self.mysettings.ignore_files)

        if g_files != c_files:
            only_in_g = g_files - c_files
            if only_in_g:
                mlog.warn("only in g_files: {}".format(','.join(
                    sorted(map(str, only_in_g)))))

            only_in_c = c_files - g_files
            if only_in_c:
                mlog.warn("only in c_files: {}".format(','.join(
                    sorted(map(str, only_in_c)))))

        else:
            mlog.info("all {} files matched".format(len(c_files)))

    def get_target_files(self, constraint, main_dir):
        assert constraint is None or z3.is_expr(constraint), constraint
        assert isinstance(main_dir, pathlib.Path), main_dir

        solver = zsolver.ZSolver(
            self.mysettings.zstate) if z3.is_expr(constraint) else None

        files_d = {}
        for kbuild in self.kbuilds:
            for path in kbuild.paths:
                if constraint is None or \
                   solver.is_valid(z3.Implies(constraint, path.cond)):
                    for v in path.target_files:
                        assert isinstance(v, Var), v

                        if v.name in self.mysettings.target_vars:
                            continue  # ignore obj-, lib-

                        tfiles_ = [kbuild.makefile.parent / f
                                   for f in v.vals if f.endswith('.o')]
                        tfiles_ = [f.relative_to(main_dir) for f in tfiles_]
                        files_d.setdefault(v.name, []).extend(tfiles_)
        return files_d

    @classmethod
    def get_files_from_dir(cls, build_dir, ignore_dirs, ignore_files):
        """
        Obtained built objs
        """

        assert build_dir.is_dir(), build_dir

        # ignores = {'.cmd', '.a', '.h', '.in', '.c', '.out', '.net', '.log',
        #            '.html', '.txt', '.map', '.1', '.method', '.pod', '.d'}

        fs = [f for f in build_dir.rglob('*.*') if f.suffix == '.o']
        fs = [f for f in fs
              if all(p.name not in ignore_dirs for p in f.parents)]
        fs = [f for f in fs if f.name not in ignore_files]
        fs = [f.relative_to(build_dir) for f in fs]
        return frozenset(fs)

    def config2constraint(self, config_file, undef_val):
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

        constraint = [z3.Const(s, self.COptTyp) == myconfig[s]
                      for s in myconfig]
        constraint = z3.simplify(z3.And(*constraint))
        return constraint
