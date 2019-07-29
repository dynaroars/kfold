from collections import namedtuple, OrderedDict
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

ZState = namedtuple("ZSTATE", "name states")
TriState = ZState(name="TRISTATE",
                  states=OrderedDict([
                      (y_str, y_str),
                      (m_str, m_str),
                      (undef_str, undef_val)]))
TwoState = ZState(name="TWOSTATE",
                  states=OrderedDict([
                      (y_str, y_str),
                      (undef_str, undef_val)]))


class CaseStudy:
    __zstate__ = TriState  # default

    __ignore_setvar_startswith__ = frozenset()
    __ignore_setvar_endswith__ = frozenset()
    __ignore_setvar_kws__ = frozenset()

    __ignore_dirs__ = frozenset()
    __ignore_exts__ = frozenset()

    __topdirs__ = []

    def __init__(self, path):
        """
        path is None => Analysis mode
        """
        assert path is None or isinstance(path, pathlib.Path), path
        self.path = path

    @property
    def makefile_paths(self):
        assert isinstance(self.path, pathlib.Path), pathlib

        try:
            return self._makefile_paths
        except AttributeError:
            if self.path.is_file():  # single makefile
                self._makefile_paths = [self.path]
            else:
                assert self.path.is_dir(), self.path

                path = self.path.resolve()
                topdirs = [path / d for d in self.__topdirs__]

                topdirs_ = []
                for d in topdirs:
                    if d.is_dir():
                        topdirs_.append(d)
                    else:
                        mlog.warn("ignore invalid dir '{}'".format(d))
                self._makefile_paths = topdirs_

            return self._makefile_paths

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
        elif case_study == 'busybox':
            return Busybox
        else:
            return Simple  # default

    # ANALYSIS
    def diff_files(src_files):
        assert isinstance(src_files, (set, frozenset)), src_files


class Simple(CaseStudy):
    __zstate__ = TwoState
    __topdirs__ = set([
        "main"
    ])


class Busybox(CaseStudy):
    __zstate__ = TwoState
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
    __zstate__ = TriState
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
