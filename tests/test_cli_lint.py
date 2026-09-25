"""kfold lint: zombie symbols, orphan sources, dead objects, and --diff.

Synthetic checks run against tests/lint_fixtures/basic (a tiny Kbuild+Kconfig
tree crafted to exercise each finding class exactly once, plus one clean
case per class to bound false positives). Real-Linux checks are skipped
unless results/workspaces/linux has a valid cache (see test_cli_linux.py).
"""
import json
import pathlib
import shutil

import pytest

from cli import main

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "lint_fixtures" / "basic"
LINUX = ROOT / "results" / "workspaces" / "linux"


@pytest.fixture
def tree(tmp_path):
    d = tmp_path / "tree"
    shutil.copytree(FIXTURE, d)
    return d


@pytest.fixture
def run(tmp_path, capsys):
    def go(*argv):
        rc = main.main(["--cache-dir", str(tmp_path / "cache"), *map(str, argv)])
        out, err = capsys.readouterr()
        return rc, out, err
    return go


def _findings(out, cls=None):
    d = json.loads(out)
    fs = d["findings"]
    return [f for f in fs if cls is None or f["class"] == cls]


def test_zombie_check(run, tree):
    rc, out, _ = run("lint", "--tree", tree, "--json")
    assert rc == 0
    zf = _findings(out, "zombie")
    assert {(f["symbol"], f["file"], f["line"]) for f in zf} == {("CONFIG_BAR_ZOMBIE", "Makefile", 2)}
    assert zf[0]["severity"] == "error" and not zf[0]["arch_only"]


def test_orphan_check(run, tree):
    rc, out, _ = run("lint", "--tree", tree, "--json")
    of = _findings(out, "orphan")
    assert {f["file"] for f in of} == {"orphan.c"}
    # included.c is #included by foo.c and must not be flagged, even though
    # no Makefile lists it directly.
    assert "included.c" not in {f["file"] for f in of}
    # bar.c/baz.c/dead.c/foo.c are all referenced (directly or via the
    # zombie/dead CONFIG_ guards, which still make them Kbuild objects).
    assert not ({"bar.c", "baz.c", "dead.c", "foo.c"} & {f["file"] for f in of})


def test_dead_check(run, tree):
    rc, out, _ = run("lint", "--tree", tree, "--json")
    df = _findings(out, "dead")
    by_obj = {f["file"]: f for f in df}
    assert by_obj["kbdead.o"]["status"] == "kbuild"
    assert by_obj["dead.o"]["status"] == "kconfig"
    assert not by_obj["kbdead.o"]["incomplete"] and not by_obj["dead.o"]["incomplete"]
    # foo.o/baz.o/bar.o are all satisfiable and must not be reported dead.
    assert not ({"foo.o", "baz.o", "bar.o"} & set(by_obj))


def test_counts_match_findings(run, tree):
    rc, out, _ = run("lint", "--tree", tree, "--json")
    d = json.loads(out)
    assert d["counts"]["zombie"] == 1
    assert d["counts"]["zombie_arch_only"] == 0
    assert d["counts"]["orphan"] == 1
    assert d["counts"]["dead"] == 2
    assert d["counts"]["dead_incomplete"] == 0


def test_only_restricts_classes(run, tree):
    rc, out, _ = run("lint", "--tree", tree, "--json", "--only", "zombie")
    d = json.loads(out)
    assert set(d["counts"]) == {"zombie", "zombie_arch_only"}
    assert {f["class"] for f in d["findings"]} == {"zombie"}


def test_path_restricts_findings(run, tree):
    rc, out, _ = run("lint", "--tree", tree, "--json", "--path", "bar")
    fs = _findings(out)
    # Only bar.o's own zombie guard is in scope; orphan.c and the dead
    # objects (none named bar*) must be filtered out.
    assert fs and all(f["class"] == "zombie" and f["symbol"] == "CONFIG_BAR_ZOMBIE" for f in fs)


def test_text_output_has_locations(run, tree):
    rc, out, _ = run("lint", "--tree", tree)
    assert "ERROR   zombie  Makefile:2: CONFIG_BAR_ZOMBIE" in out
    assert "WARNING orphan  orphan.c" in out
    assert "dead.o is unsatisfiable under Kbuild and Kconfig" in out


# ---------------------------------------------------------------- --diff

