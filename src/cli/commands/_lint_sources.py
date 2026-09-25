"""kfold lint helper: orphan source files (.c/.S built by no Makefile).

Not auto-discovered (leading underscore); imported by ``cli.commands.lint``.
"""
import pathlib
import re

# Directories excluded from the orphan-source scan per the phase-2C spec:
# tools/, scripts/, and Documentation/ are not part of the kernel proper
# (host tooling / build scripts / docs); samples/ builds its own tiny,
# self-contained example modules that kfold's analysis of the main tree does
# not need to reach for this check to be meaningful, and its buildability is
# governed by its own local Makefiles that this scan already checks.
_EXCLUDE_TOP = ("tools", "scripts", "Documentation", "samples")

_INCLUDE_C_RE = re.compile(r'#\s*include\s*"([^"]+\.c)"')


def in_scope(rel_parts, arch):
    """Whether a source path (parts, relative to the tree) is in the scope
    that a single-arch analysis (``arch``, e.g. "x86") actually reaches:
    excludes the listed non-kernel directories and other archs' arch/<name>
    trees (never analyzed for this arch, so absence from the cache there
    would be a false "orphan", not a real one)."""
    if not rel_parts:
        return False
    if rel_parts[0] in _EXCLUDE_TOP:
        return False
    if rel_parts[0] == "arch" and (len(rel_parts) < 2 or rel_parts[1] != arch):
        return False
    return True


def find_sources(tree, arch):
    out = []
    for ext in ("*.c", "*.S"):
        for p in tree.rglob(ext):
            if not p.is_file():
                continue
            rel = p.relative_to(tree)
            if in_scope(rel.parts, arch):
                out.append(p)
    return sorted(out)


def included_c_basenames(c_files):
    """Basenames of .c files that some other .c file ``#include``s (e.g. the
    x86 SIMD "glue" pattern of #including a shared body); these are never
    Makefile targets of their own and must not be flagged as orphans.
    Matched by filename only (not by directory), which is deliberately
    permissive: it may hide a genuine orphan that happens to share a name
    with an included file elsewhere, but that trades a rare false negative
    for a much lower false positive rate."""
    included = set()
    for f in c_files:
        try:
            text = f.read_text(errors="ignore")
        except OSError:
            continue
        for m in _INCLUDE_C_RE.finditer(text):
            included.add(pathlib.Path(m.group(1)).name)
    return included


def orphan_check(analysis, tree, arch="x86", path_prefix=None):
    """[{file, line, message, severity}] .c/.S files with no obj-y/lib-y/
    rule reference in the cached analysis. A file counts as referenced if
    <same dir>/<stem>.o is a known object (covers direct obj-y/lib-y
    listing, composite -y/-objs members, and implicit %.o<-%.c/%.S rule
    prerequisites, all of which ``cache.Analysis.conds`` already resolves)."""
    all_sources = find_sources(tree, arch)
    c_files = [p for p in all_sources if p.suffix == ".c"]
    included = included_c_basenames(c_files)
    findings = []
    for p in all_sources:
        rel = p.relative_to(tree)
        if path_prefix and not str(rel).startswith(path_prefix):
            continue
        if rel.name in included:
            continue
        if "generated" in rel.parts:
            continue
        obj_rel = str(rel.with_suffix(".o"))
        if obj_rel in analysis.conds:
            continue
        findings.append({
            "class": "orphan", "file": str(rel), "line": None,
            "message": f"{rel} is built by no Makefile (no obj-y/lib-y/rule "
                       f"reaches {obj_rel})",
            "severity": "warning",
        })
    return findings
