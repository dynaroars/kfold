#!/usr/bin/env python3
"""Audit the object paths that Kmax and kfold report for Linux v6.6.

Runs Kmax 4.10 (per Makefile, as in compare_kfold_with_kmax.py, but under
``python3 -O`` and on the same v6.6 tree the physical builds came from) and
kfold on results/workspaces/linux. Every reported path is then classified
against the union of the four archived Linux build inventories:

  built          path appears in at least one inventory
  other_arch     under arch/<not x86>/ and never built
  dir_unbuilt    directory has no object in any inventory
  dir_built      directory was built, but this object never was

Writes results/kmax_extra_audit.json with counts and the full path lists.
"""
import concurrent.futures
import json
import pathlib
import subprocess
import sys
import time
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from compare_kfold_with_kmax import run_kfold_on_corpus  # noqa: E402

LINUX = ROOT / "results" / "workspaces" / "linux"
PROFILES = ["tinyconfig", "defconfig", "debian", "allmodconfig"]
KMAX = [sys.executable, "-O", str(pathlib.Path.home() / ".local/bin/kmax"), "-u"]


def inventory(profile):
    base = ROOT / "evidence" / "physical_builds" / profile
    return {str(p.relative_to(base)) for p in base.rglob("*.o")}


def kmax_objects(root):
    mks = [p for p in root.rglob("*")
           if p.is_file() and (p.name.startswith(("Makefile", "Kbuild")))
           and ".git" not in p.parts]

    def one(mk):
        try:
            r = subprocess.run(KMAX + [mk.name], cwd=mk.parent, capture_output=True,
                               text=True, timeout=120)
        except subprocess.TimeoutExpired:
            return mk, None
        if r.returncode != 0:
            return mk, None
        objs = set()
        for line in r.stdout.splitlines():
            if not line.startswith("unit_pc "):
                continue
            unit = line.split(maxsplit=2)[1]
            if unit.startswith("$(") or not unit.endswith(".o"):
                continue
            p = (mk.parent / unit).resolve()
            try:
                objs.add(str(p.relative_to(root.resolve())))
            except ValueError:
                pass
        return mk, objs

    found, failed = set(), []
    t0 = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        for mk, objs in ex.map(one, mks):
            if objs is None:
                failed.append(str(mk.relative_to(root)))
            else:
                found |= objs
    return found, len(mks), failed, time.monotonic() - t0


def classify(paths, built, built_dirs):
    cls = {"built": [], "other_arch": [], "dir_unbuilt": [], "dir_built": []}
    for p in sorted(paths):
        parts = p.split("/")
        if p in built:
            cls["built"].append(p)
        elif parts[0] == "arch" and len(parts) > 1 and parts[1] != "x86":
            cls["other_arch"].append(p)
        elif str(pathlib.PurePath(p).parent) not in built_dirs:
            cls["dir_unbuilt"].append(p)
        else:
            cls["dir_built"].append(p)
    return cls


def main():
    built = set()
    for prof in PROFILES:
        built |= inventory(prof)
    built_dirs = {str(pathlib.PurePath(p).parent) for p in built}

    kfold = run_kfold_on_corpus("Linux v6.6", str(LINUX))
    kfold_set = set(kfold["target_objects"])
    kmax_set, n_mk, failed, kmax_time = kmax_objects(LINUX)

    groups = {"common": kfold_set & kmax_set,
              "kmax_only": kmax_set - kfold_set,
              "kfold_only": kfold_set - kmax_set}
    out = {"tree": str(LINUX.relative_to(ROOT)), "profiles": PROFILES,
           "built_union": len(built),
           "kfold": {"objects": len(kfold_set), "time_s": round(kfold["wall_time_s"], 2)},
           "kmax": {"objects": len(kmax_set), "makefiles": n_mk,
                    "failed_makefiles": failed, "time_s": round(kmax_time, 2)},
           "groups": {}}
    for name, paths in groups.items():
        cls = classify(paths, built, built_dirs)
        top = Counter(p.split("/")[0] for p in cls["dir_built"] + cls["dir_unbuilt"])
        out["groups"][name] = {"total": len(paths),
                               "counts": {k: len(v) for k, v in cls.items()},
                               "unbuilt_by_top_dir": dict(top.most_common(12)),
                               "paths": cls}
        print(name, len(paths), out["groups"][name]["counts"], flush=True)
    dest = ROOT / "results" / "kmax_extra_audit.json"
    dest.write_text(json.dumps(out, indent=1))
    print("wrote", dest)


if __name__ == "__main__":
    main()
