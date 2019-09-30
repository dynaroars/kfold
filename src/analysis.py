import itertools
import pdb
import pathlib
import z3
from ds import Var

import helpers.vcommon as CM
import helpers.zsolver as zsolver

import settings
mlog = CM.getLogger(__name__, settings.logger_level)

DBG = pdb.set_trace


class Analysis:
    def __init__(self, result_dir):
        assert result_dir.is_dir(), result_dir

        from alg import Run
        self.main_dir, self.mysettings, self.kbuilds = Run.load(result_dir)
        assert len(self.kbuilds)

        self.config_vars = {}

        for kbuild in self.kbuilds:
            assert self.mysettings == kbuild.mysettings, \
                (self.mysettings, kbuild.mysettings)
            for c in kbuild.solver.__config_vars__:
                if c not in self.config_vars:
                    self.config_vars[c] = kbuild.solver.__config_vars__[c]

        kfiles_d = self.get_kfiles(None, self.main_dir)
        self.kfiles = frozenset(itertools.chain(*kfiles_d.values()))

        # remove files in lib- or obj-
        mlog.info("{}: {} {} kfiles, {} files, {} config vars".format(
            result_dir,
            self.mysettings.zstate.__class__.__name__,
            len(self.kbuilds), len(self.kfiles), len(self.config_vars)))

        for i, kbuild in enumerate(self.kbuilds):
            mlog.debug("{}. {}\n{}".format(
                i + 1, kbuild.makefile, kbuild.paths))

    def go(self, args):
        if args.src_dir:
            self.check_src_dir(pathlib.Path(args.src_dir).resolve())

        if args.build_dir:
            self.check_build_dir(pathlib.Path(args.build_dir).resolve())

    def check_src_dir(self, src_dir):
        """
        Obtain all C programs in src dir and check against Kbuild files
        """
        assert src_dir.is_dir(), src_dir

        # all c files in dir
        gfiles = [f for f in src_dir.rglob('*.*')
                  if f.suffix == '.c' and not f.name.startswith('.')]

        def get_includes(f):
            """
            get include files, e.g., #include "file.c"
            """
            includes = set()
            try:
                lines = f.read_text()
            except UnicodeDecodeError:
                lines = f.read_text(encoding="ISO-8859-1")

            for line in lines.splitlines():
                line = line.strip()
                if (line.startswith("#include") and
                        '<' not in line and '.c' in line):
                    include_f = line.replace(
                        "#include", '').replace('"', '').strip()
                    include_f = f.parent / include_f
                    assert include_f.is_file(), (f, include_f)
                    includes.add(include_f)
            return includes

        gfiles = {f.relative_to(src_dir):
                  set(f_.relative_to(src_dir) for f_ in get_includes(f))
                  for f in gfiles}

        mlog.debug("{} has {} C files".format(src_dir, len(gfiles)))

        # remove c files found from constraints and included files
        kfiles = set(f.with_suffix('.c')
                     for f in self.kfiles if f.suffix == '.o')

        removes = set()
        for f in kfiles:
            assert f in gfiles, f
            removes.add(f)
            for include_f in gfiles[f]:
                assert include_f in gfiles, include_f
                removes.add(include_f)

        for f in removes:
            gfiles.pop(f)

        mlog.debug(
            "gfiles: excluding {} targets and includes, {} remains"
            .format(len(removes), len(gfiles)))

        # remove files not in kbuild dirs
        # kbuild dirs also include subdirs that might not be mentioned
        # in setting topdirs
        # kbuild dirs also do not include dirs in setting topdirs that do
        # not have a Kbuild makefile
        kbuild_dirs = set(kb.topdir.relative_to(self.main_dir)
                          for kb in self.kbuilds)

        removes = set(f for f in gfiles
                      if f.parent not in kbuild_dirs)

        for f in removes:
            gfiles.pop(f)

        mlog.debug(
            "gfiles: excluding {} files not in top_dirs, {} remains"
            .format(len(removes), len(gfiles)))

        if gfiles:
            mlog.debug("W: {} files unaccounted for\n{}"
                       .format(len(gfiles), '\n'.join(map(str, gfiles))))

        return gfiles

    def check_build_dir(self, build_dir):
        assert build_dir.is_dir(), build_dir

        # get results from kbuild constraints
        config_constraint = self.config2constraint(
            build_dir / '.config')
        kfiles = self.get_kfiles(config_constraint, self.main_dir)
        kfiles = frozenset(f for target in kfiles for f in kfiles[target])

        # get groundtruth results
        gfiles = self.get_files_from_dir(
            build_dir, self.mysettings.ignore_dirs,
            self.mysettings.ignore_files)

        mlog.debug("{} kfiles, {} gfiles".format(len(kfiles), len(gfiles)))

        if gfiles != kfiles:
            only_in_g = gfiles - kfiles
            if only_in_g:
                mlog.warn("{} only in gfiles: {}".format(
                    len(only_in_g), ', '.join(sorted(map(str, only_in_g)))))

            only_in_k = kfiles - gfiles
            if only_in_k:
                mlog.warn("{} only in kfiles: {}".format(
                    len(only_in_k), ', '.join(sorted(map(str, only_in_k)))))

        else:
            mlog.info("all {} files matched".format(len(kfiles)))

    def get_kfiles(self, constraint, main_dir):
        assert constraint is None or z3.is_expr(constraint), constraint
        assert isinstance(main_dir, pathlib.Path), main_dir

        solver = zsolver.ZSolver(self.mysettings) \
            if z3.is_expr(constraint) else None

        paths = [(p, kbuild.makefile)
                 for kbuild in self.kbuilds
                 for p in kbuild.paths
                 if (constraint is None or
                     solver.is_valid(z3.Implies(constraint, p.cond)))]

        files_d = {}
        for path, makefile in paths:
            print(path)
            print(path.target_files)
            for v in path.target_files:
                assert isinstance(v, Var), v

                if v.name in self.mysettings.target_vars:
                    continue  # ignore obj-, lib-

                vals = [self.expand(v, path.vals_d) for v in v.vals
                        if v.endswith('.o')]
                vals = list(itertools.chain(*vals))
                tfiles_ = [makefile.parent / f for f in vals]
                tfiles_ = [f.relative_to(main_dir) for f in tfiles_]
                files_d.setdefault(v.name, []).extend(tfiles_)
        return files_d

    @classmethod
    def expand(cls, val_name, d):
        """
        val_name = files2.o
        d = {files2-y:{1.o, 2.o}}
        =>
        1.o, 2.o
        """

        key = val_name[:-2] + '-y'  # files2.o -> files2-y
        ret = list(d.get(key, frozenset([]))) + [val_name]
        return ret

    @classmethod
    def get_files_from_dir(cls, build_dir, ignore_dirs, ignore_files):
        """
        Obtained built objs
        """

        assert build_dir.is_dir(), build_dir

        fs = [f for f in build_dir.rglob('*.*') if f.suffix == '.o']
        fs = [f for f in fs
              if all(p.name not in ignore_dirs for p in f.parents)]
        fs = [f for f in fs if f.name not in ignore_files]
        fs = [f.relative_to(build_dir) for f in fs]
        return frozenset(fs)

    def config2constraint(self, config_file):
        assert config_file.is_file(), config_file

        solver = zsolver.ZSolver(self.mysettings)
        cOptTyp, cOptD = solver.get_typ_info(None)

        configs = [l.split("=") for l in CM.iread_strip(config_file)]

        myconfigs = {}
        for name, val in configs:
            assert name not in myconfigs, name
            assert self.mysettings.is_copt(name), name

            try:
                myconfigs[name] = cOptD[val]
            except KeyError:
                assert name not in self.config_vars
                mlog.warn("ignore {} = {}".format(name, val))

        undef_val = solver.undef_val
        nundefs = 0
        for name in self.config_vars:
            if name not in myconfigs and self.mysettings.is_copt(name):
                myconfigs[name] = undef_val
                nundefs += 1

        constraint = [z3.Const(name, cOptTyp) == myconfigs[name]
                      for name in myconfigs]
        constraint = z3.simplify(z3.And(*constraint))

        mlog.debug("{} config vars, {} undefs".format(len(myconfigs), nundefs))
        return constraint
