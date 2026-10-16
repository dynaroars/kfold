"""kfold config-for: mapping a patch/file list to objects, solving
Phi_Kbuild && Phi_Kconfig for a minimal .config fragment, and (on the Linux
tree) verifying the result against real Kconfig/olddefconfig behavior.

Fast tests run on tests/paper_example (no Kconfig, so only Phi_Kbuild
applies) and on synthetic z3 conditions (solve_targets' conflict handling,
with no tree at all). Linux tests are skipped unless a valid cache exists
for work/prepared/linux-7.2.8 (same convention as tests/test_cli_linux.py).
"""
import json
import pathlib
import shutil

import pytest
import z3

from cli import cache, main
from cli.commands import _configfor_patch as patchmod
from cli.commands import _configfor_verify as verifymod
from cli.commands import config_for as cf

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAPER = ROOT / "tests" / "paper_example"
# The analyzed Linux tree and configs of the canonical run (experiments/).
LINUX = ROOT / "work" / "prepared" / "linux-7.2.8"
DEFCONFIG = ROOT / "evidence" / "configs" / "linux" / "defconfig.config"


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


def run_json(run, *argv):
    rc, out, err = run(*argv)
    return rc, json.loads(out), err


# ---------------------------------------------------------------- discovery

def test_registers_command():
    assert "config_for" in [n for n, _ in main.discover()]


# ---------------------------------------------------------------- mapping (paper_example)

def test_maps_source_file_and_emits_fragment(run, tree):
    rc, d, err = run_json(run, "config-for", tree / "1.c", "--tree", tree, "--json")
    assert rc == 0
    assert d["mapped"] == {str(tree / "1.c"): "1.o"}
    # obj-$(CONFIG_1) and obj-$(CONFIG_A) both add 1.o: either is one change.
    assert d["fragment"] in ({"CONFIG_1": "y"}, {"CONFIG_A": "y"})
    assert d["predicted_built"] == ["1.o"]
    assert d["predicted_not_built"] == []
    assert d["used_kconfig"] is False  # paper_example has no Kconfig file


def test_minimizes_toward_a_shared_symbol(run, tree):
    # 1.o is selected by CONFIG_1=y, and also (via the later `:=`)
    # effectively by CONFIG_A; 3.o only by CONFIG_A. Asking for 1.o and 3.o
    # together should share CONFIG_A rather than pay for CONFIG_1 as well.
    rc, d, _ = run_json(run, "config-for", tree / "1.c", tree / "3.c", "--tree", tree, "--json")
    assert rc == 0
    assert d["fragment"] == {"CONFIG_A": "y"}

    rc, d2, _ = run_json(run, "config-for", tree / "1.c", tree / "2.c", "--tree", tree, "--json")
    assert rc == 0
    assert d2["fragment"] == {"CONFIG_1": "y", "CONFIG_2": "y"}


def test_base_config_avoids_redundant_changes(run, tree, tmp_path):
    base = tmp_path / "base.config"
    base.write_text("CONFIG_1=y\n")
    rc, d, _ = run_json(run, "config-for", tree / "1.c", "--tree", tree, "--base", str(base), "--json")
    assert rc == 0
    assert d["fragment"] == {}  # already satisfied by the base


def test_unknown_file_reported(run, tree):
    rc, d, err = run_json(run, "config-for", tree / "nope.c", "--tree", tree, "--json")
    assert rc == 1
    assert d["unmapped"] and d["unmapped"][0]["path"] == str(tree / "nope.c")


def test_patch_input_extracts_touched_files_and_flags_headers(run, tree, tmp_path):
    patch = tmp_path / "p.diff"
    patch.write_text(
        "diff --git a/2.c b/2.c\n"
        "--- a/2.c\n"
        "+++ b/2.c\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
        "diff --git a/newhdr.h b/newhdr.h\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/newhdr.h\n"
        "@@ -0,0 +1 @@\n"
        "+int x;\n")
    rc, d, _ = run_json(run, "config-for", str(patch), "--tree", tree, "--json")
    assert rc == 0
    assert d["mapped"] == {"2.c": "2.o"}
    assert d["headers_not_compiled"] == ["newhdr.h"]
    assert d["fragment"] == {"CONFIG_2": "y"}


def test_stdin_patch(run, tree, monkeypatch):
    import io
    import sys
    monkeypatch.setattr(sys, "stdin", io.StringIO(
        "--- a/1.c\n+++ b/1.c\n@@ -1 +1 @@\n-a\n+b\n"))
    rc, d, _ = run_json(run, "config-for", "-", "--tree", tree, "--json")
    assert rc == 0
    assert d["mapped"] == {"1.c": "1.o"}


# ---------------------------------------------------------------- helper unit tests

def test_touched_paths_skips_deleted_files():
    text = ("diff --git a/a.c b/a.c\n--- a/a.c\n+++ b/a.c\n@@ -1 +1 @@\n-x\n+y\n"
            "diff --git a/b.c b/b.c\n--- a/b.c\n+++ /dev/null\n")
    assert patchmod.touched_paths(text) == ["a.c"]


def test_looks_like_patch():
    assert patchmod.looks_like_patch("--- a/x.c\n+++ b/x.c\n")
    assert not patchmod.looks_like_patch("just some text\nwith no diff markers\n")


def test_merge_config_text_replaces_and_appends():
    base = "CONFIG_A=y\n# CONFIG_B is not set\nCONFIG_C=m\n"
    merged = verifymod.merge_config_text(base, {"CONFIG_A": "", "CONFIG_B": "y", "CONFIG_D": "m"})
    lines = merged.splitlines()
    assert "# CONFIG_A is not set" in lines
    assert "CONFIG_B=y" in lines
    assert "CONFIG_C=m" in lines
    assert "CONFIG_D=m" in lines


