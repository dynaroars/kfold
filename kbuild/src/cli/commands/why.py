"""kfold why OBJ --config .config: "why isn't my file built?" A guard chain
(directory reachability, then the obj-/lib-/member line that selects the
object), each conjunct marked built/not-built under the config; for a
not-built object, the symbols responsible and, via Kconfig (depends on /
select / choice), why they are off and a minimal set of changes that would
turn the object on.
"""
import os
import pathlib
import re

from cli import common
from cli.commands import _why_kconfig as wk

MAX_TEXT = 2000


def register(subparsers):
    p = subparsers.add_parser("why", help="explain whether/why an object is built (guard chain + Kconfig)",
                              description=__doc__)
    p.add_argument("object", help="object or source path, e.g. fs/ext2/xattr.o or fs/ext2/xattr.c")
    common.add_tree_option(p)
    common.add_config_option(p)
    common.add_json_option(p)
    p.add_argument("--full", action="store_true", help="do not truncate the condition")
    p.add_argument("--no-kconfig", action="store_true",
                   help="skip the Kconfig explanation/suggestion (guard chain only)")
    p.set_defaults(func=run)


# ---------------------------------------------------------------- guard chain

def _find_line(makefile_path, pattern, prefer=("CONFIG_", "+=", ":=")):
    """(lineno, text) of the first non-comment line of ``makefile_path``
    matching regex ``pattern``, preferring lines that also look like a
    variable assignment; (None, None) if unreadable or no match."""
    try:
        lines = makefile_path.read_text(errors="replace").splitlines()
    except OSError:
        return None, None
    rx = re.compile(pattern)
    # Match against the line with any trailing Make comment removed, so a
    # comment such as "# Before hfs to ..." does not count as a reference.
    hits = [(i + 1, line) for i, line in enumerate(lines)
            if not line.lstrip().startswith("#") and rx.search(line.split("#", 1)[0])]
    if not hits:
        return None, None
    hits.sort(key=lambda t: sum(0 if k in t[1] else 1 for k in prefer))
    return hits[0]


def _object_word(path, what):
    if what.startswith("member of "):
        return what[len("member of "):]
    if what.startswith("object of program "):
        # "object of program NAME (var)"
        return pathlib.Path(path).name
    return pathlib.Path(path).name


def build_guard_chain(a, path):
    """The ordered list of guard-chain conjuncts for ``path``: ancestor
    directory-reachability entries (from the tree root down to the Makefile
    that defines the object), then the obj-/lib-/member line itself. Each
    entry: {label, makefile, line, text, cond}. Returns (chain, primary
    makefile, primary "what")."""
    origins = sorted(a.origins.get(path, ()))
    if not origins:
        return [], None, None
    # Prefer an origin whose "what" matches the object's own kind, else the
    # first (alphabetically first Makefile, for determinism).
    kind = a.kinds.get(path)
    preferred = {"target": lambda w: w in ("obj-y", "obj-m", "lib-y", "lib-m"),
                 "member": lambda w: w.startswith("member of "),
                 "program": lambda w: w.startswith("object of program "),
                 "rule": lambda w: w == "prerequisite"}.get(kind)
    mk0, what0 = origins[0]
    if preferred:
        for mk, what in origins:
            if preferred(what):
                mk0, what0 = mk, what
                break

    tree = a.tree
    mkdir = (tree / mk0).parent
    try:
        rel_parts = mkdir.relative_to(tree).parts
    except ValueError:
        rel_parts = ()
    dirs = [tree] + [tree.joinpath(*rel_parts[:i + 1]) for i in range(len(rel_parts))]

    chain_mks = []
    for d in dirs:
        for name in ("Makefile", "Kbuild", "Makefile.inc"):
            relmk = str((d / name).relative_to(tree)) if d != tree else name
            if relmk in a.reached or relmk in a.builtin:
                chain_mks.append(relmk)
                break
    if mk0 not in chain_mks:
        chain_mks.append(mk0)

    chain = []
    for i, relmk in enumerate(chain_mks):
        # Directory reachability: builtin (obj-y route) is the operative
        # guard whenever it is known for this Makefile; else plain reach.
        if relmk in a.builtin:
            cond, via = a.builtin[relmk], "reached (built-in / obj-y route)"
        elif relmk in a.reached:
            cond, via = a.reached[relmk], "reached"
        else:
            continue
        lineno = text = None
        line_file = relmk
        if i > 0:
            # The subdirectory is selected by a line in the parent Makefile,
            # e.g. "obj-$(CONFIG_HFS_FS) += hfs/"; "hfs/" must not match "hfsplus/".
            line_file = chain_mks[i - 1]
            subdir = pathlib.Path(relmk).parent.name
            lineno, text = _find_line(tree / line_file, r"(?<![\w./-])" + re.escape(subdir) + r"/(?![\w.-])")
        chain.append({"label": f"{via}: {relmk}", "makefile": relmk, "line_file": line_file,
                      "line": lineno, "text": text, "cond": cond})

    word = _object_word(path, what0)
    lineno, text = _find_line(tree / mk0, r"\b" + re.escape(word).replace(r"\.", r"\.") + r"\b")
    chain.append({"label": f"{what0} in {mk0}: {word}", "makefile": mk0, "line_file": mk0,
                  "line": lineno, "text": text,
                 "cond": a.conds[path]})
    return chain, mk0, what0


