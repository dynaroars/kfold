"""Persistent per-tree analysis cache.

``analyze(tree)`` runs kfold once over a tree (``alg.Run(...).go()`` and
``objects.object_conditions``) and stores, for every object path, its kind,
its origins (Makefile, variable or rule), and its Z3 condition; plus the
condition under which each analyzed Makefile is reached (``reached``) and,
for trees with ``need_builtin``, reached through obj-y only (``builtin``).
``load(tree)`` returns the same data as an :class:`Analysis` without running
the analyzer.

Layout, under ``<cache root>/<tree name>-<hash of the tree path>/``:

``meta.json``
    format version, the cache key, the files the analysis read (each with
    mtime and size), the enum sorts and the variables of the conditions, and
    per object ``[kind, origins, variable ids, offset, length]``.
``conds.smt2``
    one SMT-LIB term per condition, concatenated. Shared subterms are bound
    with ``let``, so the text is linear in the size of the formula DAG.

Conditions are parsed back with ``z3.parse_smt2_string`` lazily, one object
at a time, against the same enum sorts ``helpers.zsolver`` creates, so they
are interchangeable with the analyzer's own expressions (and with
``ZSolver.get_sort`` / ``KconfigSMT`` variables) in the same process.

Staleness: a cache is valid if its format version, analysis options, and
analyzer digest (a content hash of the analyzer's own ``src/`` modules,
excluding ``src/cli``) match, and every file the analysis read -- each
Makefile/Kbuild file and included fragment, plus ``skbuild.ini`` -- still
has the recorded path, mtime (ns), and size. This is a stat, not a content
hash; it does not notice a *new* Makefile in a directory that no analyzed
Makefile reached, nor an include that was missing and later appears.
"""
import hashlib
import json
import os
import pathlib
import shutil
import sys
import tempfile
import time
from collections.abc import Mapping

import z3

import cli  # noqa: F401  (sets up sys.path)

FORMAT_VERSION = 1
META = "meta.json"
CONDS = "conds.smt2"

# Environment switches that change what the analyzer computes.
_ENV_SWITCHES = ("KFOLD_NO_LINK_SEMANTICS", "KFOLD_NO_RULES", "KFOLD_NO_INCLUDES",
                 "KFOLD_SETTINGS_FILE")


class CacheError(Exception):
    pass


# ---------------------------------------------------------------- locations

def default_cache_root():
    env = os.environ.get("KFOLD_CACHE")
    if env:
        return pathlib.Path(env).expanduser()
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = pathlib.Path(xdg).expanduser() if xdg else pathlib.Path.home() / ".cache"
    return base / "kfold"


def tree_root(tree):
    """The analyzed directory: a Makefile argument means its directory."""
    tree = pathlib.Path(tree).expanduser().resolve()
    return tree.parent if tree.is_file() else tree


def cache_dir_for(tree, cache_root=None):
    tree = tree_root(tree)
    root = pathlib.Path(cache_root).expanduser() if cache_root else default_cache_root()
    h = hashlib.sha256(str(tree).encode()).hexdigest()[:16]
    return root / f"{tree.name or 'root'}-{h}"


# ---------------------------------------------------------------- digests

_ANALYZER_DIGEST = None


def analyzer_digest():
    """Content hash of the analyzer's modules (src/ minus src/cli)."""
    global _ANALYZER_DIGEST
    if _ANALYZER_DIGEST is None:
        h = hashlib.sha256()
        for p in sorted(cli.SRC.rglob("*.py")):
            rel = p.relative_to(cli.SRC)
            if rel.parts[0] == "cli" or "__pycache__" in rel.parts:
                continue
            h.update(str(rel).encode() + b"\0" + p.read_bytes() + b"\0")
        _ANALYZER_DIGEST = h.hexdigest()
    return _ANALYZER_DIGEST


def options_key(use_tristate):
    return {"use_tristate": bool(use_tristate),
            "env": {k: os.environ[k] for k in _ENV_SWITCHES if os.environ.get(k)}}


def _stat(path):
    st = os.stat(path)
    return [st.st_mtime_ns, st.st_size]


def _rel(path, tree):
    p = pathlib.Path(path)
    try:
        return str(p.resolve().relative_to(tree))
    except ValueError:
        return str(p.resolve())


# ---------------------------------------------------------------- SMT-LIB

_SHARED = "kf!"


