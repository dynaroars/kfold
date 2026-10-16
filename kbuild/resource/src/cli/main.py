"""kfold: variability-aware answers about a Kbuild tree.

Subcommands are the modules of ``cli.commands`` (see its docstring); they
are discovered at startup, so new commands need no change here.
"""
import argparse
import importlib
import os
import pkgutil
import sys

import cli  # noqa: F401  (sets up sys.path)
from cli import commands, common


def discover():
    """[(name, module)] of cli.commands modules defining register()."""
    found = []
    for info in sorted(pkgutil.iter_modules(commands.__path__), key=lambda i: i.name):
        if info.name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"{commands.__name__}.{info.name}")
        except Exception as e:  # one broken command must not disable the rest
            if os.environ.get("KFOLD_DEBUG"):
                raise
            common.warn(f"skipping command module {info.name}: {type(e).__name__}: {e}")
            continue
        if callable(getattr(mod, "register", None)):
            found.append((info.name, mod))
    return found


def build_parser():
    parser = argparse.ArgumentParser(
        prog="kfold", description="Variability-aware Kbuild analysis for kernel developers.")
    parser.add_argument("--log-level", type=int, default=1, metavar="0-4",
                        help="analyzer log level (0 critical .. 4 debug; default 1)")
    parser.add_argument("--cache-dir", metavar="DIR", default=None,
                        help="cache root (default: $KFOLD_CACHE or ~/.cache/kfold)")
    parser.add_argument("--no-analyze", action="store_true",
                        help="fail instead of analyzing when the cache is missing or stale")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    for name, mod in discover():
        before = set(sub.choices)
        try:
            mod.register(sub)
        except Exception as e:
            if os.environ.get("KFOLD_DEBUG"):
                raise
            common.warn(f"skipping command module {name}: register failed: {e}")
            continue
        # Global options are accepted after the subcommand too.
        for cname in set(sub.choices) - before:
            p = sub.choices[cname]
            have = {o for a in p._actions for o in a.option_strings}
            if "--cache-dir" not in have and "--no-analyze" not in have:
                common.add_cache_options(p)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    common.configure_logging(args.log_level)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 2
    try:
        rc = func(args)
    except common.CLIError as e:
        common.warn(str(e))
        return e.code
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        try:
            sys.stdout = open(os.devnull, "w")
        except OSError:
            pass
        return 0
    return 0 if rc is None else int(rc)


if __name__ == "__main__":
    sys.exit(main())
