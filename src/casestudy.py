import os.path
import settings
import pdb

import vcommon as CM

trace = pdb.set_trace
pause = CM.pause

y_str = "y"
m_str = "m"
undef_str = "undef"
undef_val = ''
tristate = (undef_val, "TriState", [y_str, m_str, undef_str],
            [y_str, m_str, undef_val])
twostate = (undef_val, "TwoState", [y_str, undef_str], [y_str, undef_val])


class CaseStudy:
    __zstate__ = twostate

    __ignore_setvar_startswith__ = frozenset()
    __ignore_setvar_endswith__ = frozenset()
    __ignore_setvar_kws__ = frozenset()

    __ignore_dirs__ = frozenset()
    __ignore_exts__ = frozenset()

    __topdirs__ = []

    def __init__(self, path):
        # path is None is for analysis only
        if path:
            if os.path.isfile(path):  # single makefile
                self.makefile_paths = [path]
            else:
                assert os.path.isdir(path)
                path = os.path.abspath(path)
                topdirs = [os.path.join(path, d) for d in self.__topdirs__]
                topdirs = [d for d in topdirs if os.path.isdir(d)]
                self.makefile_paths = topdirs

    @property
    def topdirs(self):
        td = set([d if d.endswith(os.path.sep) else d + os.path.sep
                  for d in self.__topdirs__])
        return td

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

    # analysis

    def diff_files(src_files):
        assert isinstance(src_files, (set, frozenset)), src_files


class Busybox(CaseStudy):
    __zstate__ = twostate
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


class Linux(CaseStudy):
    __zstate__ = tristate
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
