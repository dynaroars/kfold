"""kfold blindspots: code no standard configuration builds, grouped by the
MAINTAINERS entry that owns it.

A "blind spot" is an object that ``kfold query``'s condition predicts as NOT
built under any of ``--configs`` (default: x86_64 allmodconfig, allyesconfig,
defconfig). Each blind spot is attributed to the most specific MAINTAINERS
entry claiming its source path (see ``_blindspots_maintainers`` for the exact
matching rules) and given a best-effort reason:

  - "non-x86 arch": the object lives under arch/<other>/ or its condition
    needs another architecture's top-level symbol (CONFIG_ARM, CONFIG_MIPS,
    ...) -- structurally unbuildable on x86_64 no matter the config.
  - "excludes a symbol every config enables": the condition is only
    satisfied by turning OFF some CONFIG_X that is on (y or m) in *every*
    provided config (e.g. ``depends on !COMPILE_TEST``, or a Kconfig
    ``choice`` whose selected member conflicts with one all*config always
    picks).
  - "Kconfig-unreachable": the condition is unsatisfiable under *any*
    assignment (proved with Z3) -- truly dead code, not just unbuilt by
    these configs.
  - "other": the condition needs a symbol that is off in every provided
    config (and turning it on, holding the rest fixed, would build the
    object) or the blocker is a multi-symbol combination this heuristic
    does not resolve; see the object's condition (``--json`` includes it)
    for the details.
"""
import pathlib
import re

import z3

from cli import common
from cli.commands import _blindspots_maintainers as mnt

ARCH_SYMS = {
    "CONFIG_ARM", "CONFIG_ARM64", "CONFIG_MIPS", "CONFIG_PPC", "CONFIG_PPC32",
    "CONFIG_PPC64", "CONFIG_RISCV", "CONFIG_S390", "CONFIG_SPARC", "CONFIG_SPARC32",
    "CONFIG_SPARC64", "CONFIG_MICROBLAZE", "CONFIG_XTENSA", "CONFIG_M68K",
    "CONFIG_SUPERH", "CONFIG_SH", "CONFIG_LOONGARCH", "CONFIG_PARISC",
    "CONFIG_ALPHA", "CONFIG_IA64", "CONFIG_NIOS2", "CONFIG_OPENRISC",
    "CONFIG_CSKY", "CONFIG_ARC", "CONFIG_HEXAGON", "CONFIG_UML",
}

DEFAULT_CONFIGS = ["allmodconfig", "allyesconfig", "defconfig"]

# Where named configs are looked up, in order; {name} is substituted.
CONFIG_SEARCH = [
    "results/revalidation_builds/linux_configs/{name}/.config",
    "results/revalidation_builds/linux_configs/{name}.config",
]
# A second root (outside the repo) generated configs may be cached under,
# per DEVTOOL_PLAN's shared-tree rule: build missing configs in a /tmp copy
# of the tree, not in the analyzed tree itself.
EXTRA_CONFIG_ROOTS = ["/tmp/kfold-blind/configs"]


def register(subparsers):
    p = subparsers.add_parser(
        "blindspots", help="code no standard config builds, grouped by MAINTAINERS entry",
        description=__doc__)
    common.add_tree_option(p)
    p.add_argument("--configs", nargs="+", default=None, metavar="CONFIG",
                   help="'.config' paths or named configs (allmodconfig, allyesconfig, "
                        f"defconfig); default: {' '.join(DEFAULT_CONFIGS)}")
    p.add_argument("--maintainers", metavar="FILE", default=None,
                   help="MAINTAINERS file (default: <tree>/MAINTAINERS)")
    p.add_argument("--entry", metavar="NAME", default=None,
                   help="only report the MAINTAINERS entry(s) whose title contains NAME "
                        "(case-insensitive)")
    p.add_argument("--path", metavar="PREFIX", default=None,
                   help="only consider objects whose path starts with PREFIX")
    p.add_argument("--limit", type=int, default=None,
                   help="show only the top LIMIT entries by blind-spot count")
    common.add_json_option(p)
    p.set_defaults(func=run)


# ---------------------------------------------------------------- configs

