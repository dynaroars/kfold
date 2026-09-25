"""kfold config-for PATCH|FILE...: "how do I compile-test this?" Maps the
.c/.S files a patch (or an explicit file list) touches to kfold objects,
solves Phi_Kbuild(objects) && Phi_Kconfig for an assignment close to a base
.config (or with the fewest enabled symbols), and emits a .config fragment
that builds every touched object -- reporting objects that cannot be built
at all, or not all together, and why.
"""
import pathlib
import sys
import time

import z3
from z3.z3util import get_vars

import helpers.zsolver as zsolver
from cli import common
from cli.commands import _configfor_kconfig as kc
from cli.commands import _configfor_patch as patchmod
from cli.commands import _configfor_verify as verifymod

DEFAULT_DEFCONFIG = (pathlib.Path(__file__).resolve().parent.parent.parent.parent
                     / "results" / "revalidation_builds" / "linux_configs" / "defconfig" / ".config")


def register(subparsers):
    p = subparsers.add_parser(
        "config-for", help="a .config that builds the objects a patch or file list touches",
        description=__doc__)
    p.add_argument("input", nargs="+",
                   help="a patch file, '-' for a patch on stdin, or one or more "
                        "source paths (.c/.S)")
    common.add_tree_option(p)
    p.add_argument("--base", metavar=".config",
                   help="prefer this .config's values (default: fewest enabled symbols; "
                        "also the base --verify applies the fragment to)")
    p.add_argument("--full", action="store_true",
                   help="print the base .config merged with the fragment, not just the fragment")
    common.add_json_option(p)
    p.add_argument("--include-headers", action="store_true",
                   help="also try to map .h inputs to objects (usually not directly compiled)")
    p.add_argument("--timeout", type=int, default=60, metavar="SECONDS",
                   help="Z3 Optimize timeout for minimization (default 60)")
    p.add_argument("--max-kconfig-symbols", type=int, default=8000, metavar="N",
                   help="fall back to the whole-tree Kconfig formula if the patch's "
                        "dependency cone would exceed this many symbols")
    p.add_argument("--verify", action="store_true",
                   help="apply the fragment to --base (or the packaged defconfig) in a "
                        "/tmp copy of the tree and run `make ARCH=x86_64 olddefconfig`")
    p.add_argument("--compile", action="store_true",
                   help="with --verify, also `make ARCH=x86_64 <obj>` each touched object")
    p.add_argument("--verify-arch", default="x86_64", help="ARCH= for --verify's make (default x86_64)")
    p.set_defaults(func=run)


# ---------------------------------------------------------------- mapping

_SOURCE_EXTS = (".c", ".C", ".S", ".s")
_HEADER_EXTS = (".h",)
_UNSET = object()


def _read_input_text(items):
    if len(items) == 1 and items[0] == "-":
        return sys.stdin.read()
    if len(items) == 1 and pathlib.Path(items[0]).is_file():
        text = pathlib.Path(items[0]).read_text(errors="replace")
        if patchmod.looks_like_patch(text):
            return text
    return None


def classify_inputs(a, raw_inputs, text=_UNSET):
    """(known {input path: object path}, headers [...], skipped [(input, why)],
    unknown [(input, why)]) for the source paths a patch touches or that were
    given directly. ``text``, if given, is the already-read patch text (stdin
    can only be read once); pass it rather than letting this re-read it."""
    if text is _UNSET:
        text = _read_input_text(raw_inputs)
    paths = patchmod.touched_paths(text) if text is not None else list(raw_inputs)
    known, headers, skipped, unknown = {}, [], [], []
    for path in paths:
        ext = pathlib.Path(path).suffix
        if ext in _HEADER_EXTS:
            headers.append(path)
            continue
        if ext not in _SOURCE_EXTS:
            skipped.append((path, "not a .c/.S source kfold maps to an object"))
            continue
        try:
            obj = common.object_path(a, path)
            known[path] = obj
        except common.CLIError as e:
            unknown.append((path, str(e)))
    return known, headers, skipped, unknown


# ---------------------------------------------------------------- solving

def _solo_satisfiable(s, bvar, cache=None):
    s.push()
    s.add(bvar)
    r = s.check()
    s.pop()
    return r == z3.sat


def solve_targets(objs_conds, phi_kconfig):
    """(included {path: cond}, excluded {path: reason}) -- the largest subset
    of ``objs_conds`` simultaneously satisfiable with ``phi_kconfig``, found
    by dropping one conflicting object at a time using Z3 unsat cores."""
    names = sorted(objs_conds)
    bvars = {p: z3.Bool(f"__kfold_inc_{i}") for i, p in enumerate(names)}
    s = z3.Solver()
    s.add(phi_kconfig)
    for p in names:
        s.add(z3.Implies(bvars[p], objs_conds[p]))

    included, excluded = set(), {}
    for p in names:
        if _solo_satisfiable(s, bvars[p]):
            included.add(p)
        else:
            excluded[p] = "this object's own build condition is unsatisfiable under Kconfig " \
                          "and Kbuild constraints together (impossible under any configuration)"

    while included:
        r = s.check([bvars[p] for p in included])
        if r == z3.sat:
            break
        core = set(s.unsat_core())
        core_names = sorted(p for p in included if bvars[p] in core)
        if not core_names:
            core_names = sorted(included)
        drop = core_names[-1]
        others = [n for n in core_names if n != drop]
        excluded[drop] = ("conflicts with " + ", ".join(others)) if others else \
            "conflicts with the Kconfig/Kbuild constraints of the other requested objects"
        included.discard(drop)

    return {p: objs_conds[p] for p in included}, excluded