class _Nodes:
    """Structure of Z3 AST nodes by id, so serializing many formulas that
    share subterms queries Z3 once per distinct node. Keeps the nodes alive,
    which keeps their ids stable."""

    def __init__(self):
        self.info = {}  # id -> (head or None, child ids, leaf text, node)

    def get(self, n):
        k = n.get_id()
        r = self.info.get(k)
        if r is not None:
            return r
        stack = [(n, False)]
        while stack:
            m, done = stack.pop()
            mk = m.get_id()
            if mk in self.info:
                continue
            if z3.is_app(m) and m.num_args() > 0:
                kids = m.children()
                if not done:
                    stack.append((m, True))
                    stack.extend((c, False) for c in kids if c.get_id() not in self.info)
                    continue
                d = m.decl()
                head = d.name()
                if d.kind() == z3.Z3_OP_UNINTERPRETED:
                    head = _symbol(head)
                self.info[mk] = (head, tuple(c.get_id() for c in kids), None, m, mk)
            else:
                self.info[mk] = (None, (), m.sexpr(), m, mk)
        return self.info[k]


def expr_to_smt(e, variables=None, nodes=None):
    """SMT-LIB text of ``e``; subterms used more than once become ``let``
    bindings so the text is linear in the DAG size (Z3's printer would
    expand them). If ``variables`` is a list, the uninterpreted constants of
    ``e`` are appended to it. ``nodes`` (a ``_Nodes``) may be shared across
    calls to speed up serializing many formulas."""
    nodes = nodes or _Nodes()
    info = nodes.info
    root = nodes.get(e)[4]
    refs, order = {}, []
    stack = [(root, False)]
    while stack:
        k, done = stack.pop()
        if done:
            order.append(k)
            continue
        if k in refs:
            refs[k] += 1
            continue
        refs[k] = 1
        stack.append((k, True))
        stack.extend((c, False) for c in reversed(info[k][1]))
    text, bindings = {}, []
    for k in order:
        head, kids, leaf, n, _ = info[k]
        if head is None:
            s = leaf
            if (variables is not None and z3.is_app(n)
                    and n.decl().kind() == z3.Z3_OP_UNINTERPRETED):
                variables.append(n)
        else:
            s = "(" + head + " " + " ".join([text[c] for c in kids]) + ")"
            if refs[k] > 1 and k != root:
                b = f"{_SHARED}{len(bindings)}"
                bindings.append((b, s))
                s = b
        text[k] = s
    body = text[root]
    for b, s in reversed(bindings):
        body = f"(let (({b} {s})) {body})"
    return body


def _symbol(name):
    simple = name and all(c.isalnum() or c in "~!@$%^&*_-+=<>.?/" for c in name) \
        and not name[0].isdigit()
    return name if simple else "|" + name.replace("|", "") + "|"


# ---------------------------------------------------------------- sorts

def _get_sort(name, constructors):
    from helpers import zsolver
    return zsolver._get_enum_sort(name, list(constructors))[0]


# ---------------------------------------------------------------- the store

class LazyConds(Mapping):
    """{path: z3 condition}, parsed from the cache on first access."""

    def __init__(self, analysis, section):
        self._a = analysis
        self._section = section
        self._index = analysis._meta[section]
        self._parsed = {}

    def __getitem__(self, path):
        e = self._parsed.get(path)
        if e is None:
            rec = self._index[path]  # KeyError for unknown paths
            e = self._a._parse(rec[-3], rec[-2], rec[-1])
            self._parsed[path] = e
        return e

    def __iter__(self):
        return iter(self._index)

    def __len__(self):
        return len(self._index)

    def __contains__(self, path):
        return path in self._index


