"""Helpers shared by kfold subcommands: tree and cache resolution, loading
the cached analysis, .config loading, object-name normalization, condition
formatting, and text/JSON output."""
import difflib
import json
import logging
import os
import pathlib
import sys

import z3

import cli  # noqa: F401  (sets up sys.path)


class CLIError(Exception):
    """An error reported to the user as ``kfold: <message>`` with ``code``."""

    def __init__(self, message, code=2):
        super().__init__(message)
        self.code = code


def warn(msg):
    print(f"kfold: {msg}", file=sys.stderr)


# ---------------------------------------------------------------- logging

def configure_logging(level):
    """Analyzer log level 0..4 (critical..debug). Must run before the
    analyzer's modules are imported to fully take effect; loggers already
    created are adjusted too."""
    import settings
    from helpers import vcommon
    lvl = vcommon.getLogLevel(max(0, min(4, level)))
    settings.logger_level = lvl
    for logger in logging.root.manager.loggerDict.values():
        if isinstance(logger, logging.Logger):
            for h in logger.handlers:
                h.setLevel(lvl)


# ---------------------------------------------------------------- arguments

def add_tree_option(parser):
    parser.add_argument("--tree", "-C", metavar="TREE", default=None,
                        help="kernel/source tree (default: the nearest directory at or "
                             "above the current one with skbuild.ini, else the current one)")


def add_config_option(parser, required=False):
    parser.add_argument("--config", "-c", metavar=".config", default=None, required=required,
                        help="evaluate under this .config")


def add_json_option(parser):
    parser.add_argument("--json", action="store_true", help="machine-readable JSON output")


def add_cache_options(parser):
    """--cache-dir and --no-analyze; main adds these to every subcommand, so
    commands need not."""
    parser.add_argument("--cache-dir", metavar="DIR", default=argparse_suppress(),
                        help="cache root (default: $KFOLD_CACHE or ~/.cache/kfold)")
    parser.add_argument("--no-analyze", action="store_true", default=argparse_suppress(),
                        help="fail instead of analyzing when the cache is missing or stale")


def argparse_suppress():
    import argparse
    return argparse.SUPPRESS


# ---------------------------------------------------------------- tree/cache

def resolve_tree(tree=None, hint=None):
    """The tree to analyze: ``tree`` if given; else, searching upward from
    ``hint`` (e.g. a file argument) and then from the current directory, the
    nearest directory holding skbuild.ini, else the topmost directory of a
    contiguous run of ancestors holding both Kconfig and a Makefile; else the
    current directory. Raises CLIError if the result has no Makefile/Kbuild."""
    if tree:
        p = pathlib.Path(tree).expanduser()
        if not p.exists():
            raise CLIError(f"{tree}: no such tree")
        p = p.resolve()
        return p.parent if p.is_file() else p
    cwd = pathlib.Path.cwd().resolve()
    starts = []
    if hint:
        h = pathlib.Path(hint).expanduser()
        h = (h if h.is_absolute() else cwd / h).resolve()
        starts.append(h if h.is_dir() else h.parent)
    starts.append(cwd)
    for start in starts:
        for d in (start, *start.parents):
            if (d / "skbuild.ini").is_file():
                return d
    for start in starts:
        top = None
        for d in (start, *start.parents):
            if (d / "Kconfig").is_file() and (d / "Makefile").is_file():
                top = d
            elif top is not None:
                break
        if top is not None:
            return top
    if not any((cwd / f).is_file() for f in ("Makefile", "Kbuild", "Makefile.inc")):
        raise CLIError(f"{cwd} has no Makefile or Kbuild file; pass --tree")
    return cwd


def cache_root(args=None):
    from cli import cache
    d = getattr(args, "cache_dir", None) if args is not None else None
    return pathlib.Path(d).expanduser() if d else cache.default_cache_root()


def get_analysis(args, tree=None, hint=None):
    """The cached Analysis for ``args.tree`` (or ``tree``; ``hint`` is a
    path argument used to locate the tree when neither is given), analyzing
    first if the cache is missing or stale unless --no-analyze."""
    from cli import cache
    t = resolve_tree(tree if tree is not None else getattr(args, "tree", None), hint)
    try:
        return cache.load_or_analyze(t, cache_root(args),
                                     auto=not getattr(args, "no_analyze", False), log=warn)
    except cache.CacheError as e:
        raise CLIError(str(e))


def load_config(path):
    """{CONFIG_X: value} of a .config (``objects.config_values``)."""
    from objects import config_values
    p = pathlib.Path(path).expanduser()
    if not p.is_file():
        raise CLIError(f"{path}: no such .config")
    return config_values(p)


def config_value(values, sym):
    """A symbol's value as kfold's analysis sees it: y, m, or n (unset)."""
    v = values.get(sym, "")
    return v if v else "n"


