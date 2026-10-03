"""kfold lint --diff PATCH: apply a patch to a scratch copy of the tree and
compare Kbuild conditions / run checks 1-3 restricted to what it touches.

Not auto-discovered (leading underscore); imported by ``cli.commands.lint``.
"""
import pathlib
import re
import shutil
import subprocess
import tempfile

import z3

from cli import common
from cli.commands import _lint_kconfig, _lint_sources

_DIFF_GIT_RE = re.compile(r"^diff --git a/(.*?) b/(.*)$", re.MULTILINE)
_PLUS_HDR_RE = re.compile(r"^\+\+\+ (?:b/)?(.*)$", re.MULTILINE)
_CONFIG_RE = re.compile(r"\bCONFIG_[A-Za-z0-9_]+\b")


def touched_files(patch_text):
    """Paths a unified diff touches, from ``diff --git`` headers if present,
    else the ``+++`` header of each hunk (skipping /dev/null, for deletes we
    still want the a/ side -- callers use this only to name Makefile/Kconfig
    files, so falling back to the new-file name is a minor approximation)."""
    files = [m.group(2) for m in _DIFF_GIT_RE.finditer(patch_text)]
    if files:
        return files
    out = []
    for m in _PLUS_HDR_RE.finditer(patch_text):
        f = m.group(1).strip()
        if f and f != "/dev/null":
            out.append(f)
    return out


def kbuild_related(files):
    """The subset of ``files`` that are Makefile/Kbuild/Kconfig files, whose
    hunks the spec asks us to focus the diff and checks 1-3 on."""
    out = []
    for f in files:
        name = pathlib.Path(f).name
        if name in ("Makefile", "Kbuild") or name.startswith("Kconfig"):
            out.append(f)
    return out


def apply_patch(tree, patch_path, scratch_dir):
    """Copy ``tree`` into ``scratch_dir / 'tree'`` and apply ``patch_path``
    there (never touches ``tree`` itself). Returns the scratch tree path."""
    dest = scratch_dir / "tree"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(tree, dest, symlinks=True,
                    ignore=shutil.ignore_patterns(".git"))
    patch_path = pathlib.Path(patch_path).resolve()
    r = subprocess.run(["patch", "-p1", "--fuzz=3", "--no-backup-if-mismatch",
                        "-i", str(patch_path)],
                       cwd=dest, capture_output=True, text=True)
    if r.returncode != 0:
        r2 = subprocess.run(["git", "apply", "--unsafe-paths", "-p1", str(patch_path)],
                            cwd=dest, capture_output=True, text=True)
        if r2.returncode != 0:
            raise common.CLIError(
                f"could not apply {patch_path} to a scratch copy of {tree}:\n"
                f"patch: {r.stdout.strip()}\n{r.stderr.strip()}\n"
                f"git apply: {r2.stdout.strip()}\n{r2.stderr.strip()}")
    return dest


def _equivalent(a, b):
    if not (isinstance(a, z3.ExprRef) and isinstance(b, z3.ExprRef)):
        return a == b
    if a.get_id() == b.get_id():
        return True
    s = z3.Solver()
    s.set("timeout", 10000)
    s.add(a != b)
    return s.check() == z3.unsat


def run(before, args, tree):
    """before: the cached Analysis of the unmodified ``tree``. Returns the
    ``kfold lint --diff`` report dict."""
    from cli import cache as cache_mod
    patch_path = pathlib.Path(args.diff).expanduser()
    if not patch_path.is_file():
        raise common.CLIError(f"{args.diff}: no such patch file")
    patch_text = patch_path.read_text(errors="ignore")
    files = touched_files(patch_text)
    kb_files = kbuild_related(files)

    scratch_root = (pathlib.Path(args.scratch).expanduser() if args.scratch
                    else pathlib.Path(tempfile.mkdtemp(prefix="kfold-lint-", dir="/tmp")))
    scratch_root.mkdir(parents=True, exist_ok=True)
    dest = apply_patch(tree, patch_path, scratch_root)
    after = cache_mod.analyze(dest, scratch_root / "cache", log=None)

    touched_set = set(kb_files)
    impacted = set()
    for p, origs in before.origins.items():
        if any(mk in touched_set for mk, _ in origs):
            impacted.add(p)
    for p, origs in after.origins.items():
        if any(mk in touched_set for mk, _ in origs):
            impacted.add(p)

    changes = []
    for p in sorted(impacted):
        bcond = before.conds[p] if p in before.conds else None
        acond = after.conds[p] if p in after.conds else None
        if bcond is None and acond is None:
            continue
        if bcond is None:
            changes.append({"object": p, "change": "added",
                            "before": None, "after": common.display_cond(acond)})
        elif acond is None:
            changes.append({"object": p, "change": "removed",
                            "before": common.display_cond(bcond), "after": None})
        elif not _equivalent(bcond, acond):
            changes.append({"object": p, "change": "changed",
                            "before": common.display_cond(bcond),
                            "after": common.display_cond(acond)})

    findings = []
    # Check 1 (zombie), restricted to symbols the patch's Makefile/Kconfig
    # hunks actually mention, evaluated against the patched Kconfig.
    declared_after = _lint_kconfig.declared_symbols(dest)
    for f in kb_files:
        p = dest / f
        if not p.is_file():
            continue
        for i, line in enumerate(p.read_text(errors="ignore").splitlines(), 1):
            for m in _CONFIG_RE.finditer(line):
                sym = m.group(0)
                arches = declared_after.get(sym)
                if arches is None or not _lint_kconfig.is_in_scope(arches, args.arch):
                    findings.append({
                        "class": "zombie", "symbol": sym, "file": f, "line": i,
                        "message": f"{sym} (patched {f}:{i}) has no Kconfig definition "
                                   f"in the patched tree",
                        "severity": "error"})
    # Check 2 (orphan), restricted to .c/.S files the patch touches.
    for f in files:
        if not f.endswith((".c", ".S")):
            continue
        p = dest / f
        if not p.is_file():
            continue
        rel_parts = pathlib.Path(f).parts
        if not _lint_sources.in_scope(rel_parts, args.arch):
            continue
        obj_rel = str(pathlib.Path(f).with_suffix(".o"))
        if obj_rel not in after.conds:
            findings.append({
                "class": "orphan", "file": f, "line": None,
                "message": f"{f} (touched by the patch) is built by no Makefile "
                           f"in the patched tree",
                "severity": "warning"})
    # Check 3 (dead), restricted to the impacted objects, on the patched tree.
    try:
        kc = _lint_kconfig.KconfigConstraints(dest, kconfig_rel=args.kconfig,
                                              solver=after.solver())
        for p, status, incomplete, cause, extra in _lint_kconfig.dead_check(after, kc, paths=impacted):
            arch_dead = cause == "arch-dead"
            findings.append({
                "class": "dead", "file": p, "line": None,
                "message": f"{p} is unsatisfiable under Kbuild" +
                           ("" if status == "kbuild" else f" and Kconfig ({cause})") +
                           " in the patched tree" +
                           (" (Kconfig parse incomplete; verify independently)"
                            if incomplete else ""),
                "severity": "info" if (incomplete or arch_dead) else "error",
                "status": status, "incomplete": incomplete, "cause": cause,
                "arch_dead": arch_dead,
                "bool_composite_container": extra.get("bool_composite_container", False)})
    except FileNotFoundError:
        pass

    return {
        "tree": str(tree), "patch": str(patch_path), "scratch": str(dest),
        "touched_files": files, "touched_kbuild_files": kb_files,
        "impacted_objects": len(impacted), "condition_changes": changes,
        "findings": findings,
    }
