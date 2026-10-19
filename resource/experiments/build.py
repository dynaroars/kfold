#!/usr/bin/env python3
"""Physically build every pinned (subject, configuration) and record inventories.

Usage: experiments/build.py [SUBJECT[:CONFIG] ...] [--jobs N] [--force]

For each pair this
  1. copies the pristine tree from work/src/ to work/build/<subject>-<config>/,
  2. generates the configuration (see CONFIG_STEPS),
  3. runs the build with ``make -k`` so one failing file cannot hide others,
  4. writes, under evidence/:
       configs/<subject>/<config>.config          final .config
       inventories/<subject>/<config>.txt          every .o produced (sorted,
                                                   relative, *.mod.o excluded)
       inventories/<subject>/<config>.failed.txt   objects make reported failing
     and appends a record (toolchain, exit status, time) to results/builds.json.

Configuration choices that deviate from the stock target are listed in
ADJUSTMENTS and recorded with each build, so they can be reported.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from subjects import CC, EVIDENCE, RESULTS, SUBJECTS, WORK, build_dir, source_dir  # noqa: E402

COREBOOT_XGCC = WORK / "toolchains" / "coreboot-26.06" / "util" / "crossgcc" / "xgcc" / "bin"

# Deviations from the stock configuration, applied after generation and
# before ``olddefconfig``. Each is needed for the build to run on this host
# and does not change which objects Kbuild selects for compilation, except
# where noted.
ADJUSTMENTS = {
    ("linux", "debian"): [
        # Debian's signing certificates are not part of the kernel tree.
        "scripts/config --set-str SYSTEM_TRUSTED_KEYS ''",
        "scripts/config --set-str SYSTEM_REVOCATION_KEYS ''",
    ],
    ("linux", "allmodconfig"): [
        # allmodconfig turns warnings into errors; a newer compiler's new
        # warnings would then abort files that otherwise compile.
        "scripts/config --disable WERROR --disable DRM_WERROR --disable DRM_AMDGPU_WERROR",
    ],
    ("coreboot", "qemu-i440fx"): [
        # No payload: SeaBIOS would be cloned from the network mid-build.
        # This removes the payload's objects (reported as a deviation).
        "echo CONFIG_PAYLOAD_NONE=y >> .config",
    ],
}


def linux_steps(cfg, jobs):
    arch = f"ARCH={cfg['arch']}"
    base = cfg["base"]
    gen = (f"cp {base[5:]} .config && make {arch} CC={CC} olddefconfig"
           if base.startswith("file:") else f"make {arch} CC={CC} {base}")
    return gen, f"make {arch} CC={CC} olddefconfig", f"make {arch} CC={CC} -k -j{jobs}"


def steps(subject, config, jobs):
    cfg = SUBJECTS[subject]["configs"][config]
    if subject == "linux":
        return linux_steps(cfg, jobs)
    if subject == "busybox":
        return ("make CC=gcc defconfig", "make CC=gcc oldconfig </dev/null",
                f"make CC=gcc -k -j{jobs}")
    if subject == "barebox":
        return ("make ARCH=sandbox sandbox_defconfig", "make ARCH=sandbox olddefconfig",
                f"make ARCH=sandbox -k -j{jobs}")
    if subject == "uboot":
        # NO_PYTHON: skip the Python host tools (pylibfdt), whose generated
        # wrapper does not compile against Python 3.14; they are not targets.
        # The host has no SDL2 headers, so arch/sandbox/cpu/sdl.o fails to
        # compile; that failure is recorded, not configured away.
        return ("make sandbox_defconfig", "make olddefconfig",
                f"make NO_PYTHON=1 -k -j{jobs}")
    if subject == "coreboot":
        board = cfg["base"].split(":", 1)[1]
        # coreboot's own cross toolchain, built once by `make crossgcc-i386`
        # in work/toolchains/ (see experiments/README.md).
        xgcc = f"XGCCPATH={COREBOOT_XGCC}/"
        return (f"printf 'CONFIG_VENDOR_EMULATION=y\\nCONFIG_BOARD_{board}=y\\n' > .config",
                f"make {xgcc} olddefconfig", f"make {xgcc} -k -j{jobs} CPUS={jobs}")
    raise ValueError(subject)


def sh(cmd, cwd, log):
    log.write(f"\n$ {cmd}\n".encode())
    log.flush()
    return subprocess.run(cmd, shell=True, cwd=cwd, stdout=log, stderr=subprocess.STDOUT).returncode


def inventory(tree):
    objs = []
    for dirpath, dirnames, filenames in os.walk(tree):
        for f in filenames:
            if f.endswith(".o") and not f.endswith(".mod.o"):
                objs.append(os.path.relpath(os.path.join(dirpath, f), tree))
    return sorted(objs)


FAIL_RE = re.compile(r"make\[\d+\]: \*\*\* \[[^\]]*: ([^\]]+\.o)\] Error")


def record(entry):
    path = RESULTS / "builds.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    data[f"{entry['subject']}:{entry['config']}"] = entry
    RESULTS.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")


def build(subject, config, jobs, force):
    tree = build_dir(subject, config)
    inv = EVIDENCE / "inventories" / subject / f"{config}.txt"
    if SUBJECTS[subject]["configs"][config].get("build", True) is False:
        inv = EVIDENCE / "configs" / subject / f"{config}.config"
    if inv.exists() and not force:
        print(f"{subject}:{config}: already built", flush=True)
        return
    if tree.exists():
        subprocess.run(["chmod", "-R", "u+w", str(tree)], check=True)
        shutil.rmtree(tree)
    tree.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["cp", "-a", "--reflink=auto", str(source_dir(subject)), str(tree)], check=True)
    subprocess.run(["chmod", "-R", "u+w", str(tree)], check=True)
    gen, normalize, make = steps(subject, config, jobs)
    adjust = ADJUSTMENTS.get((subject, config), [])
    if SUBJECTS[subject]["configs"][config].get("build", True) is False:
        make = "true"  # configuration only
    logpath = tree.parent / f"{subject}-{config}.log"
    t0 = time.time()
    with open(logpath, "wb") as log:
        rc_gen = sh(gen, tree, log)
        for cmd in adjust:
            sh(cmd, tree, log)
        rc_norm = sh(normalize, tree, log)
        rc = sh(make, tree, log)
    elapsed = time.time() - t0
    text = logpath.read_text(errors="replace")
    failed = sorted(set(FAIL_RE.findall(text)))
    objs = inventory(tree)
    if make != "true":
        inv.parent.mkdir(parents=True, exist_ok=True)
        inv.write_text("".join(o + "\n" for o in objs))
        inv.with_suffix(".failed.txt").write_text("".join(o + "\n" for o in failed))
    cfgdir = EVIDENCE / "configs" / subject
    cfgdir.mkdir(parents=True, exist_ok=True)
    shutil.copy(tree / ".config", cfgdir / f"{config}.config")
    cc = subprocess.run([CC, "--version"], capture_output=True, text=True).stdout.splitlines()[0]
    record({"subject": subject, "config": config, "version": SUBJECTS[subject]["version"],
            "commands": [gen, *adjust, normalize, make], "adjustments": adjust,
            "rc_generate": rc_gen, "rc_normalize": rc_norm, "rc_build": rc,
            "seconds": round(elapsed, 1), "compiler": cc, "objects": len(objs),
            "failed_objects": len(failed), "log": str(logpath)})
    print(f"{subject}:{config}: rc={rc} objects={len(objs)} failed={len(failed)} "
          f"({elapsed/60:.1f} min)", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="*")
    ap.add_argument("--jobs", type=int, default=os.cpu_count())
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    targets = args.targets or [f"{s}:{c}" for s in SUBJECTS for c in SUBJECTS[s]["configs"]]
    for t in targets:
        subject, _, config = t.partition(":")
        configs = [config] if config else list(SUBJECTS[subject]["configs"])
        for c in configs:
            build(subject, c, args.jobs, args.force)


if __name__ == "__main__":
    main()
