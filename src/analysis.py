import os
import itertools
import pdb

import vcommon as CM
import z3
import zsolver
from kbuild import Kbuild

from ds import Var

import settings
mlog = CM.getLogger(__name__, settings.logger_level)

trace = pdb.set_trace
pause = CM.pause

class Analysis:
    def __init__(self, result_dir):
        assert os.path.isdir(result_dir), result_dir

        self.kbuilds = load(result_dir)
        assert len(self.kbuilds)

        self.COptTyp, self.COptD, self.config_vars = \
            self.kbuilds[0].typ_info

        for kbuild in self.kbuilds[1:]:
            t, d, config_vars = kbuild.typ_info
            assert t == self.COptTyp
            assert d == self.COptD
            for s in config_vars:
                if s not in self.config_vars:
                    self.config_vars[s] = config_vars[s]

        self.commonpath = os.path.commonpath(
            [kbuild.makefile for kbuild in self.kbuilds])
        self.commonpath_len = len(self.commonpath)

        self.files_d = self.get_target_files(None)
        self.all_files = frozenset(itertools.chain(*self.files_d.values()))
        tfs = [self.files_d[target] for target in self.files_d
               if target not in settings.target_vars]
        self.target_files = frozenset(itertools.chain(*tfs))
        assert (self.target_files == self.all_files)

        mlog.debug("{}: load {} kbuilds, {} config vars, "
                   "files: {} total, {} target".format(
            result_dir, len(self.kbuilds), len(self.config_vars),
            len(self.all_files), len(self.target_files)))

    def go(self, args):
        return None

    def check_src_dir(self, src_dir):
        """
        Obtain all C programs and check
        """
        assert os.path.isdir(src_dir)

        # get all src files from src_dir
        src_dir_len = len(src_dir)
        src_files = []

        for root, subdirs, files in os.walk(src_dir):
            # ignore .hidden dirs
            subdirs[:] = [d for d in subdirs if not d.startswith('.')]
            for f in files:
                if f.startswith('.'):  #ignore hidden
                    continue
                f_ = os.path.join(root, f)
                assert os.path.isfile(f_), "{}: not exist".format(f_)
                f = f_[src_dir_len:]
                src_files.append(f)

        assert(len(set(src_files)) == len(src_files))

        #remove files with no ext
        src_files = [f for f in src_files if os.path.splitext(f)[1]]

        #remove files in specific dirs

        old_len = len(src_files)
        src_files = frozenset(f for f, _ in src_files)
        assert old_len == len(src_files)


        target_files_noext = frozenset(os.path.splitext(f)[0] 
                                       for f in self.target_files)
        assert len(target_files_noext) == len(self.target_files)


        #test
        d = {}
        for f in src_files:
            d_ = os.path.splitext(f)[0]
            if d_ not in d:
                d[d_] = f
            else:
                print("{} , {}".format(f, d[d_]))

        src_files_noext = frozenset(os.path.splitext(f)[0]
                                        for f in src_files)
        assert len(src_files_noext) == len(src_files)



        compare_files(self.target_files, src_files,
                      "skanner", "src_dir")

    def get_target_files(self, constraint):
        assert constraint is None or z3.is_expr(constraint), constraint

        solver = zsolver.ZSolver() if z3.is_expr(constraint) else None

        files_d = {}
        for kbuild in self.kbuilds:
            tdir = os.path.split(kbuild.makefile)[0][self.commonpath_len:]
            if tdir.startswith('/'): tdir = tdir[1:]
            for path in kbuild.paths:
                if (constraint is None or
                        solver.is_valid(z3.Implies(constraint, path.cond))):
                    tfiles = path.target_files
                    assert all(isinstance(v, Var) for v in tfiles), tfiles
                    for v in tfiles:
                        files = [os.path.join(tdir, f) for f in v.vals]
                        if v.name not in files_d:
                            files_d[v.name] = []
                        files_d[v.name].extend(files)

        return files_d

    def check_target_files(self, config_file, make_log):
        assert config_file is None or os.path.isfile(config_file), config_file
        assert make_log is None or os.path.isfile(make_log), make_log

        config_files_notused = []
        config_files = []
        make_files = []
        if config_file:
            config_files_d = self.get_files_from_config(config_file)
            #print some stats
            ss = []
            ss_notused = []
            for target, tfiles in config_files_d.items():
                assert (len(tfiles) == len(set(tfiles)))

                if target in settings.target_vars: # ignore obj- and lib-
                    ss_notused.append("{} {}".format(target, len(tfiles)))
                    config_files_notused.extend(tfiles)
                else:
                    ss.append("{} {}".format(target, len(tfiles)))
                    config_files.extend(tfiles)

            config_files = frozenset(config_files)
            mlog.debug("config files {} ({})".format(len(config_files), ', '.join(ss)))
            config_files_notused = frozenset(config_files_notused)
            mlog.debug("config files (notused) {} ({})".format(
                len(config_files_notused), ', '.join(ss_notused)))

        if make_log:
            make_files = self.get_files_from_make_log(make_log)
            mlog.debug("make files {}".format(len(make_files)))

        compare_sets(config_files, make_files,
                     "config_files", "make_files")

    def get_files_from_config(self, config_file):
        contents = [l.split("=") for l in
                    CM.strip_contents(CM.iread(config_file))]

        myconfig = {}
        for s, v in contents:
            assert s not in myconfig
            try:
                myconfig[s] = self.COptD[v]
            except KeyError:
                assert s not in self.config_vars
                mlog.warn("ignore {} = {}".format(s, v))

        undef = self.COptD[settings.undef_val]
        for s in self.config_vars:
            if s not in myconfig:
                myconfig[s] = undef

        constraint = [z3.Const(s, self.COptTyp) == v for s, v
                      in myconfig.items()]
        constraint = z3.simplify(z3.And(*constraint))

        constraint_files = self.get_target_files(constraint)

        # mlog.debug(', '.join("{}={}".format(s, v) for s, v in contents))
        # mlog.debug("{} targets\n{}".format(
        #     len(constraint_files), '\n'.join("{} ({}) = {}".format(
        #         name, len(constraint_files[name]),
        #         ', '.join(constraint_files[name])) for name in constraint_files)))

        return constraint_files

    @staticmethod
    def file_stats(files_d):
        all_files = frozenset(itertools.chain(*files_d.values()))
        mlog.info("{} uniq files".format(len(all_files)))

        for target in files_d:
            assert len(files_d[target]) == len(set(files_d[target]))

            if target in settings.target_vars:  # ignore obj- , lib-
                continue

            mlog.info("{} ({})".format(target, len(files_d[target])))
            mlog.debug(', '.join(files_d[target]))

    @staticmethod
    def get_files_from_make_log(log_file):
        assert os.path.isfile(log_file), log_file

        ignores = frozenset("uidgid_get.o lib.a built-in.o applets.c common_bufsiz.h autoconf.h".split())

        def _parse(l):
            """
            set -e;  echo '  AR      archival/libarchive/lib.a'; rm -f archival/libarchive/lib.a; ar  rcs archival/libarchive/lib.a archival/libarchive/common.o; echo 'cmd_archival/libarchive/lib.a := rm -f archival/libarchive/lib.a; ar  rcs archival/libarchive/lib.a archival/libarchive/common.o' > archival/libarchive/.lib.a.cmd
            """
            ll = [p for p in l.split('echo')]  #[sed -d ; '  AR ... '   , ' .... long echo str...']
            ll = [p for p in ll if "'  " in p]  #'  AR
            ll = [p.split(';') for p in ll]
            ll = list(itertools.chain(*ll))
            ll = [p.strip() for p in ll if '.o' in p]
            ll = ' '.join(ll)
            ll = [p for p in ll.split() if ('.') in p]
            return ll

        contents = [l for l in
                    CM.strip_contents(CM.iread(log_file))]
        contents = [l for l in contents if 'echo' and '.o' in l]
        contents = [_parse(l) for l in contents]
        contents = [l for l in contents if l]
        contents = list(itertools.chain(*contents))
        # d = set()
        # for f in contents:
        #     if f not in d:
        #         d.add(f)
        #     else:
        #         print(f)
        # print(len(contents))
        # print(contents)

        contents = [p for p in contents if ',' not in p] # -Wp,-MD,applets/.applets.o.d  
        contents = [p for p in contents if not('"' in p and '=' in p)] # -D"BB_VER=KBUILD_STR(1.28.1)"
        contents = [p for p in contents if not os.path.split(p)[-1].startswith('.')]  # '/file/.hidden'
        contents = [p.replace('"','').replace("'",'') for p in contents]
        contents = [p for p in contents if os.path.splitext(p)[-1] != '.sh'] #
        contents = [p for p in contents if os.path.split(p)[-1] not in ignores]

        return frozenset(contents)


def load(result_dir):
    assert os.path.isdir(result_dir), result_dir
    kbuilds = [os.path.join(result_dir, f) for f in os.listdir(result_dir)]
    kbuilds = [Kbuild.load(f) for f in kbuilds]
    return kbuilds

def compare_files(A, B, A_str, B_str):
    """
    print diffs between sets A and B
    """
    if A and B:
        def _print_diffs(A, B, A_str, B_str):
            diffs  = A - B
            if not diffs:
                return
            mlog.info("in {}, but not in {}: {}".format(
                A_str, B_str, len(diffs)))

        mlog.debug("files: {} {}, {} {}".format(
            A_str, len(A), B_str, len(B)))
        pause()
        if A != B:
            _print_diffs(A, B, A_str, B_str)
            _print_diffs(B, A, B_str, A_str)
