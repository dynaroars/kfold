"""kfold lint: checkpatch-style checks for a Kbuild tree, from the cached
analysis.

Checks (each finding: class, file[:line], message, severity):

1. zombie   -- CONFIG_X referenced in an analyzed Makefile/Kbuild condition
               with no Kconfig declaration in scope for --arch (a symbol
               declared only for another arch is reported separately,
               severity "info", as arch_only rather than a zombie error).
2. orphan   -- .c/.S files on disk that no Makefile builds (composite
               members, implicit %.o<-%.c/%.S rules, and #include "x.c"
               glue are all accounted for; see _lint_sources.py).
3. dead     -- objects whose Kbuild condition alone is unsatisfiable
               ("kbuild"), or whose Kbuild condition conjoined with the
               tree's Kconfig constraints (tools/kconfig_solver.KconfigSMT)
               is unsatisfiable ("kconfig"); marked incomplete when a
               referenced symbol did not parse into a Kconfig symbol, since
               that could be an analysis gap rather than genuine dead code.

``--diff PATCH`` instead applies a patch to a scratch copy of the tree (never
the tree itself), prints the before/after condition of every object whose
Makefile/Kconfig hunks changed, added, or removed it, and runs checks 1-3
restricted to what the patch touches.
"""
import collections
import pathlib
import re

import z3

from cli import common
from cli.commands import _lint_diff, _lint_kconfig, _lint_sources

_WORD_CACHE = {}


def register(subparsers):
    p = subparsers.add_parser("lint", help="checkpatch-style lint for Kbuild Makefiles/Kconfig",
                              description=__doc__,
                              formatter_class=__import__("argparse").RawDescriptionHelpFormatter)
    common.add_tree_option(p)
    common.add_json_option(p)
    p.add_argument("--diff", metavar="PATCH",
                   help="lint only what PATCH changes: apply it to a scratch copy under "
                        "/tmp and diff conditions / run checks 1-3 against the current tree")
    p.add_argument("--only", choices=["zombie", "orphan", "dead"], action="append",
                   help="restrict to this finding class (repeatable)")
    p.add_argument("--path", metavar="PREFIX", default=None,
                   help="restrict findings to tree-relative paths starting with PREFIX")
    p.add_argument("--arch", default="x86",
                   help="the arch the tree was analyzed for (default: x86); symbols declared "
                        "only for a different arch are reported as arch-only, not zombies")
    p.add_argument("--kconfig", metavar="FILE", default="Kconfig",
                   help="top Kconfig file, relative to the tree (default: Kconfig)")
    p.add_argument("--scratch", metavar="DIR", default=None,
                   help="scratch directory for --diff (default: a fresh dir under /tmp)")
    p.add_argument("--dead-limit", type=int, default=None,
                   help="check at most this many objects for the dead-object check "
                        "(default: all); useful to bound a slow whole-tree run")
    p.set_defaults(func=run)


def run(args):
    a = common.get_analysis(args)
    only = set(args.only) if args.only else None
    if args.diff:
        data = _lint_diff.run(a, args, a.tree)
    else:
        data = run_whole_tree(a, a.tree, only=only, path_prefix=args.path,
                              kconfig_rel=args.kconfig, arch=args.arch,
                              dead_limit=args.dead_limit)
    common.emit(args, data, _text)
    return 0


# ---------------------------------------------------------------- check 1

def _word_re(sym):
    r = _WORD_CACHE.get(sym)
    if r is None:
        r = _WORD_CACHE[sym] = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(sym) + r"(?![A-Za-z0-9_])")
    return r


def _locate_symbol(tree, sym, objs, analysis, extra_files=(), cap=3):
    """Up to ``cap`` (file, line, text) occurrences of ``sym`` in the
    Makefiles that the objects referencing it came from (so we grep only the
    handful of files a zombie symbol actually appears in, not the tree)."""
    files = list(extra_files)
    for o in list(objs)[:8]:
        for mk, _via in analysis.origins.get(o, []):
            if mk not in files:
                files.append(mk)
    pat = _word_re(sym)
    out = []
    for mk in files:
        p = tree / mk
        try:
            lines = p.read_text(errors="ignore").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            if pat.search(line):
                out.append((mk, i, line.strip()))
                if len(out) >= cap:
                    return out
    return out or [(files[0] if files else "?", None, "")]


