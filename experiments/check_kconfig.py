#!/usr/bin/env python3
"""Check kfold's Kconfig model against scripts/kconfig on the Linux configs.

Usage: experiments/check_kconfig.py

kfold's Kconfig reasoning (``why`` explanations, ``config-for``) goes through
kconfiglib plus src/kconfig_compat.py. For each generated Linux .config, this
loads the .config into kconfiglib and compares every symbol's value with the
value scripts/kconfig wrote. The toolchain probes that the kernel Makefile
exports to Kconfig (CC_VERSION_TEXT, PAHOLE, NM, ...) are set as the Makefile
sets them. Writes results/kconfig_check.json.
"""
import json
import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from subjects import CC, EVIDENCE, RESULTS, ROOT, SUBJECTS, analysis_dir  # noqa: E402

sys.path.insert(0, str(ROOT / "src"))
import kconfiglib  # noqa: E402
import kconfig_compat  # noqa: E402


def values(path):
    d = {}
    for line in open(path):
        if line.startswith("CONFIG_"):
            k, v = line.rstrip("\n").split("=", 1)
            d[k[7:]] = v.strip('"')
        elif line.startswith("# CONFIG_") and line.endswith(" is not set\n"):
            d[line[9:-12]] = "n"
    return d


def main():
    tree = analysis_dir("linux")
    out = {}
    for config, cfg in SUBJECTS["linux"]["configs"].items():
        path = EVIDENCE / "configs" / "linux" / f"{config}.config"
        if not path.exists():
            continue
        os.environ.update(srctree=str(tree), ARCH=cfg["arch"], SRCARCH="x86", CC=CC, LD="ld",
                          NM="nm", OBJCOPY="objcopy", PAHOLE="pahole", HOSTCC="gcc",
                          KERNELVERSION=SUBJECTS["linux"]["version"],
                          RUSTC="rustc", BINDGEN="bindgen", PYTHON3="python3")
        os.environ.update(kconfig_compat.makefile_exports(tree))
        kc = kconfiglib.Kconfig(str(tree / "Kconfig"), warn=False)
        kc.load_config(str(path))
        want = values(path)
        bad = []
        for name, v in want.items():
            sym = kc.syms.get(name)
            if sym is None or not sym.nodes:
                continue
            got = sym.str_value
            if got != v and not (v == "n" and got in ("n", "")):
                bad.append({"symbol": name, "scripts_kconfig": v, "kconfiglib": got})
        out[config] = {"symbols_in_config": len(want), "defined_symbols": len(kc.unique_defined_syms),
                       "mismatches": bad}
        print(config, len(want), "symbols,", len(bad), "mismatches", bad[:5], flush=True)
    (RESULTS / "kconfig_check.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
