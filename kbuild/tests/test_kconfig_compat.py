"""Newer Kconfig syntax (src/kconfig_compat.py) and config-for's widened
Kconfig cone, on a synthetic tree small enough to reason about by hand."""
import json
import pathlib
import textwrap

import pytest

import kconfiglib
import kconfig_compat
from cli import main

KCONFIG = textwrap.dedent("""\
    config MODULES
    \tbool "Enable loadable module support"
    \tmodules

    config OLD_NAME
    \tbool
    \ttransitional
    \thelp
    \t  Renamed to NEW_NAME.

    config NEW_NAME
    \tbool "new name"
    \tdefault OLD_NAME

    config BUS
    \ttristate "bus"

    config GADGET
    \ttristate "gadget"

    config CONTROLLER
    \ttristate "controller"
    \tdepends on BUS if !GADGET

    config ORDER
    \tint

    config SMALL
    \tint "small"
    \trange 1 10 if ORDER = 0
    \tdefault 10 if ORDER = 0

    config SCHED
    \ttristate

    config DRIVER
    \ttristate "driver"
    \tselect SCHED

    config HELPER
    \ttristate "helper"

    config USER
    \tbool "user"
    \timply HELPER
    """)


@pytest.fixture
def tree(tmp_path):
    d = tmp_path / "tree"
    d.mkdir()
    (d / "Kconfig").write_text(KCONFIG)
    (d / "Makefile").write_text("obj-$(CONFIG_SCHED) += sched.o\nobj-$(CONFIG_DRIVER) += driver.o\n")
    (d / "sched.c").write_text("")
    (d / "driver.c").write_text("")
    (d / "skbuild.ini").write_text("[COMMON]\nuse_tristate = yes\n")
    return d


def load(tree, config=None):
    kc = kconfiglib.Kconfig(str(tree / "Kconfig"), warn=False)
    if config is not None:
        path = tree / ".config"
        path.write_text(config)
        kc.load_config(str(path))
    return kc


def test_newer_syntax_parses(tree):
    kc = load(tree)
    assert kc.modules.name == "MODULES"              # bare "modules"
    assert not kc.syms["OLD_NAME"].nodes[0].prompt   # "transitional" dropped


def test_conditional_dependency_matches_scripts_kconfig(tree):
    # depends on BUS if !GADGET  ==  BUS || (GADGET = y)
    for bus, gadget, visible in (("n", "n", 0), ("n", "y", 2), ("m", "n", 1),
                                 ("n", "m", 0), ("y", "m", 2)):
        cfg = "CONFIG_MODULES=y\n" + "".join(
            f"CONFIG_{s}={v}\n" for s, v in (("BUS", bus), ("GADGET", gadget)) if v != "n")
        assert load(tree, cfg).syms["CONTROLLER"].visibility == visible, (bus, gadget)


def test_empty_int_compares_as_zero(tree):
    kc = load(tree, "")
    assert kc.syms["ORDER"].str_value == "0"
    assert kc.syms["SMALL"].str_value == "10"


def test_imply_does_not_override_user_module_value(tree):
    kc = load(tree, "CONFIG_MODULES=y\nCONFIG_USER=y\nCONFIG_HELPER=m\n")
    assert kc.syms["HELPER"].str_value == "m"
    kc = load(tree, "CONFIG_MODULES=y\nCONFIG_USER=y\n")
    assert kc.syms["HELPER"].str_value == "y"   # no user value: implied y


def test_makefile_exports_computed(tree, monkeypatch):
    monkeypatch.setenv("CC", "gcc")
    exports = kconfig_compat.makefile_exports(tree)
    assert set(exports) == {"CC_VERSION_TEXT", "RUSTC_VERSION_TEXT", "PAHOLE_VERSION"}


def test_config_for_enables_promptless_symbol_through_selector(tree, tmp_path, capsys):
    # SCHED has no prompt; only DRIVER's select can enable it. The fast cone
    # (depends-on only, selectors pinned to the base) finds it impossible, so
    # config-for must widen the cone before excluding sched.o.
    base = tmp_path / "base.config"
    base.write_text("CONFIG_MODULES=y\n")
    rc = main.main(["--cache-dir", str(tmp_path / "cache"), "config-for", "sched.c",
                    "--tree", str(tree), "--base", str(base), "--json"])
    d = json.loads(capsys.readouterr().out)
    assert rc == 0, d
    assert d["excluded"] == {}
    assert d["kconfig_widened"] is True
    assert d["fragment"].get("CONFIG_DRIVER") in ("y", "m")
    assert d["predicted_not_built"] == []