def _reached_symbols(analysis, table, path_prefix=None):
    """{symbol: {Makefile paths}} from a LazyConds table of directory-reach
    conditions (``analysis.reached``/``analysis.builtin``): these carry
    CONFIG_ guards on ``obj-$(CONFIG_X) += subdir/`` lines that gate whether
    a directory is visited at all, which is not tied to any one object's own
    condition (object_conditions folds them in per-object too, but scanning
    this table directly also catches purely-directory guards for a
    Makefile with no objects of its own, e.g. one that only recurses
    further)."""
    from z3.z3util import get_vars
    out = collections.defaultdict(set)
    for mk in table:
        if path_prefix and not mk.startswith(path_prefix):
            continue
        cond = table[mk]
        if not isinstance(cond, z3.ExprRef):
            continue
        for v in get_vars(cond):
            name = str(v)
            if name.startswith("CONFIG_"):
                out[name].add(mk)
    return out


def zombie_check(analysis, tree, path_prefix=None, arch="x86"):
    declared = _lint_kconfig.declared_symbols(tree)
    refs = collections.defaultdict(set)
    for p in analysis.conds:
        if path_prefix and not p.startswith(path_prefix):
            continue
        for s in analysis.symbols(p):
            refs[s].add(p)
    reached_via = _reached_symbols(analysis, analysis.reached, path_prefix)
    for sym, mks in _reached_symbols(analysis, analysis.builtin, path_prefix).items():
        reached_via[sym] |= mks
    findings = []
    for sym in sorted(set(refs) | set(reached_via)):
        objs = refs.get(sym, set())
        arches = declared.get(sym)
        if arches is not None and _lint_kconfig.is_in_scope(arches, arch):
            continue
        arch_only = arches is not None and bool(arches - {None})
        for f, line, _snippet in _locate_symbol(tree, sym, objs, analysis,
                                                extra_files=sorted(reached_via.get(sym, ()))):
            msg = f"{sym} is used in Kbuild but not declared in Kconfig"
            if arch_only:
                msg += f" for {arch} (declared only for {sorted(arches - {None})})"
            findings.append({
                "class": "zombie", "kind": "guard", "symbol": sym, "file": f, "line": line,
                "message": msg, "severity": "info" if arch_only else "error",
                "arch_only": arch_only, "example_objects": sorted(objs)[:3],
            })
    findings += _hardcoded_define_check(analysis, tree, declared, path_prefix=path_prefix, arch=arch)
    return findings


# Matches a literal "-DCONFIG_X" (and "-DCONFIG_X=value") compiler flag, e.g.
# "ccflags-y += -DCONFIG_CAAM_QI" or "CFLAGS_foo.o := -DCONFIG_X=y": a symbol
# baked directly into the flags rather than expanded from $(CONFIG_X). Such a
# flag is present in every build regardless of any .config, so any "#ifdef
# CONFIG_X" it feeds in the source is not actually configurable -- and if
# CONFIG_X is not even a real Kconfig symbol, it is Kbuild-only (kfold's
# per-object condition machinery never sees it, since it is never a make
# variable expansion), which is why the guard-based scan above alone found
# zero true zombies on Linux v6.6 even though upstream's own
# scripts/checkkconfigsymbols.py flags several of exactly this shape (e.g.
# CONFIG_CAAM_QI, CONFIG_FORCE_HARD_FLOAT, CONFIG_NCR53C8XX_PREFETCH).
_HARDCODED_DEFINE_RE = re.compile(r"-D(?!\$\()(CONFIG_[A-Za-z0-9_]+)")


