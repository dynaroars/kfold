"""kfold query OBJ: the kind, origins, and condition of one object, and with
--config whether that configuration builds it."""
from cli import common


def register(subparsers):
    p = subparsers.add_parser("query", help="show an object's condition (and status under a .config)",
                              description=__doc__)
    p.add_argument("object", help="object or source path, e.g. fs/ext2/xattr.o or fs/ext2/xattr.c")
    common.add_tree_option(p)
    common.add_config_option(p)
    common.add_json_option(p)
    p.add_argument("--full", action="store_true", help="do not truncate the condition")
    p.add_argument("--raw", action="store_true",
                   help="show the condition as analyzed, without simplifying it")
    p.add_argument("--smt", action="store_true", help="also print the Z3 (SMT-LIB) condition")
    p.set_defaults(func=run)


MAX_TEXT = 2000


def run(args):
    a = common.get_analysis(args, hint=args.object)
    path = common.object_path(a, args.object)
    cond = a.conds[path]
    data = {
        "object": path,
        "tree": str(a.tree),
        "kind": a.kinds[path],
        "origins": [{"makefile": mk, "via": what} for mk, what in a.origins[path]],
        "condition": common.display_cond(cond, simplify=not args.raw,
                                         max_len=None if (args.full or args.json) else MAX_TEXT),
        "symbols": a.symbols(path),
    }
    if args.smt or args.json:
        data["smt"] = cond.sexpr()
    if args.config:
        values = common.load_config(args.config)
        data["config"] = {
            "path": args.config,
            "built": a.is_built(path, args.config),
            "values": {s: common.config_value(values, s) for s in data["symbols"]},
        }
    common.emit(args, data, _text)
    return 0


def _text(d):
    lines = [f"{d['object']}  ({d['kind']})"]
    for o in d["origins"]:
        lines.append(f"  from {o['makefile']}: {o['via']}")
    lines.append(f"  condition: {d['condition']}")
    if "smt" in d:
        lines.append(f"  smt: {d['smt']}")
    if "config" in d:
        c = d["config"]
        lines.append(f"  under {c['path']}: {'BUILT' if c['built'] else 'NOT built'}")
        if c["values"]:
            shown = list(c["values"].items())
            vals = ", ".join(f"{s}={v}" for s, v in shown[:40])
            more = f", ... (+{len(shown) - 40})" if len(shown) > 40 else ""
            lines.append(f"  values: {vals}{more}")
    return "\n".join(lines)
