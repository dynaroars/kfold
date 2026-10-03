"""The kfold command dispatcher and the analyze/query commands."""
import json
import pathlib
import shutil
import sys

import pytest

from cli import commands, common, main

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAPER = ROOT / "tests" / "paper_example"


@pytest.fixture
def tree(tmp_path):
    d = tmp_path / "tree"
    shutil.copytree(PAPER, d)
    return d


@pytest.fixture
def run(tmp_path, capsys):
    def go(*argv):
        rc = main.main(["--cache-dir", str(tmp_path / "cache"), *map(str, argv)])
        out, err = capsys.readouterr()
        return rc, out, err
    return go


def test_discovers_commands():
    names = [n for n, _ in main.discover()]
    assert {"analyze", "query"} <= set(names)


def test_broken_command_module_is_skipped(tmp_path, monkeypatch, capsys):
    pkg = tmp_path / "extra"
    pkg.mkdir()
    (pkg / "zzbroken.py").write_text("raise RuntimeError('boom')\n")
    (pkg / "zzhello.py").write_text(
        "def register(sub):\n"
        "    p = sub.add_parser('zzhello')\n"
        "    p.set_defaults(func=lambda a: print('hi', a.cache_dir) or 0)\n")
    monkeypatch.setattr(commands, "__path__", list(commands.__path__) + [str(pkg)])
    monkeypatch.delenv("KFOLD_DEBUG", raising=False)
    for m in ("cli.commands.zzbroken", "cli.commands.zzhello"):
        sys.modules.pop(m, None)
    rc = main.main(["zzhello", "--cache-dir", "X"])
    out, err = capsys.readouterr()
    assert rc == 0 and out.strip() == "hi X"
    assert "zzbroken" in err


def test_no_command_prints_help(run):
    rc, out, _ = run()
    assert rc == 2 and "analyze" in out and "query" in out


def test_analyze_then_query(run, tree):
    rc, out, err = run("analyze", tree)
    assert rc == 0 and "written" in out
    rc, out, _ = run("analyze", tree, "--status")
    assert rc == 0 and "valid" in out
    rc, out, _ = run("analyze", tree)
    assert rc == 0 and "cache is valid" in out
    rc, out, _ = run("query", "probe64.o", "--tree", tree, "--no-analyze")
    assert rc == 0
    assert "probe64.o  (target)" in out and "CONFIG_A!=y" in out and "obj-y" in out


def test_query_json_with_config(run, tree, tmp_path):
    cfg = tmp_path / "cfg"
    cfg.write_text("CONFIG_A=y\n")
    rc, out, _ = run("query", tree / "probe32.c", "--config", cfg, "--json")
    assert rc == 0
    d = json.loads(out)
    assert d["object"] == "probe32.o" and d["kind"] == "target"
    assert d["config"]["built"] is True and d["config"]["values"] == {"CONFIG_A": "y"}
    assert d["origins"] == [{"makefile": "Makefile", "via": "obj-y"}]
    rc, out, _ = run("query", "probe64.o", "-C", tree, "-c", cfg, "--json")
    assert json.loads(out)["config"]["built"] is False


def test_query_unknown_object(run, tree):
    rc, _, err = run("query", "probe6.o", "-C", tree)
    assert rc == 1 and "did you mean" in err and "probe64.o" in err


def test_query_no_analyze_without_cache(run, tree):
    rc, _, err = run("query", "scan.o", "-C", tree, "--no-analyze")
    assert rc == 2 and "kfold analyze" in err


def test_resolve_tree_from_file_hint(tree, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert common.resolve_tree(None, hint=tree / "probe32.c") == tree.resolve()


def test_format_cond():
    import z3
    from helpers import zsolver
    S, (y, m, u) = zsolver._get_enum_sort("TriState", ["y", "m", "undef"])
    a, b = z3.Const("CONFIG_A", S), z3.Const("CONFIG_B", S)
    e = z3.And(z3.Or(a == y, a == m), z3.Not(b == u), z3.Or(b == y, z3.And(a == y, b == m)))
    assert common.format_cond(e) == \
        "CONFIG_A=y|m && CONFIG_B!=n && (CONFIG_B=y || (CONFIG_A=y && CONFIG_B=m))"
    assert common.format_cond(e, 10) == "CONFIG_..."
