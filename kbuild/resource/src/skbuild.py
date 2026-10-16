#! /usr/bin/env python3
import pdb
from helpers.vcommon import getLogLevel, getLogger

DBG = pdb.set_trace


def is_analysis_mode(path):
    return (path.is_dir() and
            (any(f.is_file() and f.name == settings.RESULT_SINFO
                 for f in path.iterdir())))


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

    ag("--json", "-json",
       action="store_true",
       help="output analysis result and metrics as JSON")

    ag("--recursive", "-r",
       action="store_true",
       help="recursively find and analyze all Makefiles in directory")

    ag("--tristate", "-T",
       action="store_true",
       help="enable tristate (=y / =m) configuration option modeling")

    ag("--check-dead", "--lint",
       action="store_true",
       help="lint Makefiles for unreachable, orphaned, and unsatisfiable targets")

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

    if args.check_dead:
        from tools.lint_dead_targets import lint_dead_targets
        lint_res = lint_dead_targets(path, recursive=args.recursive, use_tristate=args.tristate)
        import json
        print(json.dumps(lint_res, indent=2))
        import sys
        sys.exit(0)

    if is_analysis_mode(path):
        from analysis import Analysis
        cls = Analysis(path)
        tmpdir = cls.go(args)

    else:
        from alg import Run
        cls = Run(path, recursive=args.recursive, use_tristate=args.tristate)
        tmpdir = cls.go()

    from census import GLOBAL_METRICS
    summary = GLOBAL_METRICS.summary()

    if args.json:
        import json
        from analysis import Analysis
        res_data = {
            "summary": summary,
            "target": str(path.resolve()),
        }
        kbuilds_list = getattr(cls, 'all_kbuilds', getattr(cls, 'kbuilds', []))
        main_dir = getattr(cls, 'maindir', getattr(cls, 'main_dir', path))
        mysettings = getattr(cls, 'mysettings', None)
        target_objects = {}

        units_by_type_agg = {
            "compilation_units": {},
            "composite_units": {},
            "composite_map": {},
            "hostprog_units": {},
            "dialect_units": {},
            "clean_files": {},
            "extra_targets": {},
            "unconfigurable_units": {},
            "subdirs": [],
        }

        for kbuild in kbuilds_list:
            state = kbuild.state
            parent = kbuild.makefile.parent
            solver = kbuild.solver
            kb_units = state.get_units_by_type(solver=solver)

            for v in state.target_files:
                if mysettings and v.name in mysettings.target_vars:
                    continue
                for word, wcond in v.valconds.items():
                    try:
                        rel = str((parent / word).relative_to(main_dir))
                    except ValueError:
                        rel = str(word)
                    target_objects[rel] = str(wcond)

            for k in ["compilation_units", "composite_units", "hostprog_units", "dialect_units", "clean_files", "extra_targets", "unconfigurable_units"]:
                for word, cond in kb_units[k].items():
                    try:
                        rel = str((parent / word).relative_to(main_dir))
                    except ValueError:
                        rel = str(word)
                    units_by_type_agg[k][rel] = str(cond)

            for comp, consts in kb_units["composite_map"].items():
                try:
                    rel_comp = str((parent / comp).relative_to(main_dir))
                except ValueError:
                    rel_comp = str(comp)
                units_by_type_agg["composite_map"][rel_comp] = {
                    str((parent / cw).relative_to(main_dir)) if not str(cw).startswith('/') else str(cw): str(cc)
                    for cw, cc in consts.items()
                }

            for sd in kb_units["subdirs"]:
                try:
                    rel_sd = str((parent / sd).relative_to(main_dir))
                except ValueError:
                    rel_sd = str(sd)
                if rel_sd not in units_by_type_agg["subdirs"]:
                    units_by_type_agg["subdirs"].append(rel_sd)

        res_data["predictions_count"] = len(target_objects)
        res_data["predictions"] = target_objects
        res_data["units_by_type"] = units_by_type_agg
        print(json.dumps(res_data, indent=2))

    if tmpdir and tmpdir.is_dir():
        if args.rmtmp:
            import shutil
            mlog.debug("rm -rf {}".format(tmpdir))
            shutil.rmtree(tmpdir)
        elif not args.json:
            print("tmpdir: {}".format(tmpdir))
