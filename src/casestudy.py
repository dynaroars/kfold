import os.path
import settings
import vcommon as CM
mlog = CM.getLogger(__name__, settings.logger_level)

class CaseStudy:
    __zstate__ = settings.twostate

    __ignore_setvar_startswith__ = frozenset()
    __ignore_setvar_endswith__ = frozenset()
    __ignore_setvar_kws__ = frozenset()

    __ignore_dirs__ = frozenset()
    __ignore_exts__ = frozenset()

    __topdirs__ = []

    def __init__(self, path):
        if os.path.isfile(path): # single makefile
            self.makefile_paths = [path]
        else:
            assert os.path.isdir(path)
            path = os.path.abspath(path)
            topdirs = [os.path.join(path, d) for d in
                       self.__topdirs__]
            topdirs = [d for d in topdirs if os.path.isdir(d)]
            self.makefile_paths = topdirs

        mlog.info("using settings of {}".format(self.__class__.__name__))

        settings.zstate = self.__zstate__
        settings.ignore_setvar_startswith = self.__ignore_setvar_startswith__
        settings.ignore_setvar_endswith =  self.__ignore_setvar_endswith__
        settings.ignore_setvar_kws = self.__ignore_setvar_kws__
        settings.ignore_dirs = self.__ignore_dirs__
        settings.ignore_exts = self.__ignore_exts__

class Busybox(CaseStudy):
    __zstate__ = settings.twostate
    __ignore_dirs__ = frozenset("hush_test".split())
    __ignore_exts__ = frozenset(".src".split())
    __topdirs__ = ["applets/",
                   "arch/",
                   "archival/",
                   "console-tools/",
                   "coreutils/",
                   "debianutils/",
                   "e2fsprogs/",
                   "editors/",
                   "findutils/",
                   "init/",
                   "klibc-utils/",
                   "libbb/",
                   "libpwdgrp/"
                   "loginutils/",
                   "mailutils/",
                   "miscutils/",
                   "modutils/",
                   "networking/",
                   "printutils/",
                   "procps/",
                   "runit/",
                   "scripts/",
                   "selinux/",
                   "shell/",
                   "sysklogd/",
                   "util-linux/"]

class Linux(CaseStudy):
    __zstate__ = settings.tristate
    __topdirs__ = [
        "arch/i386",
        "block", # seems OK
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
    ]

    __ignore_setvar_starswith__ = frozenset([
        "AFLAGS",
        "CCVERSION",
        "filechk_ikconfiggz",
        'ccflags-y',
        'ramfs-input',  # TODO: automatically ignore these
        'ramfs-args'
    ])
    __ignore_setvar_endswith__ = frozenset([
        "extract_certs",
        "chk_compile.h"
    ])
    __ignore_setvar_kws__ = frozenset([
        "CFLAGS",
        "_flag"]
    )


