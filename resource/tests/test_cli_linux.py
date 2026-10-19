"""Smoke test of the kfold CLI on the Linux v6.6 workspace.

Skipped unless work/prepared/linux-7.2.8 exists. Analyzing Linux takes about
two minutes, so the tests use an existing valid cache (from `kfold analyze
work/prepared/linux-7.2.8`, default cache root or $KFOLD_CACHE) and are
skipped without one, unless KFOLD_TEST_ANALYZE_LINUX=1 allows analyzing.
"""
import json
import os
import pathlib
import time

import pytest

from cli import cache, main

ROOT = pathlib.Path(__file__).resolve().parent.parent
# The analyzed Linux tree and configs of the canonical run (experiments/).
LINUX = ROOT / "work" / "prepared" / "linux-7.2.8"
CONFIGS = ROOT / "evidence" / "configs" / "linux"

pytestmark = pytest.mark.skipif(not (LINUX / "Makefile").is_file(),
                                reason="work/prepared/linux-7.2.8 is absent (run experiments/fetch.py)")


@pytest.fixture(scope="module")
def analysis():
    a = cache.load(LINUX)
    if a is None:
        if not os.environ.get("KFOLD_TEST_ANALYZE_LINUX"):
            pytest.skip("no valid Linux cache; run `kfold analyze work/prepared/linux-7.2.8` "
                        "or set KFOLD_TEST_ANALYZE_LINUX=1")
        a = cache.analyze(LINUX)
    return a


def test_load_is_fast(analysis):
    t0 = time.monotonic()
    a = cache.load(LINUX)
    a.conds["fs/ext2/xattr.o"]
    assert time.monotonic() - t0 < 1.0
    assert len(a.conds) > 20000


def test_ext2_xattr(analysis):
    p = "fs/ext2/xattr.o"
    assert analysis.kinds[p] == "member"
    assert ("fs/ext2/Makefile", "member of ext2.o") in analysis.origins[p]
    assert {"CONFIG_EXT2_FS", "CONFIG_EXT2_FS_XATTR"} <= set(analysis.symbols(p))
    assert analysis.is_built(p, {"CONFIG_EXT2_FS": "y", "CONFIG_EXT2_FS_XATTR": "y"})
    assert not analysis.is_built(p, {"CONFIG_EXT2_FS": "y"})


@pytest.mark.parametrize("profile", ["defconfig", "tinyconfig"])
def test_query_matches_archived_build(analysis, profile, capsys):
    """kfold's verdict for a few objects agrees with the archived build."""
    cfg = CONFIGS / f"{profile}.config"
    if not cfg.is_file():
        pytest.skip(f"{cfg} is absent")
    built = set((ROOT / "evidence" / "inventories" / "linux" / f"{profile}.txt").read_text().split())
    for obj in ("kernel/sched/core.o", "fs/ext4/xattr.o", "fs/ext2/xattr.o",
                "drivers/net/ethernet/intel/e1000e/netdev.o"):
        rc = main.main(["query", obj, "--tree", str(LINUX), "--config", str(cfg),
                        "--json", "--no-analyze"])
        d = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert d["config"]["built"] == (obj in built), (profile, obj)