class Analysis:
    """A cached analysis of one tree.

    Attributes: ``tree`` (Path), ``meta`` (dict: key, created, timing,
    counts), ``kinds`` ({path: kind}), ``origins`` ({path: [(Makefile,
    variable or rule)]}), ``conds`` ({path: z3 expr}, lazy), ``reached``
    ({Makefile relative to tree: condition under which it is analyzed}),
    ``builtin`` ({Makefile: condition under which it is reached through obj-y
    only}; empty unless the tree sets need_builtin).
    """

    def __init__(self, tree, cdir, meta, smt_path):
        self.tree = tree
        self.cache_dir = cdir
        self._meta = meta
        self._smt_path = smt_path
        self._smt = None
        self._vars = None
        self._settings = None
        self.meta = {k: meta[k] for k in ("format", "key", "created", "analysis_seconds",
                                          "counts")}
        self.kinds = {p: r[0] for p, r in meta["objects"].items()}
        self.origins = {p: [tuple(o) for o in r[1]] for p, r in meta["objects"].items()}
        self.conds = LazyConds(self, "objects")
        self.reached = LazyConds(self, "reached")
        self.builtin = LazyConds(self, "builtin")

    # -- parsing
    def _text(self, off, length):
        if self._smt is None:
            self._smt = self._smt_path.read_bytes()
        return self._smt[off:off + length].decode()

    def _var_consts(self):
        if self._vars is None:
            sorts = {name: _get_sort(name, cons) for name, cons in self._meta["sorts"].items()}
            self._sorts = sorts
            self._vars = [(name, sorts[s]) for name, s in self._meta["vars"]]
            self._consts = {}
        return self._vars

    def _parse(self, var_ids, off, length):
        variables = self._var_consts()
        decls, sorts = {}, {}
        for i in var_ids:
            c = self._consts.get(i)
            name, sort = variables[i]
            if c is None:
                c = self._consts[i] = z3.Const(name, sort)
            decls[name] = c
            sorts[sort.name()] = sort  # declares the sort's constructors too
        text = self._text(off, length)
        if text == "true":
            return z3.BoolVal(True)
        if text == "false":
            return z3.BoolVal(False)
        return z3.parse_smt2_string(f"(assert {text})", sorts=sorts, decls=decls)[0]

    # -- convenience
    def cond(self, path):
        return self.conds[path]

    def settings(self):
        """``settings.Settings`` for the tree (needed by ZSolver/KconfigSMT)."""
        if self._settings is None:
            import settings
            self._settings = settings.Settings(self.tree,
                                               use_tristate=self.meta["key"]["options"]["use_tristate"])
        return self._settings

    def solver(self):
        from helpers import zsolver
        return zsolver.ZSolver(self.settings())

    def symbols(self, path):
        """Names of the variables in ``path``'s condition."""
        rec = self._meta["objects"][path]
        return sorted(self._meta["vars"][i][0] for i in rec[2])

    def predicted(self, config, paths=None):
        """Paths (among ``paths``, default all) built under ``config``, a
        ``.config`` path or a {CONFIG_X: value} dict; the semantics are
        ``objects.predicted_objects`` (unset options are undef)."""
        from objects import predicted_objects
        paths = list(self.conds) if paths is None else list(paths)
        targets = {p: self.conds[p] for p in paths}
        runner = _SettingsOnly(self.settings())
        if isinstance(config, Mapping):
            with tempfile.NamedTemporaryFile("w", suffix=".config", delete=False) as f:
                f.write("".join(f"{k}={v}\n" for k, v in config.items()))
                name = f.name
            try:
                return predicted_objects(runner, targets, name)
            finally:
                os.unlink(name)
        return predicted_objects(runner, targets, str(config))

    def is_built(self, path, config):
        return path in self.predicted(config, [path])


class _SettingsOnly:
    """The part of a Run that objects.predicted_objects uses."""

    def __init__(self, mysettings):
        self.mysettings = mysettings


# ---------------------------------------------------------------- analyze

def _record_reads():
    """Patch the analyzer's Makefile reader to record every file it reads."""
    import kbuild
    original = kbuild.read_makefile_text
    read = set()

    def reader(path):
        read.add(str(pathlib.Path(path).resolve()))
        return original(path)
    kbuild.read_makefile_text = reader

    def restore():
        kbuild.read_makefile_text = original
    return read, restore


def _capture_builtin():
    import objects
    original = objects.builtin_guards
    box = {}

    def wrapper(runner):
        box["guards"] = original(runner)
        return box["guards"]
    objects.builtin_guards = wrapper

    def restore():
        objects.builtin_guards = original
    return box, restore


def run_analysis(tree, use_tristate=True):
    """Analyze ``tree`` without the cache. Returns a dict with ``conds``,
    ``kinds``, ``origins`` ({path: set of (Makefile, what)}), ``reached`` and
    ``builtin`` ({Makefile rel: cond}), ``files`` (resolved paths read), and
    ``seconds``."""
    from alg import Run
    import objects
    tree = tree_root(tree)
    read, restore_reads = _record_reads()
    box, restore_builtin = _capture_builtin()
    t0 = time.monotonic()
    tmp = None
    try:
        runner = Run(tree, use_tristate=use_tristate)
        tmp = runner.go()
        origins = {}
        conds, kinds = objects.object_conditions(runner, origins=origins)
    finally:
        restore_reads()
        restore_builtin()
        if tmp is not None:
            shutil.rmtree(str(tmp), ignore_errors=True)
    seconds = time.monotonic() - t0
    for mk, _ in runner.makefiles:
        read.add(str(pathlib.Path(mk).resolve()))
    ini = pathlib.Path(os.environ.get("KFOLD_SETTINGS_FILE") or tree / "skbuild.ini")
    reached = {_rel(mk, tree): c for mk, c in getattr(runner, "reached_conditions", {}).items()}
    builtin = {_rel(mk, tree): c for mk, c in box.get("guards", {}).items()}
    return {"tree": tree, "conds": conds, "kinds": kinds, "origins": origins,
            "reached": reached, "builtin": builtin, "files": read,
            "settings_file": ini, "seconds": seconds}