def _write_patch(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return p


NEW_ZOMBIE_PATCH = """\
diff --git a/Makefile b/Makefile
index 1111111..2222222 100644
--- a/Makefile
+++ b/Makefile
@@ -1,4 +1,5 @@
 obj-$(CONFIG_FOO) += foo.o
 obj-$(CONFIG_BAR_ZOMBIE) += bar.o
+obj-$(CONFIG_NOPE) += x.o
 obj-y += baz.o

"""

GUARD_CHANGE_PATCH = """\
diff --git a/Makefile b/Makefile
index 1111111..3333333 100644
--- a/Makefile
+++ b/Makefile
@@ -6,7 +6,7 @@
 # Nested contradiction: CONFIG_FOO == y AND CONFIG_FOO == undef -> UNSAT
 # under Kbuild alone (a "kbuild"-class dead object).
 ifeq ($(CONFIG_FOO),y)
-ifeq ($(CONFIG_FOO),)
+ifeq ($(CONFIG_BAR_ZOMBIE),)
 obj-y += kbdead.o
 endif
 endif
"""


def test_diff_new_zombie_object(run, tree, tmp_path):
    (tree / "x.c").write_text("int x(void) { return 0; }\n")
    patch = _write_patch(tmp_path, "new_zombie.diff", NEW_ZOMBIE_PATCH)
    rc, out, _ = run("lint", "--tree", tree, "--diff", patch,
                     "--scratch", tmp_path / "scratch", "--json")
    assert rc == 0
    d = json.loads(out)
    changes = {c["object"]: c for c in d["condition_changes"]}
    assert changes["x.o"]["change"] == "added"
    zf = [f for f in d["findings"] if f["class"] == "zombie"]
    assert any(f["symbol"] == "CONFIG_NOPE" and f["line"] == 3 for f in zf)
    # The pre-existing zombie is still reported (it is still in the patched
    # Makefile).
    assert any(f["symbol"] == "CONFIG_BAR_ZOMBIE" for f in zf)


def test_diff_guard_change_fixes_dead_object(run, tree, tmp_path):
    patch = _write_patch(tmp_path, "guard_change.diff", GUARD_CHANGE_PATCH)
    rc, out, _ = run("lint", "--tree", tree, "--diff", patch,
                     "--scratch", tmp_path / "scratch", "--json")
    assert rc == 0
    d = json.loads(out)
    changes = {c["object"]: c for c in d["condition_changes"]}
    assert changes["kbdead.o"]["change"] == "changed"
    assert changes["kbdead.o"]["before"] == "false"
    assert "CONFIG_FOO" in changes["kbdead.o"]["after"]
    # kbdead.o is no longer unsatisfiable after the patch.
    dead_objs = {f["file"] for f in d["findings"] if f["class"] == "dead"}
    assert "kbdead.o" not in dead_objs
    # dead.o (untouched by this patch) is still dead under Kconfig.
    assert "dead.o" in dead_objs


# ---------------------------------------------------------------- Linux smoke

pytestmark_linux = pytest.mark.skipif(not (LINUX / "Makefile").is_file(),
                                      reason="results/workspaces/linux is absent")


@pytestmark_linux
def test_linux_smoke(capsys):
    """A narrow, --path-restricted run against the real cache completes and
    returns well-formed findings (the full-tree run and its manually
    verified numbers are evidence/lint_v6.6.json, generated separately --
    a whole-tree dead-object check is too slow for a unit test)."""
    from cli import cache
    a = cache.load(LINUX)
    if a is None:
        pytest.skip("no valid Linux cache; run `kfold analyze results/workspaces/linux`")
    rc = main.main(["lint", "--tree", str(LINUX), "--json", "--no-analyze",
                    "--path", "fs/ext2/", "--dead-limit", "200"])
    d = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert "counts" in d
    for f in d["findings"]:
        assert f["file"].startswith("fs/ext2/") or f["class"] == "zombie"
        assert f["severity"] in ("error", "warning", "info")


# ---------------------------------------------------------------- regressions
#
# Two bugs were found and fixed while manually verifying the checkpoint 2C
# findings against the real Linux tree; both are cheap to regress-test
# without a full Linux cache.

def test_arch_of_does_not_mislabel_arch_kconfig():
    """arch/Kconfig (and arch/Kconfig.*) is architecture-independent glue
    sourced by every arch, not a declaration scoped to a pseudo-arch named
    "Kconfig" -- a real bug found in checkpoint verification that bucketed
    ~220 common symbols (SMP, KPROBES, HOTPLUG_*, ...) as arch-only."""
    from cli.commands import _lint_kconfig as lk
    assert lk.arch_of("arch/Kconfig") is None
    assert lk.arch_of("arch/Kconfig.debug") is None
    assert lk.arch_of("arch/x86/Kconfig") == "x86"
    assert lk.arch_of("arch/x86/Kconfig.cpu") == "x86"
    assert lk.arch_of("drivers/foo/Kconfig") is None


def test_dead_check_uses_orig_type_not_degraded_type(tmp_path):
    """KconfigConstraints forbids "=m" for bool-typed symbols (a supplement
    to tools/kconfig_solver.KconfigSMT, which does not itself constrain a
    symbol's value away from "m"). kconfiglib dynamically downgrades every
    *declared* tristate symbol's ``.type`` to BOOL once MODULES evaluates to
    not-y, which it always does here (no .config is loaded, so MODULES
    defaults to its unset value) -- checked directly against the real tree
    during checkpoint verification: 16,672 tristate-or-bool symbols, 0
    reporting as TRISTATE via .type. Using .type instead of .orig_type here
    would forbid "=m" for every real tristate symbol in the tree, which
    produced ~2,900 false "dead" findings (e.g. ordinary AES-NI-accelerated
    crypto modules) before the fix."""
    from cli import cache
    from cli.commands import _lint_kconfig as lk
    d = tmp_path / "tree"
    d.mkdir()
    (d / "Makefile").write_text("obj-$(CONFIG_FOO) += foo.o\n")
    (d / "foo.c").write_text("int foo(void) { return 0; }\n")
    (d / "Kconfig").write_text(
        "config MODULES\n\tbool \"modules\"\n\toption modules\n\n"
        "config FOO\n\ttristate \"foo\"\n"
    )
    (d / "skbuild.ini").write_text("[COMMON]\nuse_tristate = yes\n")
    a = cache.analyze(d, tmp_path / "cache")
    kc = lk.KconfigConstraints(d, solver=a.solver())
    # FOO is declared tristate (not bool): building as a module ("=m") must
    # remain satisfiable even though MODULES defaults to unset/off in an
    # unloaded Kconfig parse.
    import z3
    zvar, optd = a.solver().get_sort("CONFIG_FOO")
    s = z3.Solver()
    s.add(zvar == optd["m"], *kc.constraints_for({"FOO"}))
    assert s.check() == z3.sat
    dead = lk.dead_check(a, kc, paths=["foo.o"])
    assert dead == []
