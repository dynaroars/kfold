#! /usr/bin/env python3
from helpers.vcommon import getLogLevel, getLogger
import pathlib


def is_analysis_mode(path):
    return (path.is_dir() and
            any(f.is_file() and f.suffix == settings.RESULT_EXT
                for f in path.iterdir()))


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

    ag("--case-study", "-case-study",
       type=str,
       help="avail options: busybox, linux, fromfile")

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
    ag("--config_file", "-config_file",
       type=str,
       help="full config file")

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

    path = pathlib.Path(args.path)
    assert path

    if is_analysis_mode(path):
        from analysis import Analysis
        cls = Analysis(path)
        tmpdir = cls.go(args)

    else:
        from casestudy import CaseStudy
        cls = CaseStudy.get_case_study(args.case_study)
        cls = cls(path)
        from alg import Run
        cls = Run(cls.makefile_paths, cls)
        tmpdir = cls.go()

    if tmpdir and tmpdir.is_dir():
        if args.rmtmp:
            import shutil
            mlog.debug("rm -rf {}".format(tmpdir))
            shutil.rmtree(tmpdir)
        else:
            print("tmpdir: {}".format(tmpdir))