def test_solve_targets_excludes_conflicting_objects():
    # No Kconfig involved: pure Phi_Kbuild conflict, X and Y cannot both hold.
    X, Y, Z = z3.Bools("CONFIG_X CONFIG_Y CONFIG_Z")
    objs_conds = {
        "a.o": X,
        "b.o": z3.Not(X),
        "c.o": Z,
    }
    included, excluded = cf.solve_targets(objs_conds, z3.BoolVal(True))
    assert set(included) | set(excluded) == {"a.o", "b.o", "c.o"}
    assert len(included) == 2 and "c.o" in included
    assert len(excluded) == 1
    dropped = next(iter(excluded))
    assert dropped in ("a.o", "b.o")
    assert "conflicts with" in excluded[dropped]


def test_solve_targets_reports_solo_unsat():
    X = z3.Bool("CONFIG_X")
    objs_conds = {"impossible.o": z3.And(X, z3.Not(X))}
    included, excluded = cf.solve_targets(objs_conds, z3.BoolVal(True))
    assert included == {}
    assert "impossible under any configuration" in excluded["impossible.o"]


# ---------------------------------------------------------------- Linux tree

pytestmark_linux = pytest.mark.skipif(not (LINUX / "Makefile").is_file(),
                                      reason="work/prepared/linux-7.2.8 is absent (run experiments/fetch.py)")


@pytest.fixture(scope="module")
def linux_analysis():
    if not (LINUX / "Makefile").is_file():
        pytest.skip("work/prepared/linux-7.2.8 is absent (run experiments/fetch.py)")
    a = cache.load(LINUX)
    if a is None:
        pytest.skip("no valid Linux cache; run `kfold analyze work/prepared/linux-7.2.8`")
    return a


@pytest.fixture
def linux_run(capsys):
    def go(*argv):
        rc = main.main([*map(str, argv)])
        out, err = capsys.readouterr()
        return rc, out, err
    return go


def _linux_json(linux_run, *argv):
    rc, out, err = linux_run(*argv)
    return rc, json.loads(out), err


@pytestmark_linux
def test_ext2_xattr_needs_non_default_symbols(linux_analysis, linux_run):
    if not DEFCONFIG.is_file():
        pytest.skip(f"{DEFCONFIG} is absent")
    rc, d, _ = _linux_json(linux_run, "config-for", "fs/ext2/xattr.c", "--tree", str(LINUX),
                           "--base", str(DEFCONFIG), "--json")
    assert rc == 0
    assert d["mapped"] == {"fs/ext2/xattr.c": "fs/ext2/xattr.o"}
    # EXT2_FS is tristate and defconfig has MODULES=y, so y and m are equally
    # small changes; EXT2_FS_XATTR is bool, so it is y either way.
    assert set(d["fragment"]) == {"CONFIG_EXT2_FS", "CONFIG_EXT2_FS_XATTR"}
    assert d["fragment"]["CONFIG_EXT2_FS"] in ("y", "m")
    assert d["fragment"]["CONFIG_EXT2_FS_XATTR"] == "y"
    assert d["predicted_built"] == ["fs/ext2/xattr.o"]
    assert d["used_kconfig"] is True


@pytestmark_linux
def test_conflicting_arch_objects_are_excluded_not_both_built(linux_analysis, linux_run):
    if not DEFCONFIG.is_file():
        pytest.skip(f"{DEFCONFIG} is absent")
    rc, d, _ = _linux_json(linux_run, "config-for", "arch/x86/entry/entry_32.S",
                           "arch/x86/entry/entry_64.S", "--tree", str(LINUX),
                           "--base", str(DEFCONFIG), "--json")
    assert rc == 1  # something was excluded
    objs = set(d["objects"])
    assert objs == {"arch/x86/entry/entry_32.o", "arch/x86/entry/entry_64.o"}
    assert len(d["excluded"]) == 1
    kept = objs - set(d["excluded"])
    assert d["predicted_built"] == list(kept)


@pytestmark_linux
def test_patch_maps_multiple_real_objects(linux_analysis, linux_run, tmp_path):
    patch = tmp_path / "ext4.diff"
    patch.write_text(
        "diff --git a/fs/ext4/inode.c b/fs/ext4/inode.c\n"
        "--- a/fs/ext4/inode.c\n+++ b/fs/ext4/inode.c\n"
        "@@ -1 +1 @@\n-x\n+y\n"
        "diff --git a/fs/ext4/extents.c b/fs/ext4/extents.c\n"
        "--- a/fs/ext4/extents.c\n+++ b/fs/ext4/extents.c\n"
        "@@ -1 +1 @@\n-x\n+y\n")
    rc, d, _ = _linux_json(linux_run, "config-for", str(patch), "--tree", str(LINUX), "--json")
    assert rc == 0
    assert set(d["mapped"].values()) == {"fs/ext4/inode.o", "fs/ext4/extents.o"}
    assert d["predicted_not_built"] == []


@pytestmark_linux
def test_verify_survives_olddefconfig(linux_analysis, linux_run):
    if not DEFCONFIG.is_file():
        pytest.skip(f"{DEFCONFIG} is absent")
    rc, d, err = _linux_json(linux_run, "config-for", "fs/ext2/xattr.c", "--tree", str(LINUX),
                             "--base", str(DEFCONFIG), "--verify", "--json")
    assert rc == 0, err
    v = d["verify"]
    assert v["olddefconfig_rc"] == 0
    assert v["lost"] == {}
    assert v["kfold_predicted_all_built"] is True
