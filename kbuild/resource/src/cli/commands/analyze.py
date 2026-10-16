"""kfold analyze TREE: analyze a tree once and cache the result."""
import time

from cli import cache, common


def register(subparsers):
    p = subparsers.add_parser("analyze", help="analyze a tree and cache its object conditions",
                              description=__doc__)
    p.add_argument("tree", nargs="?", default=None,
                   help="tree to analyze (default: see --tree of other commands)")
    p.add_argument("--force", "-f", action="store_true",
                   help="re-analyze even if the cache is valid")
    p.add_argument("--status", action="store_true",
                   help="only report whether a valid cache exists")
    p.add_argument("--clear", action="store_true", help="delete the tree's cache")
    p.add_argument("--verify", action="store_true",
                   help="re-run the analysis and check that the cached conditions are "
                        "Z3-equivalent to the fresh ones (slow)")
    common.add_json_option(p)
    p.set_defaults(func=run)


def run(args):
    tree = common.resolve_tree(args.tree)
    root = common.cache_root(args)
    cdir = cache.cache_dir_for(tree, root)
    if args.clear:
        removed = cache.clear(tree, root)
        common.emit(args, {"tree": str(tree), "cache": str(cdir), "removed": removed},
                    f"{'removed' if removed else 'no cache at'} {cdir}")
        return 0
    if args.status:
        meta, reason = cache.status(tree, root)
        data = {"tree": str(tree), "cache": str(cdir), "valid": reason is None,
                "reason": reason, "meta": _summary(meta)}
        common.emit(args, data, lambda d: f"{d['cache']}: " + (
            "valid" if d["valid"] else d["reason"]) + (
            f" ({d['meta']['counts']['objects']} objects, {d['meta']['created']})"
            if d["meta"] else ""))
        return 0 if reason is None else 1
    t0 = time.monotonic()
    before = None if args.force else cache.status(tree, root)[1]
    a = cache.analyze(tree, root, force=args.force,
                      log=None if args.json else common.warn)
    if args.verify:
        v = cache.verify(a)
        data = {"tree": str(tree), "cache": str(cdir), "verify": v,
                "seconds": round(time.monotonic() - t0, 2)}
        common.emit(args, data, lambda d: (
            f"{d['cache']}: {'OK' if v['ok'] else 'MISMATCH'}: {v['objects']} objects "
            f"({v['identical']} identical, {v['proved']} proved equivalent, {v['differ']} differ, "
            f"{v['unknown']} unknown, {v['missing']} missing, {v['extra']} extra; "
            f"{v['kind_mismatch']} kind / {v['origin_mismatch']} origin mismatches); "
            f"{v['makefiles']} Makefile guards, {v['makefile_differ']} differ"
            + "".join(f"\n  {k}: {p}" for k, p in v["examples"])))
        return 0 if v["ok"] else 1
    data = {"tree": str(tree), "cache": str(cdir),
            "reused": not args.force and before is None,
            "seconds": round(time.monotonic() - t0, 2), "meta": _summary(a._meta)}
    common.emit(args, data, lambda d: (
        f"{d['cache']}: {'cache is valid' if d['reused'] else 'written'}; "
        f"{d['meta']['counts']['objects']} objects from "
        f"{d['meta']['counts']['makefiles']} Makefiles"
        f" (analysis {d['meta']['analysis_seconds']}s)"))
    return 0


def _summary(meta):
    if not meta:
        return None
    return {k: meta.get(k) for k in ("format", "created", "analysis_seconds", "counts")}