def _resolve_named_config(name):
    import cli
    candidates = [cli.ROOT / s.format(name=name) for s in CONFIG_SEARCH]
    candidates += [pathlib.Path(r) / name / ".config" for r in EXTRA_CONFIG_ROOTS]
    for c in candidates:
        if c.is_file():
            return c
    raise common.CLIError(
        f"no '.config' found for named config '{name}' (tried: "
        f"{', '.join(str(c) for c in candidates)}); pass a .config path instead, or generate "
        f"it in a /tmp copy of the tree (see DEVTOOL_PLAN.md's shared-tree rules) and place it "
        f"under one of the paths above")


def resolve_configs(names):
    """[(label, path)] for each of ``names``: a '.config' path used as-is,
    else a named config resolved via ``_resolve_named_config``."""
    out = []
    for n in names:
        p = pathlib.Path(n).expanduser()
        if p.is_file():
            out.append((n, p))
        else:
            out.append((n, _resolve_named_config(n)))
    return out


# ---------------------------------------------------------------- source path

def source_path(tree, obj_path):
    """Best-effort source path for an object path, e.g. 'fs/ext2/xattr.o' ->
    'fs/ext2/xattr.c': MAINTAINERS lists sources, not built objects. Falls
    back to the '.c' guess (or the object path itself for non-'.o' entries)
    when no matching source file is found on disk, which only affects
    exact-file (non-directory, non-wildcard) F:/X: pattern matches."""
    if not obj_path.endswith(".o"):
        return obj_path
    stem = obj_path[:-2]
    for ext in (".c", ".S", ".s"):
        if (tree / (stem + ext)).is_file():
            return stem + ext
    return stem + ".c"


# ---------------------------------------------------------------- classification

def _raw_value(values, sym):
    return values.get(sym, "")


def _unsat(cond, timeout_ms=3000):
    try:
        s = z3.Solver()
        s.set("timeout", timeout_ms)
        s.add(cond)
        return s.check() == z3.unsat
    except z3.Z3Exception:
        return False


def _find_blocker(analysis, cond, syms, values):
    """(sym, current_value, fix_value) for one symbol whose value, if changed
    (holding every other symbol at ``values``), would make ``cond`` true --
    or None if no single-symbol flip does. Picks the first such symbol found
    (conditions here are typically small conjunctions/disjunctions of a
    handful of symbols, so this usually finds the real cause; genuinely
    multi-symbol blockers are left as 'other')."""
    solver = analysis.solver()
    zvars = {}
    for sym in syms:
        zvar, optD = solver.get_sort(sym)
        zvars[sym] = (zvar, optD)
    base_subs = [(zvars[sym][0], zvars[sym][1].get(_raw_value(values, sym),
                                                    zvars[sym][1][""]))
                 for sym in syms]
    for i, sym in enumerate(syms):
        zvar, optD = zvars[sym]
        cur_val = _raw_value(values, sym)
        cur_expr = optD.get(cur_val, optD[""])
        for alt_val, alt_expr in optD.items():
            if alt_expr.eq(cur_expr):
                continue
            subs = list(base_subs)
            subs[i] = (zvar, alt_expr)
            try:
                result = z3.simplify(z3.substitute(cond, subs))
            except z3.Z3Exception:
                continue
            if z3.is_true(result):
                return sym, (cur_val or "n"), (alt_val or "n")
    return None


def classify(analysis, path, cond, configs):
    """A short human-readable reason ``path`` is a blind spot under every
    (name, {CONFIG_X: value}) in ``configs``."""
    parts = path.split("/")
    if len(parts) > 1 and parts[0] == "arch" and parts[1] != "x86":
        return f"non-x86 arch (arch/{parts[1]}/)"
    syms = analysis.symbols(path)
    hit = ARCH_SYMS & set(syms)
    if hit:
        return "non-x86 arch symbol (" + ", ".join(sorted(hit)) + ")"
    if not isinstance(cond, z3.ExprRef):
        return "other (constant false condition)"
    if _unsat(cond):
        return "Kconfig-unreachable (condition is unsatisfiable)"
    if not syms:
        return "other"
    name0, values0 = configs[0]
    blocker = _find_blocker(analysis, cond, syms, values0)
    if blocker is None:
        return "other"
    sym, cur, fix = blocker
    if cur in ("y", "m") and fix == "n":
        if all(_raw_value(v, sym) in ("y", "m") for _, v in configs):
            return f"excludes a symbol every config enables (needs {sym}=n, but every " \
                   f"provided config sets it {cur})"
        return f"excludes {sym}={cur} (on in {name0}, off in some other provided config)"
    if cur == "n" and fix in ("y", "m"):
        return f"other: not enabled by any provided config (needs {sym}={fix})"
    return "other"


