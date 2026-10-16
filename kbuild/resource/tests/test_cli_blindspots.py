"""kfold blindspots: MAINTAINERS parsing/matching on an inline fixture, plus
an end-to-end smoke test against the Linux v6.6 workspace (skipped unless a
valid cache and the standard configs exist, mirroring test_cli_linux.py)."""
import json
import os
import pathlib

import pytest

from cli import cache, main
from cli.commands import _blindspots_maintainers as mnt
from cli.commands import blindspots

ROOT = pathlib.Path(__file__).resolve().parent.parent
# The analyzed Linux tree and configs of the canonical run (experiments/).
LINUX = ROOT / "work" / "prepared" / "linux-7.2.8"
CONFIGS = ROOT / "evidence" / "configs" / "linux"

FIXTURE = """\
NETWORK DRIVER CORE
M:	Core Maintainer <core@example.com>
L:	netdev@example.com
S:	Maintained
F:	drivers/net/

WIDGET NETWORK DRIVER
M:	Widget Person <widget@example.com>
S:	Maintained
F:	drivers/net/widget/
X:	drivers/net/widget/legacy/

WIDGET SINGLE FILE
M:	Single File Person <single@example.com>
S:	Maintained
F:	drivers/net/onefile.c

GLOB DRIVER
M:	Glob Person <glob@example.com>
S:	Maintained
F:	drivers/net/glob*.c

WEIRD NAME DRIVER
M:	Weird Person <weird@example.com>
S:	Maintained
N:	we[ia]rd

THE REST
M:	Rest Person <rest@example.com>
S:	Buried alive in reporters
F:	*
F:	*/
"""


@pytest.fixture(scope="module")
def index():
    entries = mnt.parse(FIXTURE, tree=None)
    return entries, mnt.MaintainersIndex(entries)


def _titles(index, path):
    entries, idx = index
    matched, depth = idx.entries_for(path)
    return sorted(e.title for e in matched), depth


def test_directory_pattern_is_recursive(index):
    titles, _ = _titles(index, "drivers/net/foo/bar.c")
    assert titles == ["NETWORK DRIVER CORE"]


def test_more_specific_directory_wins(index):
    titles, _ = _titles(index, "drivers/net/widget/main.c")
    assert titles == ["WIDGET NETWORK DRIVER"]


def test_exclude_pattern_removes_entry(index):
    # excluded from WIDGET NETWORK DRIVER, so only the broader entry claims it
    titles, _ = _titles(index, "drivers/net/widget/legacy/old.c")
    assert titles == ["NETWORK DRIVER CORE"]


def test_single_file_pattern_is_exact(index):
    titles, _ = _titles(index, "drivers/net/onefile.c")
    assert "WIDGET SINGLE FILE" in titles
    # a file in the same directory with a different name is not an exact match
    titles2, _ = _titles(index, "drivers/net/onefile_extra.c")
    assert "WIDGET SINGLE FILE" not in titles2


def test_single_file_pattern_does_not_match_subdirectory(index):
    """'drivers/net/onefile.c' must not match a deeper path even if it
    happens to start with the same characters (the slash-count rule)."""
    titles, _ = _titles(index, "drivers/net/onefile.c/extra")
    assert "WIDGET SINGLE FILE" not in titles


def test_wildcard_pattern_same_depth_as_directory(index):
    titles, _ = _titles(index, "drivers/net/globby.c")
    assert "GLOB DRIVER" in titles
    # but not a file below another directory
    titles2, _ = _titles(index, "drivers/net/sub/globby.c")
    assert "GLOB DRIVER" not in titles2


def test_n_pattern_matches_anywhere(index):
    # a root-level file: only THE REST's non-directory 'F: *' (depth 0, same
    # as an N: match) competes, so the N: match is not shadowed by a deeper
    # F: match the way it would be under drivers/net/.
    titles, _ = _titles(index, "weirdthing.c")
    assert "WEIRD NAME DRIVER" in titles


def test_catch_all_only_when_nothing_more_specific(index):
    titles, _ = _titles(index, "unrelated/path/file.c")
    assert titles == ["THE REST"]
    # but a path under a claimed directory is NOT also attributed to THE REST
    titles2, _ = _titles(index, "drivers/net/foo/bar.c")
    assert "THE REST" not in titles2