def minimize_config(solver, phi_kconfig, target_cond, base_values, timeout_ms):
    """A model of ``phi_kconfig && target_cond`` preferring ``base_values``
    (a {CONFIG_X: y|m|""} dict, possibly empty) for every symbol in scope,
    else undef; falls back to an unminimized model if Optimize times out.
    Returns ({CONFIG_X: y|m|""} for every symbol in scope}, minimized: bool)."""
    combined = z3.And(phi_kconfig, target_cond)
    scope = sorted({str(v) for v in get_vars(combined) if str(v).startswith("CONFIG_")})

    opt = z3.Optimize()
    opt.set("timeout", timeout_ms)
    opt.add(phi_kconfig)
    opt.add(target_cond)
    for name in scope:
        zvar, optd = solver.get_sort(name)
        want = base_values.get(name, "")
        val_expr = optd.get(want, optd[""])
        opt.add_soft(zvar == val_expr, 1)

    minimized = True
    if opt.check() != z3.sat:
        minimized = False
        s2 = z3.Solver()
        s2.add(phi_kconfig)
        s2.add(target_cond)
        if s2.check() != z3.sat:
            return None, False  # should not happen: solve_targets() already proved sat
        model = s2.model()
    else:
        model = opt.model()

    values = {}
    for name in scope:
        zvar, optd = solver.get_sort(name)
        val = model.eval(zvar, model_completion=True)
        val_str = str(val)
        for k, expr in optd.items():
            if str(expr) == val_str:
                values[name] = k
                break
    return values, minimized


# ---------------------------------------------------------------- output

def build_fragment(final_values, base_values):
    return {name: v for name, v in final_values.items() if v != base_values.get(name, "")}


def scripts_config_line(fragment):
    if not fragment:
        return ""
    parts = ["scripts/config"]
    for name in sorted(fragment):
        v = fragment[name]
        flag = {"y": "--enable", "m": "--module", "": "--disable"}[v]
        parts.append(f"{flag} {name}")
    return " ".join(parts)


def fragment_text(fragment):
    lines = []
    for name in sorted(fragment):
        v = fragment[name]
        lines.append(f"{name}={v}" if v in ("y", "m") else f"# {name} is not set")
    return "\n".join(lines)


