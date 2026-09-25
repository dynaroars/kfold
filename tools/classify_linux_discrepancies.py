#!/usr/bin/env python3
"""Classify the Linux physical discrepancies in results/physical_validation.json.

False positives are split into composite containers (targets with members,
which Kbuild links into built-in.a without writing the container .o when the
composite is built in) and other paths. Observed objects outside the target
set are grouped by the producing directory. Writes
results/linux_discrepancy_classes.json.
"""
import collections
import json
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
from alg import Run  # noqa: E402
from kfold_targets import target_path  # noqa: E402

SPECIAL = ("arch/x86/boot/", "arch/x86/realmode/", "arch/x86/purgatory/",
           "arch/x86/tools/", "arch/x86/entry/vdso/", "drivers/firmware/efi/libstub/")


def main():
    runner = Run(ROOT / "results" / "workspaces" / "linux", use_tristate=True)
    tmp = runner.go()
    containers = set()
    for kb in runner.all_kbuilds:
        for var in kb.state.target_files:
            for word in var.valconds:
                if isinstance(word, str) and word.endswith(".o") and \
                        kb.state.composite_members(word[:-2]):
                    rel = target_path(word, var.name, kb.makefile.parent, runner.maindir)
                    if rel:
                        containers.add(rel)
    shutil.rmtree(str(tmp), ignore_errors=True)
    data = {e["subject"]: e for e in json.load(open(ROOT / "results" / "physical_validation.json"))}
    out = {"composite_containers": len(containers), "profiles": {}}
    for p, v in data["Linux"]["profiles"].items():
        m = v["members"]
        fp = m["fp_paths"]
        outside = m["outside_universe_paths"]
        special = [x for x in outside if x.startswith(SPECIAL)]
        out["profiles"][p] = {
            "fp": len(fp),
            "fp_composite_containers": sum(x in containers for x in fp),
            "outside": len(outside),
            "outside_special_rules": len(special),
            "outside_special_by_dir": dict(collections.Counter(
                next(s for s in SPECIAL if x.startswith(s)) for x in special)),
            "outside_other": sorted(set(outside) - set(special)),
        }
        print(p, {k: v2 for k, v2 in out["profiles"][p].items() if k != "outside_other"},
              len(out["profiles"][p]["outside_other"]), flush=True)
    (ROOT / "results" / "linux_discrepancy_classes.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
