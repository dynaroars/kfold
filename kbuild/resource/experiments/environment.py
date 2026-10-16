#!/usr/bin/env python3
"""Record the machine and tool versions the evaluation ran with.

Usage: experiments/environment.py

Writes results/environment.json: host OS, kernel, CPU, cores, memory, the
kfold commit, and the versions of Python, Z3, GCC, GNU Make, and the other
tools the builds use. Per-build toolchains are also recorded in
results/builds.json.
"""
import json
import os
import platform
import subprocess
import sys

from subjects import RESULTS, ROOT


def first_line(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                             timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.strip().splitlines()[0] if out.strip() else None


def os_release():
    try:
        for line in open("/etc/os-release"):
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return None


def cpu_model():
    try:
        for line in open("/proc/cpuinfo"):
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or None


def mem_total_gib():
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemTotal:"):
                return round(int(line.split()[1]) / 1024 ** 2, 1)
    except OSError:
        pass
    return None


def main():
    import z3
    env = {
        "os": os_release(),
        "kernel": platform.release(),
        "machine": platform.machine(),
        "cpu": cpu_model(),
        "cpus": os.cpu_count(),
        "memory_gib": mem_total_gib(),
        "kfold_commit": first_line(["git", "-C", str(ROOT), "rev-parse", "HEAD"]),
        "kfold_dirty": bool(first_line(["git", "-C", str(ROOT), "status", "--porcelain",
                                        "--untracked-files=no"])),
        "python": sys.version.split()[0],
        "z3": z3.get_version_string(),
        "gcc": first_line(["gcc", "--version"]),
        "make": first_line(["make", "--version"]),
        "rustc": first_line(["rustc", "--version"]),
        "bindgen": first_line(["bindgen", "--version"]),
        "bison": first_line(["bison", "--version"]),
        "flex": first_line(["flex", "--version"]),
    }
    path = RESULTS / "environment.json"
    path.write_text(json.dumps(env, indent=1, sort_keys=True) + "\n")
    print(json.dumps(env, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