def _as_expr(c):
    if isinstance(c, z3.ExprRef):
        return c
    return z3.BoolVal(bool(c))


def analyze(tree, cache_root=None, use_tristate=True, force=False, log=None):
    """Analyze ``tree`` and write its cache; return the loaded Analysis.
    Reuses a valid cache unless ``force``."""
    tree = tree_root(tree)
    if not force:
        a = load(tree, cache_root)
        if a is not None:
            return a
    if log:
        log(f"analyzing {tree} ...")
    res = run_analysis(tree, use_tristate=use_tristate)
    cdir = cache_dir_for(tree, cache_root)
    write(cdir, res, use_tristate)
    if log:
        log(f"analyzed {len(res['conds'])} objects in {res['seconds']:.1f}s; "
            f"cache {cdir}")
    a = load(tree, cache_root)
    assert a is not None, cdir
    return a


def write(cdir, res, use_tristate):
    tree = res["tree"]
    sorts, var_ids, variables = {}, {}, []
    blob, offset = [], 0
    nodes = _Nodes()

    def store(expr):
        nonlocal offset
        expr = _as_expr(expr)
        ids, found = [], []
        text = expr_to_smt(expr, found, nodes).encode()
        for v in found:
            name, sort = str(v), v.sort()
            if name not in var_ids:
                sname = sort.name()
                if sname not in sorts:
                    sorts[sname] = [sort.constructor(j).name() for j in range(sort.num_constructors())]
                var_ids[name] = len(variables)
                variables.append([name, sname])
            ids.append(var_ids[name])
        rec = [sorted(ids), offset, len(text)]
        blob.append(text + b"\n")
        offset += len(text) + 1
        return rec

    objects = {}
    for p in sorted(res["conds"]):
        origins = sorted([list(o) for o in res["origins"].get(p, ())])
        objects[p] = [res["kinds"][p], origins] + store(res["conds"][p])
    reached = {mk: store(c) for mk, c in sorted(res["reached"].items())}
    builtin = {mk: store(c) for mk, c in sorted(res["builtin"].items())}
    files = {}
    for f in sorted(res["files"]) + [str(res["settings_file"])]:
        try:
            files[_rel(f, tree)] = _stat(f)
        except OSError:
            files[_rel(f, tree)] = None  # must stay absent
    meta = {
        "format": FORMAT_VERSION,
        "key": {"tree": str(tree), "analyzer": analyzer_digest(),
                "options": options_key(use_tristate)},
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "analysis_seconds": round(res["seconds"], 2),
        "counts": {"objects": len(objects), "makefiles": len(reached), "files": len(files),
                   "variables": len(variables)},
        "files": files, "sorts": sorts, "vars": variables,
        "objects": objects, "reached": reached, "builtin": builtin,
    }
    cdir.parent.mkdir(parents=True, exist_ok=True)
    tmp = pathlib.Path(tempfile.mkdtemp(dir=cdir.parent, prefix=cdir.name + ".tmp"))
    try:
        (tmp / CONDS).write_bytes(b"".join(blob))
        (tmp / META).write_text(json.dumps(meta, separators=(",", ":")))
        if cdir.exists():
            shutil.rmtree(cdir)
        os.replace(tmp, cdir)
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------- load

def status(tree, cache_root=None, use_tristate=True):
    """(meta or None, reason): reason is None for a valid cache, else why it
    cannot be used."""
    tree = tree_root(tree)
    cdir = cache_dir_for(tree, cache_root)
    mfile = cdir / META
    if not mfile.is_file() or not (cdir / CONDS).is_file():
        return None, "no cache"
    try:
        meta = json.loads(mfile.read_text())
    except (OSError, ValueError) as e:
        return None, f"unreadable cache ({e})"
    if meta.get("format") != FORMAT_VERSION:
        return meta, f"cache format {meta.get('format')} != {FORMAT_VERSION}"
    key = meta.get("key", {})
    if key.get("tree") != str(tree):
        return meta, "cache is for another tree"
    if key.get("options") != options_key(use_tristate):
        return meta, "analysis options changed"
    if key.get("analyzer") != analyzer_digest():
        return meta, "kfold analyzer changed"
    for rel, st in meta.get("files", {}).items():
        p = tree / rel
        if st is None:
            if p.exists():
                return meta, f"{rel} appeared"
            continue
        try:
            if _stat(p) != st:
                return meta, f"{rel} changed"
        except OSError:
            return meta, f"{rel} removed"
    return meta, None