def test_parse_ignores_description_header():
    """The file's own descriptive header (before 'Maintainers List') uses
    indented 'M:'/'F:' lines that must not be parsed as real entries."""
    text = "\tM: *Mail* patches to: FullName <address@domain>\n\tF: pattern\n\n" + FIXTURE
    entries = mnt.parse(text)
    assert [e.title for e in entries] == [
        "NETWORK DRIVER CORE", "WIDGET NETWORK DRIVER", "WIDGET SINGLE FILE",
        "GLOB DRIVER", "WEIRD NAME DRIVER", "THE REST",
    ]


def test_directory_detected_without_trailing_slash(tmp_path):
    (tmp_path / "drivers" / "net").mkdir(parents=True)
    text = "REAL DIR\nM:\tX <x@example.com>\nF:\tdrivers/net\n"
    entries = mnt.parse(text, tree=tmp_path)
    idx = mnt.MaintainersIndex(entries)
    titles, _ = _titles((entries, idx), "drivers/net/sub/file.c")
    assert titles == ["REAL DIR"]


# ---------------------------------------------------------------- classify()

def test_classify_non_x86_arch_symbol():
    class FakeAnalysis:
        def symbols(self, path):
            return ["CONFIG_ARM", "CONFIG_FOO"]
    reason = blindspots.classify(FakeAnalysis(), "drivers/foo/bar.o", True, [("cfg", {})])
    assert "non-x86 arch" in reason


def test_classify_arch_path():
    class FakeAnalysis:
        def symbols(self, path):
            return []
    reason = blindspots.classify(FakeAnalysis(), "arch/arm/kernel/foo.o", True, [("cfg", {})])
    assert reason == "non-x86 arch (arch/arm/)"


# ---------------------------------------------------------------- Linux e2e

_needs_linux = pytest.mark.skipif(not (LINUX / "Makefile").is_file(),
                                  reason="work/prepared/linux-7.2.8 is absent (run experiments/fetch.py)")


@pytest.fixture(scope="module")
def analysis():
    if not (LINUX / "Makefile").is_file():
        pytest.skip("work/prepared/linux-7.2.8 is absent (run experiments/fetch.py)")
    a = cache.load(LINUX)
    if a is None:
        if not os.environ.get("KFOLD_TEST_ANALYZE_LINUX"):
            pytest.skip("no valid Linux cache; run `kfold analyze work/prepared/linux-7.2.8` "
                        "or set KFOLD_TEST_ANALYZE_LINUX=1")
        a = cache.analyze(LINUX)
    return a


@_needs_linux
def test_source_path_maps_object_to_c(analysis):
    assert blindspots.source_path(LINUX, "fs/ext2/xattr.o") == "fs/ext2/xattr.c"


@_needs_linux
def test_blindspots_cli_on_ext2(analysis, capsys):
    """fs/ext2 is built by allmodconfig/defconfig, so it should have no
    blind spots and should be attributed to an EXT2 MAINTAINERS entry."""
    allmod = CONFIGS / "allmodconfig.config"
    defcfg = CONFIGS / "defconfig.config"
    if not (allmod.is_file() and defcfg.is_file()):
        pytest.skip("standard Linux configs are absent")
    rc = main.main(["blindspots", "--tree", str(LINUX), "--path", "fs/ext2",
                    "--configs", str(allmod), str(defcfg), "--json", "--no-analyze"])
    d = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert d["objects_considered"] > 0
    assert d["blind_spots"] == 0


@_needs_linux
def test_blindspots_finds_x86_32_only_code(analysis, capsys):
    """arch/x86/kernel/cpu/mtrr/cyrix.o is X86_32-only legacy CPU support;
    every standard config here targets x86_64, so it must be a blind spot."""
    allmod = CONFIGS / "allmodconfig.config"
    defcfg = CONFIGS / "defconfig.config"
    if not (allmod.is_file() and defcfg.is_file()):
        pytest.skip("standard Linux configs are absent")
    rc = main.main(["blindspots", "--tree", str(LINUX),
                    "--path", "arch/x86/kernel/cpu/mtrr",
                    "--configs", str(allmod), str(defcfg), "--json", "--no-analyze"])
    d = json.loads(capsys.readouterr().out)
    assert rc == 0
    flat = [p for r in d["top_entries"] for p, _ in r["objects"]]
    assert "arch/x86/kernel/cpu/mtrr/cyrix.o" in flat
