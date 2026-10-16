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


def _y(solver, name):
    sym, optd = solver.get_sort(name)
    return sym == optd["y"]


def test_eval_call_in_foreach():
    # drivers/platform/x86/intel pattern: each listed target gets a
    # composite through $(eval $(call ...)), under that target's guard.
    kb, solver = analyze("""
intel-target-$(CONFIG_HID) += hid.o
intel-target-$(CONFIG_VBTN) += vbtn.o
define INTEL_OBJ_TARGET
intel-$(1)-y := $(1).o
obj-$(2) += intel-$(1).o
endef
$(foreach target, $(basename $(intel-target-y)), $(eval $(call INTEL_OBJ_TARGET,$(target),y)))
""")
    obj_y = next(v for v in kb.state.target_files if v.name == "obj-y")
    assert set(obj_y.valconds) == {"intel-hid.o", "intel-vbtn.o"}
    assert solver.is_valid(obj_y.valconds["intel-hid.o"] == _y(solver, "CONFIG_HID"))
    assert set(kb.state.composite_members("intel-hid")) == {"hid.o"}


def test_eval_of_foreach_over_multiline_define():
    # drivers/iommu/generic_pt/fmt pattern: one $(eval) of a $(foreach)
    # whose pieces are multi-line define bodies.
    kb, solver = analyze("""
fmt-$(CONFIG_A) += a
fmt-$(CONFIG_B) += b
define create_format
obj-$(2) += iommu_$(1).o
kunit-y += kunit_$(1).o

endef
$(eval $(foreach f,$(fmt-y),$(call create_format,$(f),y)))
""")
    obj_y = next(v for v in kb.state.target_files if v.name == "obj-y")
    assert set(obj_y.valconds) == {"iommu_a.o", "iommu_b.o"}
    assert solver.is_valid(obj_y.valconds["iommu_b.o"] == _y(solver, "CONFIG_B"))


def test_eval_appends_to_a_list_read_later():
    # drivers/gpu/drm/msm pattern: evaluated text appends to a variable
    # that a later assignment turns into composite members.
    kb, solver = analyze("""
GEN =
define gen
GEN += generated/$(1).json.c
endef
$(eval $(call gen,a2xx))
$(eval $(call gen,a5xx))
obj-$(CONFIG_MSM) += msm.o
msm-y := core.o $(GEN:.c=.o)
""")
    assert set(kb.state.composite_members("msm")) == {
        "core.o", "generated/a2xx.json.o", "generated/a5xx.json.o"}


def test_eval_call_of_many_line_define_stays_small():
    # coreboot src/drivers/spi pattern: a define whose every line has its own
    # option; expanding the body as one string multiplied the alternatives.
    body = "\n".join(f"$(1)-$(CONFIG_F{i}) += f{i}.c" for i in range(24))
    kb, solver = analyze(f"define add_stage\n{body}\nendef\n"
                         "$(eval $(call add_stage,obj))\n$(eval $(call add_stage,lib))\n")
    obj_y = next(v for v in kb.state.target_files if v.name == "obj-y")
    assert set(obj_y.valconds) == {f"f{i}.c" for i in range(24)}
    assert solver.is_valid(obj_y.valconds["f7.c"] == _y(solver, "CONFIG_F7"))
