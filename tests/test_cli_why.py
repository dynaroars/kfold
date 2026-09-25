"""kfold why OBJ [--config .config]: the guard chain (directory
reachability + obj-/lib-/member line), and, when not built, the pivotal
symbols and a Kconfig-derived minimal fix.

Fast tests run on tests/paper_example (no Kconfig there, so the Kconfig
explanation/suggestion parts degrade to a reported "no Kconfig" note).
Linux tests reuse an existing cache of results/workspaces/linux (see
tests/test_cli_linux.py) and are skipped without one.
"""
import json
import os
import pathlib
import shutil

import pytest

from cli import cache, main

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAPER = ROOT / "tests" / "paper_example"
LINUX = ROOT / "results" / "workspaces" / "linux"
CONFIGS = ROOT / "results" / "revalidation_builds" / "linux_configs"


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


# ---------------------------------------------------------------- paper_example


def test_discovers_why():
    from cli import main as m
    names = [n for n, _ in m.discover()]
    assert "why" in names


def test_why_no_config_shows_guard_chain(run, tree):
    rc, out, _ = run("why", "probe64.o", "--tree", tree)
    assert rc == 0
    assert "probe64.o  (target)" in out
    assert "guard chain:" in out
    assert "obj-y in Makefile: probe64.o" in out
    assert "CONFIG_A!=y" in out


def test_why_json_shape_no_config(run, tree):
    rc, out, _ = run("why", "probe64.o", "--tree", tree, "--json")
    assert rc == 0
    d = json.loads(out)
    assert d["object"] == "probe64.o" and d["kind"] == "target"
    assert len(d["guard_chain"]) >= 1
    last = d["guard_chain"][-1]
    assert last["makefile"] == "Makefile"
    assert "condition" in last and "config" not in d


def test_why_built(run, tree, tmp_path):
    cfg = tmp_path / "built.cfg"
    cfg.write_text("CONFIG_A=n\n")
    rc, out, _ = run("why", "probe64.o", "--tree", tree, "--config", cfg, "--json")
    assert rc == 0
    d = json.loads(out)
    assert d["config"]["built"] is True
    assert all(g["ok"] is True for g in d["guard_chain"])
    assert "pivotal_symbols" not in d["config"]


def test_why_not_built_finds_pivotal_symbol(run, tree, tmp_path):
    cfg = tmp_path / "notbuilt.cfg"
    cfg.write_text("CONFIG_A=y\n")
    rc, out, _ = run("why", "probe64.o", "--tree", tree, "--config", cfg, "--json")
    assert rc == 0
    d = json.loads(out)
    c = d["config"]
    assert c["built"] is False
    assert c["first_failing_conjunct"]
    assert any(g["ok"] is False for g in d["guard_chain"])
    assert any(p["symbol"] == "CONFIG_A" for p in c["pivotal_symbols"])
    # paper_example has no Kconfig: a reported, non-fatal reason, not a crash.
    assert "kconfig_error" in c


def test_why_no_kconfig_flag_skips_kconfig_lookup(run, tree, tmp_path):
    cfg = tmp_path / "notbuilt.cfg"
    cfg.write_text("CONFIG_A=y\n")
    rc, out, _ = run("why", "probe64.o", "--tree", tree, "--config", cfg,
                     "--json", "--no-kconfig")
    assert rc == 0
    d = json.loads(out)
    assert "kconfig_error" not in d["config"]
    assert "symbol_explanations" not in d["config"]
    assert "suggested_change" not in d["config"]


def test_why_text_output_not_built(run, tree, tmp_path):
    cfg = tmp_path / "notbuilt.cfg"
    cfg.write_text("CONFIG_A=y\n")
    rc, out, _ = run("why", "probe64.o", "--tree", tree, "--config", cfg)
    assert rc == 0
    assert "NOT built" in out
    assert "first failing conjunct" in out
    assert "symbols that alone would fix it" in out


def test_why_unknown_object(run, tree):
    rc, _, err = run("why", "probe6.o", "--tree", tree)
    assert rc == 1 and "did you mean" in err and "probe64.o" in err