def run(args):
    # Read stdin/the patch file (if any) exactly once: stdin in particular
    # cannot be re-read, and _patch_mode-style detection would otherwise need
    # a second read.
    text = _read_input_text(args.input)
    # A patch file is usually not inside the tree it patches, so only use an
    # input as a tree-discovery hint when it is (or looks like) a source path.
    hint = None if text is not None else args.input[0]
    a = common.get_analysis(args, hint=hint)
    known, headers, skipped, unknown = classify_inputs(a, args.input, text=text)
    if args.include_headers:
        for h in list(headers):
            try:
                known[h] = common.object_path(a, h)
            except common.CLIError:
                pass

    data = {
        "tree": str(a.tree),
        "inputs": args.input,
        "mapped": known,
        "headers_not_compiled": headers,
        "skipped": [{"path": p, "why": w} for p, w in skipped],
        "unmapped": [{"path": p, "why": w} for p, w in unknown],
    }

    if not known:
        data["error"] = "no input mapped to an object kfold knows"
        common.emit(args, data, _text_no_objects)
        return 1

    objs = sorted(set(known.values()))
    objs_conds = {o: a.conds[o] for o in objs}

    base_values = {}
    if args.base:
        base_values = common.load_config(args.base)

    solver = a.solver()
    seed_names = set()
    for cond in objs_conds.values():
        for v in get_vars(cond):
            n = str(v)
            if n.startswith("CONFIG_"):
                seed_names.add(n[len("CONFIG_"):])

    t0 = time.monotonic()
    ksmt = kc.load_kconfig(a.tree)
    used_kconfig = ksmt is not None
    if ksmt is not None:
        phi_kconfig, closure = kc.restricted_constraints(ksmt, solver, seed_names,
                                                          max_symbols=args.max_kconfig_symbols)
    else:
        phi_kconfig, closure = zsolver.T, set()
    kconfig_seconds = round(time.monotonic() - t0, 2)

    included, excluded = solve_targets(objs_conds, phi_kconfig)
    data["objects"] = objs
    data["excluded"] = excluded
    data["used_kconfig"] = used_kconfig
    data["kconfig_symbols_considered"] = len(closure)
    data["kconfig_seconds"] = kconfig_seconds

    if not included:
        data["error"] = "no requested object can be built (see excluded)"
        common.emit(args, data, _text_no_objects)
        return 1

    target_cond = zsolver.mconj(list(included.values()))

    t0 = time.monotonic()
    final_values, minimized = minimize_config(solver, phi_kconfig, target_cond, base_values,
                                              timeout_ms=args.timeout * 1000)
    solve_seconds = round(time.monotonic() - t0, 2)
    data["minimized"] = minimized
    data["solve_seconds"] = solve_seconds

    if final_values is None:
        data["error"] = "solver could not produce a model (unexpected)"
        common.emit(args, data, _text_no_objects)
        return 1

    fragment = build_fragment(final_values, base_values)
    data["base"] = args.base
    data["fragment"] = fragment
    data["scripts_config"] = scripts_config_line(fragment)

    built_by_fragment = set()
    check_cfg = dict(base_values)
    check_cfg.update(fragment)
    for o in objs:
        if a.is_built(o, check_cfg):
            built_by_fragment.add(o)
    data["predicted_built"] = sorted(built_by_fragment)
    data["predicted_not_built"] = sorted(set(objs) - built_by_fragment - set(excluded))

    full_text = None
    if args.full or args.verify:
        base_text = (pathlib.Path(args.base).read_text() if args.base
                    else (DEFAULT_DEFCONFIG.read_text() if DEFAULT_DEFCONFIG.is_file() else ""))
        full_text = verifymod.merge_config_text(base_text, fragment)
        if args.full:
            data["full_config"] = full_text

    if args.verify:
        base_for_verify = args.base or (str(DEFAULT_DEFCONFIG) if DEFAULT_DEFCONFIG.is_file() else None)
        if base_for_verify is None:
            data["verify"] = {"error": "no --base given and the packaged defconfig is absent"}
        else:
            base_text = pathlib.Path(base_for_verify).read_text()
            compile_targets = objs[:3] if args.compile else None
            result, final_cfg = verifymod.run_verify(
                a.tree, base_text, fragment, objs, arch=args.verify_arch,
                compile_targets=compile_targets)
            if final_cfg is not None:
                result["kfold_predicted_built"] = sorted(o for o in objs if a.is_built(o, str(final_cfg)))
                result["kfold_predicted_all_built"] = set(result["kfold_predicted_built"]) >= set(objs) - set(excluded)
            data["verify"] = result

    common.emit(args, data, _text)
    return 0 if not excluded and not data.get("predicted_not_built") else 1


def _text_no_objects(d):
    lines = [f"kfold: {d.get('error', 'nothing to do')}"]
    if d.get("headers_not_compiled"):
        lines.append("headers (not directly compiled): " + ", ".join(d["headers_not_compiled"]))
    for u in d.get("unmapped", []):
        lines.append(f"  {u['path']}: {u['why']}")
    for e, why in d.get("excluded", {}).items():
        lines.append(f"  {e}: {why}")
    return "\n".join(lines)


def _text(d):
    lines = [f"tree: {d['tree']}"]
    lines.append(f"objects ({len(d['objects'])}): " + ", ".join(d["objects"]))
    if d["headers_not_compiled"]:
        lines.append("headers, not directly compiled: " + ", ".join(d["headers_not_compiled"]))
    for u in d["unmapped"]:
        lines.append(f"unmapped: {u['path']}: {u['why']}")
    for s in d["skipped"]:
        lines.append(f"skipped: {s['path']}: {s['why']}")
    for e, why in d["excluded"].items():
        lines.append(f"EXCLUDED {e}: {why}")
    lines.append(f"used_kconfig={d['used_kconfig']} kconfig_symbols={d['kconfig_symbols_considered']} "
                f"minimized={d.get('minimized')} solve_seconds={d.get('solve_seconds')}")
    lines.append("--- fragment ---")
    lines.append(fragment_text(d["fragment"]) or "(no changes needed)")
    if d.get("scripts_config"):
        lines.append(d["scripts_config"])
    if d.get("predicted_not_built"):
        lines.append("WARNING not predicted built: " + ", ".join(d["predicted_not_built"]))
    if "full_config" in d:
        lines.append("--- full .config ---")
        lines.append(d["full_config"])
    if "verify" in d:
        v = d["verify"]
        if "error" in v:
            lines.append(f"verify: {v['error']}")
        else:
            lines.append(f"verify: workdir={v['workdir']} olddefconfig_rc={v['olddefconfig_rc']} "
                        f"lost={list(v['lost'])} kfold_predicted_all_built="
                        f"{v.get('kfold_predicted_all_built')}")
            if v.get("compile"):
                for obj, r in v["compile"].items():
                    lines.append(f"  make {obj}: rc={r['rc']} built={r['built']}")
    return "\n".join(lines)
