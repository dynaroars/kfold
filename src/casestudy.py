import os.path
import pdb
import pathlib
import vcommon as CM
import settings
mlog = CM.getLogger(__name__, settings.logger_level)

trace = pdb.set_trace
pause = CM.pause

y_str = "y"
m_str = "m"
undef_str = "undef"
undef_val = ''
TRISTATE = (undef_val, "TRISTATE", [y_str, m_str, undef_str],
            [y_str, m_str, undef_val])
TWOSTATE = (undef_val, "TWOSTATE", [y_str, undef_str], [y_str, undef_val])


class CaseStudy:
    __zstate__ = TWOSTATE  # default

    __ignore_setvar_startswith__ = frozenset()
    __ignore_setvar_endswith__ = frozenset()
    __ignore_setvar_kws__ = frozenset()

    __ignore_dirs__ = frozenset()
    __ignore_exts__ = frozenset()

    __topdirs__ = []

    def __init__(self, path):
        assert isinstance(path, pathlib.Path), path

        if path.is_file():  # single makefile
            self.makefile_paths = [path]
        else:
            assert path.is_dir(), path

            path = path.resolve()
            topdirs = [path / d for d in self.__topdirs__]

            topdirs_ = []
            for d in topdirs:
                if d.is_dir():
                    topdirs_.append(d)
                else:
                    mlog.warn('{} is invalid'.format(d))
            topdirs = topdirs_
            self.makefile_paths = topdirs

    def ignore_symbol(self, symbol):
        return (any(
            symbol.startswith(x)
            for x in self.__ignore_setvar_startswith__) or any(
                symbol.endswith(x) for x in self.__ignore_setvar_endswith__)
            or any(kw in symbol for kw in self.__ignore_setvar_kws__))

    def ignore_ext(self, filename):

        ignore_exts = frozenset.union(CaseStudy.__ignore_exts__,
                                      self.__ignore_exts__)
        return os.path.splitext(filename)[1] in ignore_exts

    @classmethod
    def get_case_study(cls, case_study):
        assert case_study is None or (isinstance(
            case_study, str) and case_study), case_study

        if case_study:
            case_study = case_study.lower()

        if case_study == 'linux':
            return Linux
        else:
            return Busybox  # default

    # ANALYSIS
    def diff_files(src_files):
        assert isinstance(src_files, (set, frozenset)), src_files


class Busybox(CaseStudy):
    __zstate__ = TWOSTATE
    __topdirs__ = set([
        "applets",
        "arch/",
        "archival/",
        "archival/libarchive/",
        "console-tools/",
        "coreutils/",
        "coreutils/libcoreutils/",
        "debianutils/",
        "klibc-utils/",
        "e2fsprogs/",
        "editors/",
        "findutils/",
        "init/",
        "klibc-utils/",
        "libbb/",
        "libpwdgrp/",
        "loginutils/",
        "mailutils/",
        "miscutils/",
        "modutils/",
        "networking/",
        "networking/libiproute/",
        "networking/udhcp/",
        "printutils/",
        "procps/",
        "runit/",
        "selinux/",
        "shell/",
        "sysklogd/",
        "util-linux/",
        "util-linux/volume_id/"
    ])

    env_vars = set(['srctree', 'objtree'])


class Linux(CaseStudy):
    __zstate__ = TRISTATE
    __topdirs__ = set([
        "arch/i386",
        "block",  # seems OK
        # "certs",  problem
        # "crypto",   seems ok
        # "drivers", seems OK
        # "firmware", problem FilterFunction not implemented
        # "fs", seems ok
        # "init", seems ok
        # "ipc", seems ok
        # "kernel", seems ok
        # "lib",   problem CallFunction not implemented
        # "mm",  seems OK
        # "net",  seems ok   warning about temp-y
        # "scripts", seems ok
        # "security", seems ok
        # "sound", seems ok
        # "tools",   no make file?
        # "usr",    File "/home/tnguyen/Dropbox/git/kbuild-scanner/src/alg.py", line 579, in eval_fake_expansion
        #    stmts[0], parserdata.EmptyDirective), stmts
        # AssertionError: SetVariable<None:1:18> Exp<None:1:0>('-DINITRAMFS_IMAGE') =
        # '"usr/$(datafile_y)"'
        # "virt"  no make file ?
    ])

    __ignore_setvar_starswith__ = frozenset([
        "AFLAGS",
        "CCVERSION",
        "filechk_ikconfiggz",
        'ccflags-y',
        'ramfs-input',  # TODO: automatically ignore these
        'ramfs-args'
    ])
    __ignore_setvar_endswith__ = frozenset(["extract_certs", "chk_compile.h"])
    __ignore_setvar_kws__ = frozenset(["CFLAGS", "_flag"])