# ---------------------------------------------------------------- run

def run(args):
    a = common.get_analysis(args)
    tree = a.tree
    mfile = pathlib.Path(args.maintainers) if args.maintainers else tree / "MAINTAINERS"
    if not mfile.is_file():
        raise common.CLIError(f"{mfile}: no such MAINTAINERS file")
    entries = mnt.parse(mfile.read_text(errors="replace"), tree=tree)
    index = mnt.MaintainersIndex(entries)

    config_names = args.configs or DEFAULT_CONFIGS
    resolved = resolve_configs(config_names)
    configs = [(name, common.load_config(str(path))) for name, path in resolved]

    paths = sorted(a.conds)
    if args.path:
        paths = [p for p in paths if p.startswith(args.path)]

    # attribute every considered object to its most-specific entries, and to
    # its total-objects-per-entry denominator (needed for "% of entry"),
    # regardless of whether it is a blind spot.
    entry_totals = {}       # entry.id -> total objects attributed to it
    entry_titles = {}       # entry.id -> title
    unclaimed_total = 0
    obj_entries = {}        # path -> [entry.id]

    for p in paths:
        src = source_path(tree, p)
        matched, _depth = index.entries_for(src)
        if not matched:
            unclaimed_total += 1
            obj_entries[p] = []
            continue
        obj_entries[p] = [e.id for e in matched]
        for e in matched:
            entry_totals[e.id] = entry_totals.get(e.id, 0) + 1
            entry_titles[e.id] = e.title

    predicted_by_config = {name: a.predicted(cfgvals, paths) for name, cfgvals in configs}
    built_anywhere = set()
    for s in predicted_by_config.values():
        built_anywhere |= s

    blind = [p for p in paths if p not in built_anywhere]

    by_entry = {}       # entry.id -> list of (path, reason)
    unclaimed_blind = []
    for p in blind:
        cond = a.conds[p]
        reason = classify(a, p, cond, configs)
        ids = obj_entries[p]
        if not ids:
            unclaimed_blind.append((p, reason))
            continue
        for eid in ids:
            by_entry.setdefault(eid, []).append((p, reason))

    rows = []
    for eid, items in by_entry.items():
        total = entry_totals.get(eid, len(items))
        rows.append({
            "entry": entry_titles.get(eid, f"#{eid}"),
            "blind_spots": len(items),
            "total_objects": total,
            "percent": round(100.0 * len(items) / total, 1) if total else None,
            "objects": sorted(items),
        })
    rows.sort(key=lambda r: r["blind_spots"], reverse=True)

    if args.entry:
        needle = args.entry.lower()
        rows = [r for r in rows if needle in r["entry"].lower()]

    if args.limit:
        rows = rows[:args.limit]

    data = {
        "tree": str(tree),
        "maintainers": str(mfile),
        "configs": [{"name": n, "path": str(p)} for n, p in resolved],
        "objects_considered": len(paths),
        "blind_spots": len(blind),
        "entries_with_blind_spots": len(by_entry),
        "unclaimed_blind_spots": sorted(unclaimed_blind),
        "unclaimed_total_objects": unclaimed_total,
        "top_entries": rows,
    }
    common.emit(args, data, _text)
    return 0


def _text(d):
    lines = [
        f"{d['tree']}",
        f"  {d['objects_considered']} objects considered under "
        f"{', '.join(c['name'] for c in d['configs'])}",
        f"  {d['blind_spots']} blind spots across {d['entries_with_blind_spots']} "
        f"MAINTAINERS entries ({len(d['unclaimed_blind_spots'])} unclaimed by any entry)",
        "",
    ]
    for r in d["top_entries"]:
        pct = f" ({r['percent']}%)" if r["percent"] is not None else ""
        lines.append(f"{r['blind_spots']:5d}{pct:>8}  {r['entry']}  "
                     f"[{r['total_objects']} objects total]")
        for p, reason in r["objects"][:10]:
            lines.append(f"         {p}  -- {reason}")
        if len(r["objects"]) > 10:
            lines.append(f"         ... (+{len(r['objects']) - 10} more)")
    return "\n".join(lines)