def load(tree, cache_root=None, use_tristate=True, check=True):
    """The cached Analysis of ``tree``, or None if missing or stale
    (``check=False`` skips the staleness test, not the format check)."""
    tree = tree_root(tree)
    cdir = cache_dir_for(tree, cache_root)
    if check:
        meta, reason = status(tree, cache_root, use_tristate)
        if reason is not None:
            return None
    else:
        try:
            meta = json.loads((cdir / META).read_text())
        except (OSError, ValueError):
            return None
        if meta.get("format") != FORMAT_VERSION:
            return None
    return Analysis(tree, cdir, meta, cdir / CONDS)


def load_or_analyze(tree, cache_root=None, use_tristate=True, auto=True, log=None):
    """Load the cache, (re)analyzing if it is missing or stale and ``auto``;
    raises CacheError otherwise."""
    tree = tree_root(tree)
    meta, reason = status(tree, cache_root, use_tristate)
    if reason is None:
        return Analysis(tree, cache_dir_for(tree, cache_root), meta,
                        cache_dir_for(tree, cache_root) / CONDS)
    if not auto:
        raise CacheError(f"{tree}: {reason}; run `kfold analyze {tree}`")
    if log:
        log(f"{reason}")
    return analyze(tree, cache_root, use_tristate=use_tristate, force=True, log=log)


def clear(tree, cache_root=None):
    cdir = cache_dir_for(tree, cache_root)
    if cdir.exists():
        shutil.rmtree(cdir)
        return True
    return False


def _stderr(msg):
    print(msg, file=sys.stderr)


# ---------------------------------------------------------------- verify

def verify(analysis, fresh=None, timeout_ms=60000):
    """Compare a cached Analysis with a fresh run (``run_analysis`` output,
    computed if not given): per object, the cached condition must be
    Z3-equivalent to the fresh one and kinds/origins must agree. Returns
    counts plus up to 20 example mismatches."""
    if fresh is None:
        fresh = run_analysis(analysis.tree,
                             use_tristate=analysis.meta["key"]["options"]["use_tristate"])
    out = {"objects": len(fresh["conds"]), "identical": 0, "proved": 0, "differ": 0,
           "unknown": 0, "missing": 0, "extra": 0, "kind_mismatch": 0,
           "origin_mismatch": 0, "makefiles": 0, "makefile_differ": 0, "examples": []}
    s = z3.Solver()
    s.set("timeout", timeout_ms)

    def same(a, b):
        if a.get_id() == b.get_id():
            return "identical"
        s.push()
        s.add(a != b)
        r = s.check()
        s.pop()
        return "proved" if r == z3.unsat else "differ" if r == z3.sat else "unknown"

    for p, c in fresh["conds"].items():
        if p not in analysis.conds:
            out["missing"] += 1
            out["examples"].append(("missing", p))
            continue
        r = same(analysis.conds[p], _as_expr(c))
        out[r] += 1
        if r in ("differ", "unknown"):
            out["examples"].append((r, p))
        if analysis.kinds[p] != fresh["kinds"][p]:
            out["kind_mismatch"] += 1
            out["examples"].append(("kind", p))
        if set(analysis.origins[p]) != set(fresh["origins"].get(p, ())):
            out["origin_mismatch"] += 1
            out["examples"].append(("origins", p))
    out["extra"] = len(set(analysis.conds) - set(fresh["conds"]))
    for mk, c in list(fresh["reached"].items()) + [("builtin:" + k, v) for k, v in fresh["builtin"].items()]:
        out["makefiles"] += 1
        table = analysis.builtin if mk.startswith("builtin:") else analysis.reached
        key = mk[len("builtin:"):] if mk.startswith("builtin:") else mk
        if key not in table or same(table[key], _as_expr(c)) in ("differ", "unknown"):
            out["makefile_differ"] += 1
            out["examples"].append(("makefile", mk))
    out["examples"] = out["examples"][:20]
    out["ok"] = not any(out[k] for k in ("differ", "unknown", "missing", "extra", "kind_mismatch",
                                         "origin_mismatch", "makefile_differ"))
    return out