def _hardcoded_define_check(analysis, tree, declared, path_prefix=None, arch="x86"):
    findings = []
    seen = set()
    for mk in sorted(set(analysis.reached) | set(analysis.builtin)):
        if path_prefix and not mk.startswith(path_prefix):
            continue
        p = tree / mk
        try:
            lines = p.read_text(errors="ignore").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            for m in _HARDCODED_DEFINE_RE.finditer(line):
                sym = m.group(1)
                if (sym, mk, i) in seen:
                    continue
                seen.add((sym, mk, i))
                arches = declared.get(sym)
                if arches is not None and _lint_kconfig.is_in_scope(arches, arch):
                    continue
                arch_only = arches is not None and bool(arches - {None})
                msg = (f"{sym} is hardcoded as a compiler -D flag in {mk}:{i} (not "
                      f"via $(CONFIG_...) expansion), so it has no Kconfig-driven "
                      f"on/off switch")
                if arches is None:
                    msg += " and is not declared in Kconfig at all"
                elif arch_only:
                    msg += f"; it is declared in Kconfig only for {sorted(arches - {None})}, not {arch}"
                findings.append({
                    "class": "zombie", "kind": "hardcoded_define", "symbol": sym,
                    "file": mk, "line": i, "message": msg,
                    "severity": "info" if arch_only else "error", "arch_only": arch_only,
                })
    return findings


# ---------------------------------------------------------------- whole tree

def run_whole_tree(analysis, tree, only=None, path_prefix=None, kconfig_rel="Kconfig",
                   arch="x86", dead_limit=None):
    findings = []
    counts = {}

    if not only or "zombie" in only:
        zf = zombie_check(analysis, tree, path_prefix=path_prefix, arch=arch)
        findings += zf
        counts["zombie"] = sum(1 for f in zf if not f["arch_only"])
        counts["zombie_arch_only"] = sum(1 for f in zf if f["arch_only"])

    if not only or "orphan" in only:
        of = _lint_sources.orphan_check(analysis, tree, arch=arch, path_prefix=path_prefix)
        findings += of
        counts["orphan"] = len(of)

    if not only or "dead" in only:
        try:
            kc = _lint_kconfig.KconfigConstraints(tree, kconfig_rel=kconfig_rel,
                                                  solver=analysis.solver())
            paths = [p for p in analysis.conds if not path_prefix or p.startswith(path_prefix)]
            df = _lint_kconfig.dead_check(analysis, kc, paths=paths, limit=dead_limit)
            for p, status, incomplete in df:
                msg = (f"{p} is unsatisfiable under Kbuild" +
                      ("" if status == "kbuild" else " and Kconfig") +
                      (" (Kconfig parse incomplete for a referenced symbol; "
                       "verify independently)" if incomplete else ""))
                findings.append({
                    "class": "dead", "file": p, "line": None, "message": msg,
                    "severity": "info" if incomplete else "error",
                    "status": status, "incomplete": incomplete,
                })
            counts["dead"] = sum(1 for _, _, i in df if not i)
            counts["dead_incomplete"] = sum(1 for _, _, i in df if i)
        except FileNotFoundError as e:
            findings.append({"class": "dead", "file": kconfig_rel, "line": None,
                             "message": f"cannot run the dead-object check: {e} not found",
                             "severity": "info"})

    return {"tree": str(tree), "arch": arch, "counts": counts, "findings": findings}


# ---------------------------------------------------------------- text output

def _loc(f):
    return f"{f['file']}:{f['line']}" if f.get("line") else str(f["file"])


def _text(d):
    lines = []
    if "condition_changes" in d:
        lines.append(f"kfold lint --diff {d['patch']}  (tree: {d['tree']})")
        lines.append(f"  {len(d['touched_files'])} files touched, "
                     f"{len(d['touched_kbuild_files'])} Makefile/Kconfig, "
                     f"{d['impacted_objects']} objects impacted")
        for c in d["condition_changes"]:
            lines.append(f"  {c['object']}: {c['change']}")
            if c["before"] is not None:
                lines.append(f"    before: {c['before']}")
            if c["after"] is not None:
                lines.append(f"    after:  {c['after']}")
    else:
        lines.append(f"kfold lint: {d['tree']} (arch={d['arch']})")
        lines.append("  " + ", ".join(f"{k}={v}" for k, v in d["counts"].items()))
    for f in d["findings"]:
        lines.append(f"{f['severity'].upper():7} {f['class']:7} {_loc(f)}: {f['message']}")
    return "\n".join(lines)
