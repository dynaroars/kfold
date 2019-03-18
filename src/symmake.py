#! /usr/bin/env python3
from vcommon import getLogLevel, getLogger
import vcommon as CM
import os.path


class CaseStudy:
    def __init__(self, topdir, settings):
        self.topdir = os.path.abspath(topdir)
        self.settings = settings

    def go(self):
        dirs = self.get_makefile_dirs()
        import alg
        myrun = alg.Run(dirs)
        return myrun.go()

    def get_makefile_dirs(self):
        dirs = [os.path.join(self.topdir, d) for d in
                self.__topdirs__]
        dirs = [d for d in dirs if os.path.isdir(d)]
        return dirs


class BusyBox(CaseStudy):
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
    __topdirs__ = [
        "arch/i386",
        # "block", seems OK
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

    __ignore_setvar_starswith__ = set([
        "AFLAGS",
        "CCVERSION",
        "filechk_ikconfiggz",
        'ccflags-y',
        'ramfs-input',  # TODO: automatically ignore these
        'ramfs-args'
    ])
    __ignore_setvar_endswith__ = set([
        "extract_certs",
        "chk_compile.h"
    ])
    __ignore_setvar_kws__ = set([
        "CFLAGS",
        "_flag"]
    )


if __name__ == '__main__':

    import argparse
    aparser = argparse.ArgumentParser(
        "Find interactions from Kbuild Makefiles")
    ag = aparser.add_argument
    ag('paths',
       nargs="*",
       type=str,
       help="""paths to Linux Makefiles or dirs""")

    ag("--log_level", "-log_level",
       help="set logger info",
       type=int,
       choices=range(5),
       default=3)

    ag("--tristate", "-tristate",
       action="store_true",
       help="use tristate")

    ag('--case-study',
       type=str,
       help="""avail options: busybox, linux, fromfile""")

    ag("--rmtmp", "-rmtmp",
       action="store_true",
       help="remove saveds result")

    # analysis
    ag("--config_file", "-config_file",
       type=str,
       help="full config file")

    ag("--make_log", "-make_log",
       type=str,
       help="analyze make log (make -n)")

    args = aparser.parse_args()

    import settings
    if args.log_level != settings.logger_level and 0 <= args.log_level <= 4:
        settings.logger_level = args.log_level

    settings.logger_level = getLogLevel(settings.logger_level)
    mlog = getLogger(__name__, settings.logger_level)
    if __debug__:
        mlog.info("DEBUG MODE ON. Can be slow! (Use python -O to optimize)")
    makefile_paths = args.paths
    assert makefile_paths

    if (len(makefile_paths) == 1 and
        os.path.isdir(makefile_paths[0]) and
        any(f.endswith(settings.results_ext) for
            f in os.listdir(makefile_paths[0]))):
        from analysis import Analysis
        analysis = Analysis(makefile_paths[0])
        analysis.check_target_files(args.config_file, args.make_log)
        exit(0)

    case_study = args.case_study
    if case_study:
        case_study = case_study.lower()
        makefile_path = makefile_paths[0]
        if case_study == "busybox":
            cls = BusyBox
            settings.zstate = settings.twostate
        elif case_study == "linux":
            cls = Linux
            settings.zstate = settings.tristate
        else:
            raise NotImplementedError(case_study)

        cls = cls(makefile_path, settings)
    else:
        settings.ignore_setvar_startswith = Linux.__ignore_setvar_starswith__
        settings.ignore_setvar_endswith = Linux.__ignore_setvar_endswith__
        settings.ignore_setvar_kws = Linux.__ignore_setvar_kws__

        if args.tristate:
            settings.zstate = settings.tristate
            
        import alg
        cls = alg.Run(makefile_paths)

    tmpdir = cls.go()

    if args.rmtmp:
        import shutil
        mlog.debug("rm -rf {}".format(tmpdir))
        shutil.rmtree(tmpdir)
    else:
        print("tmpdir: {}".format(tmpdir))


# exploit
# paths in makefiles have many same state contents, so can merge .  e.g.,  x$y  = ...  ,  2 diff paths but same state.