def test_why_member_object_guard_chain(run, tree, tmp_path):
    """scan.o is unconditional (obj-y, no ifdefs): built under any config,
    and its guard chain conjuncts should all be trivially true."""
    cfg = tmp_path / "any.cfg"
    cfg.write_text("CONFIG_A=y\n")
    rc, out, _ = run("why", "scan.o", "--tree", tree, "--config", cfg, "--json")
    assert rc == 0
    d = json.loads(out)
    assert d["config"]["built"] is True


# ---------------------------------------------------------------- Linux

pytestmark_linux = pytest.mark.skipif(not (LINUX / "Makefile").is_file(),
                                      reason="results/workspaces/linux is absent")


@pytest.fixture(scope="module")
def analysis():
    if not (LINUX / "Makefile").is_file():
        pytest.skip("results/workspaces/linux is absent")
    a = cache.load(LINUX)
    if a is None:
        if not os.environ.get("KFOLD_TEST_ANALYZE_LINUX"):
            pytest.skip("no valid Linux cache; run `kfold analyze results/workspaces/linux` "
                        "or set KFOLD_TEST_ANALYZE_LINUX=1")
        a = cache.analyze(LINUX)
    return a


def _cfg(profile):
    p = CONFIGS / profile / ".config"
    if not p.is_file():
        pytest.skip(f"{p} is absent")
    return p


def test_why_linux_built_object(analysis, capsys):
    cfg = _cfg("defconfig")
    rc = main.main(["why", "kernel/sched/core.o", "--tree", str(LINUX), "--config", str(cfg),
                    "--json", "--no-analyze", "--no-kconfig"])
    d = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert d["config"]["built"] is True
    assert all(g["ok"] is not False for g in d["guard_chain"])


def test_why_linux_not_built_matches_archived_build(analysis, capsys):
    """fs/ext2/xattr.o is off under defconfig (see tests/test_cli_linux.py);
    the guard chain must (a) agree with the archived build's verdict and
    (b) point at the actual conjunct that fails."""
    cfg = _cfg("defconfig")
    rc = main.main(["why", "fs/ext2/xattr.o", "--tree", str(LINUX), "--config", str(cfg),
                    "--json", "--no-analyze", "--no-kconfig"])
    d = json.loads(capsys.readouterr().out)
    assert rc == 0
    archived = ROOT / "evidence" / "physical_builds" / "defconfig" / "fs/ext2/xattr.o"
    if archived.is_file():
        assert d["config"]["built"] is False
    assert d["config"]["first_failing_conjunct"]
    # fs/ext2/xattr.o needs both EXT2_FS and EXT2_FS_XATTR at once under
    # defconfig, so no single flip fixes it; the guard chain and values
    # should still name both symbols.
    assert {"CONFIG_EXT2_FS", "CONFIG_EXT2_FS_XATTR"} <= set(d["symbols"])
    assert d["config"]["values"]["CONFIG_EXT2_FS"] != "y"


def test_why_linux_kconfig_explanation_and_suggestion(analysis, capsys):
    """With Kconfig enabled: CONFIG_EXT2_FS's depends-on is explained, and a
    minimal .config change is suggested that (per DEVTOOL_PLAN checkpoint
    2A) actually turns the object on."""
    if not (LINUX / "Kconfig").is_file():
        pytest.skip("no top-level Kconfig in the Linux tree")
    cfg = _cfg("defconfig")
    rc = main.main(["why", "fs/ext2/xattr.o", "--tree", str(LINUX), "--config", str(cfg),
                    "--json", "--no-analyze"])
    d = json.loads(capsys.readouterr().out)
    assert rc == 0
    c = d["config"]
    assert not c.get("kconfig_error"), c.get("kconfig_error")
    explained = {e["name"] for e in c["symbol_explanations"] if e["found"]}
    assert "CONFIG_EXT2_FS" in explained
    sc = c["suggested_change"]
    assert sc["diff"], sc["note"]
    from objects import config_values
    new_config = config_values(cfg)
    new_config.update(sc["diff"])
    assert analysis.is_built("fs/ext2/xattr.o", new_config)
