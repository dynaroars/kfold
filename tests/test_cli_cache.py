"""The kfold analysis cache: round trip, staleness, and evaluation."""
import os
import pathlib
import shutil
import time

import pytest
import z3

from cli import cache

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAPER = ROOT / "tests" / "paper_example"


def equivalent(a, b):
    if a.get_id() == b.get_id():
        return True
    s = z3.Solver()
    s.add(a != b)
    return s.check() == z3.unsat


@pytest.fixture
def tree(tmp_path):
    d = tmp_path / "tree"
    shutil.copytree(PAPER, d)
    return d


@pytest.fixture
def root(tmp_path):
    return tmp_path / "cache"


def test_round_trip_matches_fresh_analysis(tree, root):
    a = cache.analyze(tree, root)
    fresh = cache.run_analysis(tree)
    assert set(a.conds) == set(fresh["conds"]) and len(a.conds) > 5
    assert a.kinds == fresh["kinds"]
    for p, c in fresh["conds"].items():
        assert equivalent(a.conds[p], cache._as_expr(c)), p
        assert set(a.origins[p]) == fresh["origins"].get(p, set())
    assert set(a.reached) == set(fresh["reached"])
    for mk, c in fresh["reached"].items():
        assert equivalent(a.reached[mk], cache._as_expr(c))


def test_known_conditions(tree, root):
    a = cache.analyze(tree, root)
    assert z3.is_true(a.conds["scan.o"])
    assert a.kinds["probe64.o"] == "target"
    assert ("Makefile", "obj-y") in a.origins["probe64.o"]
    assert a.symbols("probe64.o") == ["CONFIG_A"]


def test_loaded_exprs_share_analyzer_sorts(tree, root):
    """Cached conditions use the same enum sorts as ZSolver.get_sort, so they
    combine with the analyzer's (and KconfigSMT's) variables."""
    a = cache.analyze(tree, root)
    zvar, values = a.solver().get_sort("CONFIG_A")
    s = z3.Solver()
    s.add(a.conds["probe64.o"], zvar == values["y"])
    assert s.check() == z3.unsat


def test_reuse_and_staleness(tree, root):
    a = cache.analyze(tree, root)
    assert cache.status(tree, root)[1] is None
    assert cache.load(tree, root) is not None
    created = (a.cache_dir / cache.META).stat().st_mtime_ns
    cache.analyze(tree, root)  # valid cache: not rewritten
    assert (a.cache_dir / cache.META).stat().st_mtime_ns == created
    mk = tree / "Makefile"
    mk.write_text(mk.read_text() + "obj-$(CONFIG_NEW) += new.o\n")
    st = mk.stat()
    os.utime(mk, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
    meta, reason = cache.status(tree, root)
    assert reason == "Makefile changed"
    assert cache.load(tree, root) is None
    with pytest.raises(cache.CacheError):
        cache.load_or_analyze(tree, root, auto=False)
    b = cache.load_or_analyze(tree, root)
    assert "new.o" in b.conds and "CONFIG_NEW" in b.symbols("new.o")


def test_new_settings_file_invalidates(tmp_path, root):
    d = tmp_path / "noini"
    shutil.copytree(PAPER, d)
    (d / "skbuild.ini").unlink()
    cache.analyze(d, root)
    assert cache.status(d, root)[1] is None
    (d / "skbuild.ini").write_text("[COMMON]\n")
    assert cache.status(d, root)[1] == "skbuild.ini appeared"


def test_format_and_analyzer_key(tree, root, monkeypatch):
    cache.analyze(tree, root)
    monkeypatch.setattr(cache, "FORMAT_VERSION", cache.FORMAT_VERSION + 1)
    assert "format" in cache.status(tree, root)[1]
    monkeypatch.undo()
    monkeypatch.setattr(cache, "_ANALYZER_DIGEST", "other")
    assert cache.status(tree, root)[1] == "kfold analyzer changed"


def test_predicted_under_config(tree, root, tmp_path):
    a = cache.analyze(tree, root)
    cfg = tmp_path / ".config"
    cfg.write_text("CONFIG_A=y\n# CONFIG_B is not set\nCONFIG_C=m\nCONFIG_MODULES=y\n")
    built = a.predicted(cfg)
    assert {"scan.o", "probe32.o", "1.o", "3.o", "4.o"} <= built
    assert "probe64.o" not in built
    assert a.predicted({"CONFIG_A": "y", "CONFIG_C": "m", "CONFIG_MODULES": "y"}) == built
    assert a.is_built("probe64.o", {})
    assert not a.is_built("probe32.o", {})


def test_expr_to_smt_shares_subterms():
    from helpers import zsolver
    S, (y, m, u) = zsolver._get_enum_sort("TriState", ["y", "m", "undef"])
    xs = [z3.Const(f"CONFIG_{i}", S) for i in range(4)]
    e = z3.Or(xs[0] == y, xs[1] == m)
    for x in xs[2:]:
        e = z3.And(z3.Or(e, x == y), z3.Or(e, x == u))  # exponential as a tree
    text = cache.expr_to_smt(e)
    assert "let" in text and len(text) < len(e.sexpr())
    back = z3.parse_smt2_string(f"(assert {text})", sorts={"TriState": S},
                                decls={str(x): x for x in xs})[0]
    assert back.get_id() == e.get_id()


def test_load_is_fast(tree, root):
    cache.analyze(tree, root)
    t0 = time.monotonic()
    a = cache.load(tree, root)
    a.conds["probe64.o"]
    assert time.monotonic() - t0 < 1.0


def test_verify(tree, root):
    a = cache.analyze(tree, root)
    fresh = cache.run_analysis(tree)
    v = cache.verify(a, fresh)
    # Disjunct order can differ between analyses, so equal conditions are
    # either syntactically identical or proved equivalent.
    assert v["ok"] and v["identical"] + v["proved"] == v["objects"]
    # An equivalent but syntactically different condition is proved equal;
    # a different one is reported.
    c = cache._as_expr(fresh["conds"]["probe64.o"])
    fresh["conds"]["probe64.o"] = z3.Not(z3.Not(c))
    fresh["conds"]["probe32.o"] = z3.BoolVal(True)
    v = cache.verify(a, fresh)
    assert v["proved"] >= 1 and v["differ"] == 1 and v["unknown"] == 0 and not v["ok"]
    assert v["examples"] == [("differ", "probe32.o")]