# ---------------------------------------------------------------- symbols / Kconfig

def _pivotal_symbols(a, path, config_values, solver, tristate):
    """Symbols currently off whose lone flip (to y, or m if tristate) would
    make the object's condition true -- a quick, per-symbol explanation of
    "what's blocking this"."""
    cond = a.conds[path]
    if wk.truth_of(cond, config_values, solver):
        return []
    out = []
    all_values = ["y", "m", "n"] if tristate else ["y", "n"]
    for sym in a.symbols(path):
        cur = wk.cur_value(config_values, sym[len("CONFIG_"):]) if sym.startswith("CONFIG_") else "n"
        for tv in [v for v in all_values if v != cur]:
            trial = dict(config_values)
            trial[sym] = tv
            if wk.truth_of(cond, trial, solver):
                out.append({"symbol": sym, "current_value": cur, "suggested_value": tv})
                break
    return out


def _config_fragment(diff):
    lines = []
    for name, val in sorted(diff.items()):
        lines.append(f"{name}={val}" if val in ("y", "m") else f"# {name} is not set")
    return "\n".join(lines) + ("\n" if lines else "")


def _scripts_config_cmd(diff):
    flag = {"y": "--enable", "m": "--module", "n": "--disable"}
    parts = ["scripts/config"]
    for name, val in sorted(diff.items()):
        bare = name[len("CONFIG_"):] if name.startswith("CONFIG_") else name
        parts += [flag[val], bare]
    return " ".join(parts) if len(parts) > 1 else None


# ---------------------------------------------------------------- run

def run(args):
    a = common.get_analysis(args, hint=args.object)
    path = common.object_path(a, args.object)
    kind = a.kinds[path]
    chain, mk0, what0 = build_guard_chain(a, path)

    data = {
        "object": path,
        "tree": str(a.tree),
        "kind": kind,
        "origins": [{"makefile": mk, "via": what} for mk, what in a.origins[path]],
        "condition": common.display_cond(a.conds[path], max_len=None if (args.full or args.json) else MAX_TEXT),
        "symbols": a.symbols(path),
        "guard_chain": [
            {"label": g["label"], "makefile": g["makefile"], "line_file": g["line_file"], "line": g["line"], "text": g["text"],
             "condition": common.display_cond(g["cond"], max_len=None if (args.full or args.json) else MAX_TEXT)}
            for g in chain
        ],
    }

    if not args.config:
        common.emit(args, data, _text_no_config)
        return 0

    config_values = common.load_config(args.config)
    solver = a.solver()
    tristate = bool(a.meta["key"]["options"]["use_tristate"])
    built = a.is_built(path, config_values)

    for g, entry in zip(chain, data["guard_chain"]):
        entry["ok"] = wk.truth_of(g["cond"], config_values, solver)

    data["config"] = {"path": args.config, "built": built}
    first_fail = next((e for e in data["guard_chain"] if e["ok"] is False), None)
    data["config"]["first_failing_conjunct"] = first_fail["label"] if first_fail else None

    if built:
        common.emit(args, data, _text)
        return 0

    pivotal = _pivotal_symbols(a, path, config_values, solver, tristate)
    data["config"]["pivotal_symbols"] = pivotal
    data["config"]["values"] = {s: common.config_value(config_values, s) for s in a.symbols(path)}

    if args.no_kconfig:
        common.emit(args, data, _text)
        return 0

    ksmt, err = wk.load(a.tree)
    if ksmt is None:
        data["config"]["kconfig_error"] = err
        common.emit(args, data, _text)
        return 0

    import kconfiglib

    import kconfig_compat  # noqa: F401  (Kconfig syntax newer than kconfiglib)
    explain_names = ([p["symbol"][len("CONFIG_"):] for p in pivotal] if pivotal
                     else [s[len("CONFIG_"):] for s in a.symbols(path)])
    seen = set()
    explanations = []
    for name in explain_names:
        if name in seen:
            continue
        seen.add(name)
        explanations.append(wk.explain_symbol(ksmt, kconfiglib, name, config_values))
    data["config"]["symbol_explanations"] = explanations

    diff, note = wk.minimal_changes(a, ksmt, kconfiglib, path, config_values)
    data["config"]["suggested_change"] = {
        "note": note,
        "diff": diff,
        "config_fragment": _config_fragment(diff) if diff else None,
        "scripts_config_cmd": _scripts_config_cmd(diff) if diff else None,
    }

    common.emit(args, data, _text)
    return 0


