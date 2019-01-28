#! /usr/bin/env python
from vcommon import getLogLevel, getLogger
import vcommon as CM
import os.path


class CaseStudy:
    def __init__(self, topdir):
        self.topdir = os.path.abspath(topdir)

    def go(self):
        dirs = self.get_makefile_dirs()
        import alg
        myrun = alg.Run(dirs)
        myrun.go()

    def get_makefile_dirs(self):
        dirs = [os.path.join(self.topdir, d) for d in self.__topdirs__]
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
    __ignores__ = []


class Linux(CaseStudy):
    __topdirs__ = [
        "arch/i386",
        # "block", seems OK
        # "certs",  problem
        # "crypto",   problem
        # "drivers", seems OK
        # "firmware", problem FilterFunction not implemented
        # "fs", seems ok
        # "init", problem .s
        # "ipc", seems ok
        # "kernel", problem .s
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

    ag('--case-study',
       type=str,
       help="""avail options: busybox, linux, fromfile""")

    args = aparser.parse_args()

    import settings
    if args.log_level != settings.logger_level and 0 <= args.log_level <= 4:
        settings.logger_level = args.log_level

    settings.logger_level = getLogLevel(settings.logger_level)
    mlog = getLogger(__name__, settings.logger_level)
    if __debug__:
        mlog.info("DEBUG MODE ON. Can be slow! (Use python -O to optimize)")
    makefile_paths = args.paths

    case_study = args.case_study
    if case_study:
        case_study = case_study.lower()
        makefile_path = makefile_paths[0]
        if case_study == "busybox":
            cls = BusyBox
        elif case_study == "linux":
            cls = Linux
        else:
            raise NotImplementedError(case_study)

        case_study = cls(makefile_path)
        case_study.go()
    else:
        import alg
        myrun = alg.Run(makefile_paths)
        myrun.go()

    # if case_study == "alldirs":
    #     path = args.paths[0]
    #     paths = [os.path.join(path, sdir) for sdir in os.listdir(path)]
    #     paths = [p for p in paths if os.path.isdir(p)]
    # elif case_study == "fromfile":
    #     def _f(l):
    #         parts = l.split()
    #         if (not parts[0].startswith("#") and
    #             len(parts) > 1 and parts[1].startswith('/') and
    #             all(x not in parts[1] for x in set([
    #                 '/tools/'
    #                 '/arch/arm/', '/arch/arm64/',
    #                 '/arch/sh', '/arch/s390']))):
    #             # 'Kbuild' in parts[1]):
    #             return parts[1]
    #         else:
    #             return None

    #     path = args.paths[0]
    #     paths = [_f(l) for l in CM.iread(path)]
    #     paths = [p for p in paths if p]


# exploit 1
# paths in makefiles have many same state contents, so can merge .  e.g.,  x$y  = ...  ,  2 diff paths but same state.