# ---------------------------------------------------------------- objects

def object_path(analysis, name, cwd=None):
    """Normalize a user-supplied object name to a key of ``analysis.conds``:
    accepts tree-relative or cwd-relative or absolute paths, and .c/.S/.s
    sources (mapped to .o). Raises CLIError with suggestions if unknown."""
    cands = []
    p = pathlib.Path(name).expanduser()
    tree = analysis.tree
    bases = [p] if p.is_absolute() else [pathlib.Path(cwd or os.getcwd()) / p, tree / p]
    for b in bases:
        try:
            cands.append(str(pathlib.Path(os.path.normpath(b.absolute())).relative_to(tree)))
        except ValueError:
            pass
    if not p.is_absolute():
        cands.append(os.path.normpath(name))
    for c in cands:
        stem, ext = os.path.splitext(c)
        for k in (c, stem + ".o") if ext in (".c", ".S", ".s", ".C", "") else (c,):
            if k in analysis.conds:
                return k
    close = difflib.get_close_matches(cands[0] if cands else name, list(analysis.conds), n=5)
    hint = ("; did you mean: " + ", ".join(close)) if close else ""
    raise CLIError(f"{name}: not an object kfold knows in {tree}{hint}", code=1)


# ---------------------------------------------------------------- formatting

def _atom(e):
    """(symbol, value) for ``CONFIG_X == v`` atoms, else None."""
    if z3.is_eq(e) and e.num_args() == 2:
        a, b = e.arg(0), e.arg(1)
        if z3.is_const(b) and b.decl().kind() == z3.Z3_OP_UNINTERPRETED:
            a, b = b, a
        if (z3.is_const(a) and a.decl().kind() == z3.Z3_OP_UNINTERPRETED
                and z3.is_const(b)):
            v = str(b)
            return str(a), ("n" if v == "undef" else v)
    return None


def format_cond(e, max_len=None):
    """Readable condition: ``CONFIG_X=y``, ``CONFIG_X=y|m``, ``CONFIG_X=n``
    (unset), with ``!``, ``&&``, ``||``. Truncated to ``max_len`` chars."""
    if not isinstance(e, z3.ExprRef):
        e = z3.BoolVal(bool(e))
    memo = {}

    def go(n, prec):
        key = (n.get_id(), prec)
        if key in memo:
            return memo[key]
        if z3.is_true(n):
            s = "true"
        elif z3.is_false(n):
            s = "false"
        elif _atom(n):
            sym, v = _atom(n)
            s = f"{sym}={v}"
        elif z3.is_not(n):
            a = _atom(n.arg(0))
            s = f"{a[0]}!={a[1]}" if a else "!" + go(n.arg(0), 3)
        elif z3.is_and(n) or z3.is_or(n):
            is_and = z3.is_and(n)
            parts = []
            if not is_and:
                # CONFIG_X=y || CONFIG_X=m  ->  CONFIG_X=y|m
                grouped, order = {}, []
                for c in n.children():
                    a = _atom(c)
                    if a:
                        if a[0] not in grouped:
                            grouped[a[0]] = []
                            order.append(("sym", a[0]))
                        grouped[a[0]].append(a[1])
                    else:
                        order.append(("expr", c))
                for kind, x in order:
                    parts.append(f"{x}={'|'.join(grouped[x])}" if kind == "sym" else go(x, 1))
            else:
                parts = [go(c, 2) for c in n.children()]
            s = (" && " if is_and else " || ").join(parts)
            if len(parts) > 1 and prec > 0:
                s = f"({s})"
        else:
            s = str(n).replace("\n", " ")
        memo[key] = s
        return s
    s = go(e, 0)
    if max_len and len(s) > max_len:
        s = s[:max_len - 3] + "..."
    return s


def simplify_cond(e):
    """An equivalent, usually much smaller, form of a condition."""
    return z3.Then("propagate-values", "ctx-simplify", "ctx-solver-simplify",
                   "simplify")(e).as_expr()


def display_cond(e, simplify=True, max_len=None, limit=20000):
    """``format_cond`` of ``e``, first simplified with Z3 (propagate-values,
    ctx-simplify, ctx-solver-simplify: equivalent, shorter) when ``simplify``
    and ``e`` is not huge (``limit`` characters of SMT-LIB)."""
    if simplify and isinstance(e, z3.ExprRef) and len(e.sexpr()) <= limit:
        try:
            e = simplify_cond(e)
        except z3.Z3Exception:
            pass
    return format_cond(e, max_len)


def emit(args, data, text=None):
    """Print ``data`` as JSON with --json, else ``text`` (a string, or a
    callable taking ``data`` and returning one)."""
    if getattr(args, "json", False):
        json.dump(data, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        out = text(data) if callable(text) else (text if text is not None else
                                                  json.dumps(data, indent=2, default=str))
        if out:
            print(out)
