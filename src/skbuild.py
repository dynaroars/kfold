#! /usr/bin/env python3
import pdb
from helpers.vcommon import getLogLevel, getLogger

DBG = pdb.set_trace


if __name__ == '__main__':

    import argparse
    aparser = argparse.ArgumentParser(
        "Find interactions from Kbuild Makefiles")
    ag = aparser.add_argument
    ag('path',
       type=str,
       help="""path to Linux Makefile or dirs""")

    ag("--log_level", "-log_level",
       help="set logger info",
       type=int,
       choices=range(5),
       default=3)

    ag("--rmtmp", "-rmtmp",
       action="store_true",
       help="remove saveds result")

    ag("--detail", "-detail",
       action="store_true",
       help="lots of debug detail")

    ag("--nomp", "-nomp",
       action="store_true",
       help="don't use multiprocessing")

    # Analysis Option
    ag("--build_dir", "-build_dir",
       type=str,
       help="dir consisting files built from a full config file")

    ag("--make_log", "-make_log",
       type=str,
       help="analyze make log (make -n)")

    ag("--src_dir", "-src_dir",
       type=str,
       help="full src dir (to check coverage)")

    args = aparser.parse_args()

    import settings
    settings.doMP = not args.nomp
    settings.detail = args.detail

    if (args.log_level != settings.logger_level and
            0 <= args.log_level <= 4):
        settings.logger_level = args.log_level

    settings.logger_level = getLogLevel(settings.logger_level)
    mlog = getLogger(__name__, settings.logger_level)
    if __debug__:
        mlog.info("DEBUG MODE ON. Use python -O to optimize")

    import pathlib
    path = pathlib.Path(args.path)
    assert path.is_file() or path.is_dir(), path

    from alg import Run
    tmpdir = Run.doit(path, args)

    # mode = Run.check_path(path)
    # if mode is None:
    #     cls = Run(path)
    #     tmpdir = cls.go(args)
    # else:
    #     from analysis import Analysis
    #     cls = Analysis(path)
    #     tmpdir = cls.go(args)

    if tmpdir and tmpdir.is_dir():
        if args.rmtmp:
            import shutil
            mlog.debug("rm -rf {}".format(tmpdir))
            shutil.rmtree(tmpdir)
        else:
            print("tmpdir: {}".format(tmpdir))
