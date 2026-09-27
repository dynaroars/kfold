"""Kbuild semantics needed for exact agreement with Linux builds."""
import pathlib
import shutil
import tempfile

import z3

import settings
from alg import Run
from kbuild import Kbuild
from objects import object_conditions, predicted_objects
import helpers.zsolver as zsolver


def make_tree(files, ini=""):
    root = pathlib.Path(tempfile.mkdtemp())
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    (root / "skbuild.ini").write_text("[COMMON]\nuse_tristate = yes\n" + ini)
    return root


def objects_under(root, config):
    runner = Run(root, use_tristate=True)
    tmp = runner.go()
    try:
        conds, kinds = object_conditions(runner)
        cfg = root / "cfg"
        cfg.write_text("".join(f"{k}={v}\n" for k, v in config.items()))
        return predicted_objects(runner, conds, cfg), kinds
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
        shutil.rmtree(str(root), ignore_errors=True)


def analyze(text):
    with tempfile.TemporaryDirectory() as d:
        d = pathlib.Path(d)
        (d / "Makefile").write_text(text)
        kb = Kbuild(d / "Makefile", settings.Settings(d, use_tristate=True))
        kb.preprocess()
        kb.symexe()
        return kb, zsolver.ZSolver(kb.mysettings)


def test_substitution_reference():
    kb, _ = analyze("V := 3.1 4.2\nipa-y := main.o $(V:%=data/v%.o)\nobj-y += ipa.o\n")
    assert set(kb.state.composite_members("ipa")) == {"main.o", "data/v3.1.o", "data/v4.2.o"}


def test_deferred_append_sees_later_definition():
    # drivers/xen: dom0-y references xen-pad-y before it is defined.
    kb, solver = analyze("dom0-y += acpi.o $(xen-pad-y)\nxen-pad-y += pad.o\nobj-y += $(dom0-y)\n")
    obj_y = next(v for v in kb.state.target_files if v.name == "obj-y")
    assert {"acpi.o", "pad.o"} <= set(obj_y.valconds)


def test_word_list_keeps_independent_guards():
    # drivers/firmware/arm_scmi: many conditional lists joined in one value.
    text = "".join(f"t-$(CONFIG_T{i}) += t{i}.o\n" for i in range(10))
    text += "".join(f"d-$(CONFIG_D{i}) += d{i}.o\n" for i in range(10))
    text += "m-objs := $(d-y) $(t-y)\nobj-y += m.o\n"
    kb, solver = analyze(text)
    members = kb.state.composite_members("m")
    sym, optd = solver.get_sort("CONFIG_T3")
    assert solver.is_valid(members["t3.o"] == (sym == optd["y"]))


def test_builtin_container_not_written_and_need_builtin():
    root = make_tree({
        "Kbuild": "obj-y += a/\nobj-$(CONFIG_M) += b/\n",
        "a/Makefile": "obj-y += comp.o\ncomp-y := x.o y.o\ncomp-$(CONFIG_R) += r.o\n",
        "b/Makefile": "obj-y += builtin_only.o\nobj-m += mod.o\n",
    }, "composite_objects = modules\nneed_builtin = yes\n")
    predicted, _ = objects_under(root, {"CONFIG_M": "m", "CONFIG_R": "m", "CONFIG_MODULES": "y"})
    assert {"a/x.o", "a/y.o", "b/mod.o"} <= predicted
    assert "a/comp.o" not in predicted          # built-in composite: no container object
    assert "a/r.o" not in predicted             # comp-m members only for a modular composite
    assert "b/builtin_only.o" not in predicted  # b/ reached only through obj-m


def test_rule_prerequisites_and_submake():
    root = make_tree({
        "Kbuild": "obj-y += d/\n",
        "d/Makefile": ("obj-y += blob.o\n"
                       "parts := p1.o p2.o\n"
                       "$(obj)/blob.o: $(obj)/sub/out.bin\n"
                       "$(obj)/sub/out.bin: FORCE\n"
                       "\t$(Q)$(MAKE) $(build)=$(obj)/sub $@\n"),
        "d/sub/Makefile": "objs := s1.o s2.o\n$(obj)/out.bin: $(addprefix $(obj)/,$(objs))\n",
    })
    predicted, kinds = objects_under(root, {})
    assert {"d/blob.o", "d/sub/s1.o", "d/sub/s2.o"} <= predicted
    assert kinds["d/sub/s1.o"] == "rule"


def test_subdir_y_is_traversed():
    root = make_tree({
        "Kbuild": "subdir-$(CONFIG_S) += s\n",
        "s/Makefile": "lib-y += helper.o\n",
    })
    predicted, _ = objects_under(root, {"CONFIG_S": "y"})
    assert "s/helper.o" in predicted


def test_always_target_rule_prerequisites():
    # kernel/trace: always-$(CONFIG_SRB) += srb.o.checked, and a pattern rule
    # makes %.o.checked from %.o and base.o, which no list names.
    root = make_tree({
        "Kbuild": "obj-y += d/\n",
        "d/Makefile": ("obj-$(CONFIG_SRB) += srb.o\n"
                       "targets += base.o\n"
                       "$(obj)/%.o.checked: $(obj)/%.o $(obj)/base.o FORCE\n"
                       "\ttouch $@\n"
                       "always-$(CONFIG_SRB) += srb.o.checked\n"),
        "d/srb.c": "", "d/base.c": "",
    }, "target_vars = obj- lib- extra- always-\n")
    predicted, kinds = objects_under(root, {"CONFIG_SRB": "y"})
    assert {"d/srb.o", "d/base.o"} <= predicted
    assert kinds["d/base.o"] == "rule"
    root = make_tree({
        "Kbuild": "obj-y += d/\n",
        "d/Makefile": ("obj-$(CONFIG_SRB) += srb.o\n"
                       "$(obj)/%.o.checked: $(obj)/%.o $(obj)/base.o FORCE\n"
                       "\ttouch $@\n"
                       "always-$(CONFIG_SRB) += srb.o.checked\n"),
        "d/srb.c": "", "d/base.c": "",
    }, "target_vars = obj- lib- extra- always-\n")
    predicted, _ = objects_under(root, {})
    assert "d/base.o" not in predicted
