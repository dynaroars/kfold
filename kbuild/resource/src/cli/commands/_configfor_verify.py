"""``--verify``: apply a fragment to a base .config in a scratch copy of the
tree, run ``make ARCH=x86_64 olddefconfig``, and report which requested
symbols survived and whether kfold's own predictor agrees the touched
objects are built by the resulting .config. Never writes into the analyzed
tree itself.

Copies the tree with rsync, excluding build artifacts (.o/.a/.cmd/vmlinux*/
etc: most of a already-built tree's size but none of its source), rather
than Kbuild's ``O=`` out-of-tree build, because a source tree that already
has in-tree build state (as ``results/workspaces/linux`` does here) refuses
``O=`` ("source tree is not clean"). There is one persistent copy per tree,
refreshed incrementally by rsync (seconds after the first ~1.5 GB copy)
and locked while in use, so repeated runs do not pile up copies. Defaults
the scratch root to
``~/.cache/kfold-configfor`` rather than /tmp: a full copy is small once
build artifacts are excluded (~1-2 GB for Linux), but this host's /tmp is a
small tmpfs shared with other agents and often nearly full."""
import fcntl
import hashlib
import os
import pathlib
import shutil
import subprocess
import time

DEFAULT_VERIFY_ROOT = pathlib.Path.home() / ".cache" / "kfold-configfor"

# Generated/build files to leave behind: rsync's --exclude matches these
# names anywhere in the tree, so a real tree that has been built in-place
# (as results/workspaces/linux has) copies as source only, in a small
# fraction of its on-disk size.
_EXCLUDES = ["--exclude=.git", "--exclude=*.o", "--exclude=*.o.cmd",
             "--exclude=*.a", "--exclude=*.a.cmd", "--exclude=*.ko",
             "--exclude=*.ko.cmd", "--exclude=*.cmd", "--exclude=.tmp_*",
             "--exclude=vmlinux*", "--exclude=System.map",
             "--exclude=Module.symvers", "--exclude=modules.order",
             "--exclude=modules.builtin*", "--exclude=include/config",
             "--exclude=include/generated"]


def verify_root():
    env = os.environ.get("KFOLD_CONFIGFOR_ROOT")
    return pathlib.Path(env).expanduser() if env else DEFAULT_VERIFY_ROOT


def merge_config_text(base_text, fragment):
    """``base_text`` (a .config's contents) with ``fragment`` ({CONFIG_X: y|m|""})
    applied: matching ``CONFIG_X=...``/``# CONFIG_X is not set`` lines are
    replaced in place; symbols with no existing line are appended."""
    remaining = dict(fragment)
    out = []
    for line in base_text.splitlines():
        name = None
        if line.startswith("CONFIG_") and "=" in line:
            name = line.split("=", 1)[0]
        elif line.startswith("# CONFIG_") and line.endswith(" is not set"):
            name = line[2:-len(" is not set")]
        if name is not None and name in remaining:
            v = remaining.pop(name)
            out.append(f"{name}={v}" if v in ("y", "m") else f"# {name} is not set")
        else:
            out.append(line)
    for name, v in remaining.items():
        out.append(f"{name}={v}" if v in ("y", "m") else f"# {name} is not set")
    return "\n".join(out) + "\n"


def _copy_tree(src, dest, timeout):
    dest.mkdir(parents=True, exist_ok=True)
    # --chmod: the copy must be writable even when the analyzed tree is
    # read-only (as experiments/ keeps it), or make cannot write .config.
    subprocess.run(["rsync", "-a", "--chmod=u+w", "--delete", *_EXCLUDES, f"{src}/", f"{dest}/"],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=timeout)


def run_verify(tree, base_config_text, fragment, targets, arch="x86_64", jobs=None,
               compile_targets=None, timeout=900, root=None):
    """A source-only copy of ``tree`` under ``root`` (default
    ``~/.cache/kfold-configfor``, override with $KFOLD_CONFIGFOR_ROOT), with
    ``fragment`` merged onto ``base_config_text`` as its .config: run
    olddefconfig and report which fragment symbols survived at their
    requested value, and the path to the resulting .config (for the caller
    to cross-check with ``Analysis.predicted``); for ``compile_targets``
    (object paths), additionally run a real ``make <path>`` each. ``tree``
    (the analyzed source tree) is only ever read, never written to."""
    jobs = jobs or max(1, (os.cpu_count() or 4) // 4)
    root = pathlib.Path(root) if root else verify_root()
    root.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(str(pathlib.Path(tree).resolve()).encode()).hexdigest()[:12]
    workdir = root / f"src-{key}"
    dest = workdir / "tree"
    result = {"workdir": str(workdir)}
    with open(root / f"src-{key}.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        t0 = time.monotonic()
        _copy_tree(tree, dest, timeout)
        result["copy_seconds"] = round(time.monotonic() - t0, 1)
        result.update(_verify_in(dest, base_config_text, fragment, arch, jobs,
                                 compile_targets, timeout))
        # Keep the resulting .config outside the shared copy, which the next
        # run overwrites.
        final_path = None
        if (dest / ".config").is_file():
            final_path = root / f"last-{key}.config"
            shutil.copyfile(dest / ".config", final_path)
    result["final_config"] = str(final_path) if final_path else None
    return result, final_path


def _verify_in(dest, base_config_text, fragment, arch, jobs, compile_targets, timeout):
    result = {}
    merged = merge_config_text(base_config_text, fragment)
    (dest / ".config").write_text(merged)
    make_base = ["make", f"ARCH={arch}", f"-j{jobs}"]
    proc = subprocess.run(make_base + ["olddefconfig"],
                          cwd=str(dest), capture_output=True, text=True, timeout=timeout)
    result["olddefconfig_rc"] = proc.returncode
    result["olddefconfig_stderr_tail"] = "\n".join(proc.stderr.splitlines()[-30:])
    final_path = dest / ".config"
    if final_path.is_file():
        from objects import config_values
        final_values = config_values(final_path)
    else:
        final_values = {}
    survived, lost = {}, {}
    for name, v in fragment.items():
        got = final_values.get(name, "")
        (survived if got == v else lost)[name] = {"requested": v, "got": got}
    result["survived"] = survived
    result["lost"] = lost
    if compile_targets:
        builds = {}
        for obj in compile_targets:
            cp = subprocess.run(make_base + [obj], cwd=str(dest),
                                capture_output=True, text=True, timeout=timeout)
            builds[obj] = {"rc": cp.returncode,
                          "built": (dest / obj).is_file(),
                          "stderr_tail": "\n".join(cp.stderr.splitlines()[-20:])}
        result["compile"] = builds
    return result