# ---------------------------------------------------------------- text output

def _mark(ok):
    return "?" if ok is None else ("✓" if ok else "✗")


def _text_no_config(d):
    lines = [f"{d['object']}  ({d['kind']})"]
    for o in d["origins"]:
        lines.append(f"  from {o['makefile']}: {o['via']}")
    lines.append("guard chain:")
    for g in d["guard_chain"]:
        where = f"  [{g['line_file']}:{g['line']}]" if g["line"] else f"  [{g['makefile']}]"
        lines.append(f"  - {g['label']}{where}: {g['condition']}")
    lines.append(f"condition: {d['condition']}")
    return "\n".join(lines)


def _text(d):
    lines = [f"{d['object']}  ({d['kind']})"]
    c = d["config"]
    lines.append(f"under {c['path']}: {'BUILT' if c['built'] else 'NOT built'}")
    lines.append("guard chain:")
    for g in d["guard_chain"]:
        where = f" [{g['line_file']}:{g['line']}]" if g["line"] else f" [{g['makefile']}]"
        lines.append(f"  {_mark(g.get('ok'))} {g['label']}{where}")
        if g.get("text"):
            lines.append(f"      {g['text'].strip()}")
        lines.append(f"      {g['condition']}")
    if c["built"]:
        return "\n".join(lines)
    if c.get("first_failing_conjunct"):
        lines.append(f"first failing conjunct: {c['first_failing_conjunct']}")
    if c.get("pivotal_symbols"):
        lines.append("symbols that alone would fix it:")
        for p in c["pivotal_symbols"]:
            lines.append(f"  {p['symbol']}={p['current_value']} -> {p['suggested_value']}")
    if "kconfig_error" in c:
        lines.append(f"(no Kconfig explanation: {c['kconfig_error']})")
        return "\n".join(lines)
    if c.get("symbol_explanations"):
        lines.append("Kconfig:")
        for e in c["symbol_explanations"]:
            if not e.get("found"):
                lines.append(f"  {e['name']}: not a Kconfig symbol")
                continue
            lines.append(f"  {e['name']}={e['current_value']}"
                         + (f"  depends on: {e['depends_on']}" if e.get("depends_on") else ""))
            for u in e.get("unmet_deps", []):
                lines.append(f"      unmet: {u['name']}={u['value']}")
            if e.get("choice"):
                ch = e["choice"]
                lines.append(f"      choice ({ch['prompt']}): members={ch['members']}, "
                             f"currently selected={ch['currently_selected']}")
            for s in e.get("selected_by", []):
                lines.append(f"      would also be enabled by select from {s['name']}={s['value']}"
                             + (f" if {s['condition']}" if s.get("condition") else ""))
    sc = c.get("suggested_change") or {}
    if sc.get("diff"):
        lines.append(f"suggested minimal change ({sc['note']}):")
        lines.append(_config_fragment(sc["diff"]))
        lines.append(sc["scripts_config_cmd"])
    elif sc.get("note"):
        lines.append(f"suggested change: none found ({sc['note']})")
    return "\n".join(lines)
