import pathlib
import tempfile

import z3

import settings
from kbuild import Kbuild
import helpers.zsolver as zsolver


def analyze(content: str):
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = pathlib.Path(tmpdir)
        mk_file = tmppath / "Makefile"
        mk_file.write_text(content)
        mysettings = settings.Settings(tmppath)
        kb = Kbuild(mk_file, mysettings)
        kb.preprocess()
        kb.symexe()
        return kb, zsolver.ZSolver(kb.mysettings)


def test_partially_defined_reference_keeps_other_words():
    # dvb-core pattern from Linux: $(dvb-net-y) is empty unless CONFIG_DVB_NET=y,
    # and must not make the other members depend on CONFIG_DVB_NET.
    kb, solver = analyze("""
dvb-net-$(CONFIG_DVB_NET) := dvb_net.o
dvb-core-objs := dvbdev.o $(dvb-net-y) dvb_ringbuffer.o
obj-y += dvb-core.o
""")
    members = kb.state.composite_members("dvb-core")
    assert solver.is_valid(members["dvbdev.o"])
    assert solver.is_valid(members["dvb_ringbuffer.o"])
    net, optd = solver.get_sort("CONFIG_DVB_NET")
    assert solver.is_valid(members["dvb_net.o"] == (net == optd["y"]))


def test_merge_keeps_untouched_guards_small():
    # Words that no arm changes keep their guard instead of accumulating
    # (k & phi) | (~k & phi) at every conditional.
    blocks = "\n".join(f"ifeq ($(CONFIG_B{i}),y)\nobj-y += b{i}.o\nendif" for i in range(12))
    kb, solver = analyze(blocks)
    obj_y = next(v for v in kb.state.target_files if v.name == "obj-y")
    b0 = obj_y.valconds["b0.o"]
    sym, optd = solver.get_sort("CONFIG_B0")
    assert solver.is_valid(b0 == (sym == optd["y"]))
    assert len(b0.sexpr()) < 40


def test_include_with_src_relative_path():
    # nouveau pattern from Linux: `include $(src)/nvkm/Kbuild` adds members
    # to a composite defined in the including Kbuild file.
    with tempfile.TemporaryDirectory() as tmpdir:
        root = pathlib.Path(tmpdir)
        drv = root / "drv"
        (drv / "sub").mkdir(parents=True)
        (drv / "Kbuild").write_text(
            "obj-$(CONFIG_DRV) += drv.o\n"
            "drv-y := main.o\n"
            "include $(src)/sub/Kbuild\n")
        (drv / "sub" / "Kbuild").write_text("drv-$(CONFIG_SUB) += sub/extra.o\n")
        mysettings = settings.Settings(root)
        kb = Kbuild(drv / "Kbuild", mysettings)
        kb.preprocess()
        kb.symexe()
        assert kb.include_stats["spliced"] == 1
        members = kb.state.composite_members("drv")
        assert set(members) == {"main.o", "sub/extra.o"}
