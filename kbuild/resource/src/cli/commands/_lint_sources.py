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
# governed by its own local Makefiles that this scan already checks. Checked
# against every path component (not just the top-level one): the checkpoint
# run found nested Documentation/ and tools/ directories deep in the tree
# (e.g. drivers/staging/greybus/Documentation/firmware/*.c,
# drivers/comedi/drivers/ni_routing/tools/convert_c_to_py.c) that a
# top-level-only check missed.
_EXCLUDE_ANYWHERE = ("tools", "scripts", "Documentation", "samples")

_INCLUDE_C_RE = re.compile(r'#\s*include\s*"([^"]+\.[cS])"')

# Kbuild-generated modpost stub sources (one per module, produced by
# scripts/mod/modpost during a real build) and linker-script sources (never
# compiled to a .o at all, only preprocessed to .lds): neither is a source
# file any Makefile is expected to list. The checkpoint run found ~4,100
# stale *.mod.c files (96% of the initial 4,279 "orphans") left over in this
# workspace from a prior real build -- these are Kbuild's own output, not
# input, and would be regenerated/discarded on a clean checkout.
_GENERATED_SUFFIXES = (".mod.c",)
# "*.bpf.c" is a fixed Linux convention for eBPF "skeleton" sources compiled
# by a dedicated clang/bpftool pipeline in their own small, non-Kbuild
# Makefile (e.g. drivers/hid/bpf/entrypoints/Makefile,
# kernel/bpf/preload/iterators/Makefile: "$(OUTPUT)/%.bpf.o: %.bpf.c ...",
# invoked once via a plain sub-make, not through obj-y/hostprogs), so they
# never appear in kfold's Kbuild-object model at all -- confirmed by reading
# both Makefiles during checkpoint verification.
_NEVER_KBUILD_SUFFIXES = (".bpf.c",)
_LDS_SOURCE_RE = re.compile(r"\.lds\.S$")

# Kbuild's own offsets-style idiom: a .c compiled only to an intermediate .s
# (never a .o) to extract struct-layout constants via a post-processing
# script, declared via "targets += foo.s" (see kernel/bounds.c, top-level
# Kbuild; arch/x86/kvm/kvm-asm-offsets.c, arch/x86/kvm/Makefile; and every
# arch's kernel/asm-offsets.c, generated from the top-level Kbuild file's
# "targets += arch/$(SRCARCH)/kernel/asm-offsets.s"). Recognized generically
# below via the "targets" variable scan, not by filename.

_LINE_CONT_RE = re.compile(r"\\\r?\n\s*")


def _joined(text):
    """Backslash-continued lines joined into one logical line, so a regex
    over a single line sees a whole "VAR = a b \\\n    c d" assignment."""
    return _LINE_CONT_RE.sub(" ", text)


def in_scope(rel_parts, arch):
    """Whether a source path (parts, relative to the tree) is in the scope
    that a single-arch analysis (``arch``, e.g. "x86") actually reaches:
    excludes the listed non-kernel directories (at any depth) and other
    archs' arch/<name> trees (never analyzed for this arch, so absence from
    the cache there would be a false "orphan", not a real one)."""
    if not rel_parts:
        return False
    if any(p in _EXCLUDE_ANYWHERE for p in rel_parts):
        return False
    if rel_parts[0] == "arch" and (len(rel_parts) < 2 or rel_parts[1] != arch):
        return False
    # arch/x86/um is User-Mode-Linux's x86 overlay: it is reached only from
    # arch/um/Makefile's "core-y += $(HOST_DIR)/um/" when ARCH=um (a
    # different arch, SRCARCH=um), never from arch/x86/Makefile -- confirmed
    # by checkpoint verification (no reference to it anywhere under
    # arch/x86/). Physically nested under arch/x86/ but out of scope for an
    # ARCH=x86 analysis, the same reasoning as excluding arch/<other-arch>.
    if arch == "x86" and len(rel_parts) >= 3 and rel_parts[0] == "arch" \
            and rel_parts[1] == "x86" and rel_parts[2] == "um":
        return False
    return True


def find_sources(tree, arch):
    out = []
    for ext in ("*.c", "*.S"):
        for p in tree.rglob(ext):
            if not p.is_file():
                continue
            name = p.name
            if (any(name.endswith(s) for s in _GENERATED_SUFFIXES + _NEVER_KBUILD_SUFFIXES)
                    or _LDS_SOURCE_RE.search(name)):
                continue
            rel = p.relative_to(tree)
            if in_scope(rel.parts, arch):
                out.append(p)
    return sorted(out)


def included_c_basenames(source_files):
    """Basenames of .c/.S files that some other .c/.S file ``#include``s
    (e.g. the x86 SIMD "glue" pattern of #including a shared .c body, or
    assembly files sharing macros/common code via #include "foo.S" --
    verified during checkpoint verification against real cases:
    arch/x86/crypto/*-avx*-asm_64.S including glue_helper-asm-avx*.S,
    arch/x86/kernel/head_64.S including verify_cpu.S/sev_verify_cbit.S/
    ../../x86/xen/xen-head.S, arch/x86/realmode/rm/trampoline_64.S including
    trampoline_common.S); these are never Makefile targets of their own and
    must not be flagged as orphans. Matched by filename only (not by
    directory), which is deliberately permissive: it may hide a genuine
    orphan that happens to share a name with an included file elsewhere,
    but that trades a rare false negative for a much lower false positive
    rate."""
    included = set()
    for f in source_files:
        try:
            text = f.read_text(errors="ignore")
        except OSError:
            continue
        for m in _INCLUDE_C_RE.finditer(text):
            included.add(pathlib.Path(m.group(1)).name)
    return included


# ---------------------------------------------------------------- indirect references
#
# kfold's Kbuild analyzer (src/objects.py, not editable from this phase)
# resolves the standard family idioms directly: obj-$(CONFIG_X), lib-y,
# "<name>-y"/"<name>-objs" composite members, hostprogs with a "<name>-objs"
# composite, and implicit %.o<-%.c/%.S rule prerequisites. A handful of
# common but less-standard idioms fall outside that and made real files look
# orphaned in the whole-tree checkpoint run; the functions below are a
# narrow, text-level (not full Make-semantics) supplement scoped to exactly
# those idioms, found by manually tracing why specific checkpoint findings
# were false positives.

_TARGETS_RE = re.compile(r"^\s*targets\s*[:+]?=\s*(.*)$", re.MULTILINE)
_HOSTUSERPROGS_RE = re.compile(r"^\s*(?:hostprogs(?:-y)?|userprogs)\s*[:+]?=\s*(.*)$", re.MULTILINE)
_COMPOSITE_FAMILY_RE = re.compile(
    r"^\s*([A-Za-z_][\w-]*)-\$\(CONFIG_[A-Za-z0-9_]+\)\s*[:+]?=\s*(.*)$", re.MULTILINE)
_PLAIN_VAR_DEF_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*[:+]?=\s*(.*)$", re.MULTILINE)
_VAR_REF_RE = re.compile(r"\$\((\w+)\)")
_OBJ_TOKEN_RE = re.compile(r"[\w./-]+\.[oOsSaA](?:bj)?\b")
# "$(wildcard $(srctree)/$(src)/SUBDIR/*...)": a Makefile that globs a whole
# subdirectory's sources for some build step (e.g. lib/Makefile's
# "TEST_FORTIFY_SRCS = $(wildcard $(srctree)/$(src)/test_fortify/*-*.c)",
# which runs each file through scripts/test_fortify.sh to *.log files, never
# producing a .o at all) clearly treats every file the glob matches as part
# of the build, even though no single file is named. Kfold's Kbuild model
# has no notion of $(wildcard ...), so this is a from-scratch text heuristic
# rather than a supplement to something the analyzer already tracks.
_WILDCARD_DIR_RE = re.compile(r"\$\(wildcard\s+\$\(srctree\)/\$\(src\)/([\w./-]+?)/\*[^)]*\)")


def _dir_relative(mk_rel_dir, token):
    """A Makefile RHS token (possibly $(obj)/-prefixed, possibly with a
    $(SRCARCH) macro this scan knows how to resolve) as a tree-relative
    path. Returns None for tokens this narrow scan cannot resolve (e.g. an
    unknown make variable) rather than guessing."""
    token = token.strip()
    if not token or "$(" in token and not token.startswith("$(obj)/") \
            and "$(SRCARCH)" not in token:
        return None
    token = token.replace("$(obj)/", "").replace("$(SRCARCH)", "x86")
    if token.startswith("$("):
        return None
    return str(pathlib.Path(mk_rel_dir) / token)


def indirect_references(mk_rel, text):
    """Tree-relative .c/.S paths that a Makefile's text implies are built,
    beyond what kfold's own analyzer already resolves (see module docstring
    above): "targets += foo.s" (offsets-style intermediates: kernel/bounds.c,
    */asm-offsets.c), "hostprogs := name" / "userprogs := name" for a
    single-file host/user program with no separate "<name>-objs" composite
    (e.g. arch/x86/boot/Makefile's "hostprogs := tools/build"), and
    "NAME-$(CONFIG_X) += a.o b.o" composite family members named with an
    embedded CONFIG_ conditional rather than a plain "<name>-y" (e.g.
    crypto/Makefile's "aegis128-$(CONFIG_CRYPTO_AEGIS128_SIMD) += aegis128-neon.o
    aegis128-neon-inner.o") -- plus the common "obj-y = $(LISTVAR)" pattern of
    listing objects in an ordinary variable and selecting it wholesale
    (arch/x86/math-emu/Makefile's C_OBJS/A_OBJS)."""
    text = _joined(text)
    mk_dir = str(pathlib.Path(mk_rel).parent)
    out = set()

    def add_stem_sources(rel_no_ext):
        out.add(rel_no_ext + ".c")
        out.add(rel_no_ext + ".S")

    # "targets += foo.s" / "targets := dir/foo.o" etc: whatever extension is
    # named, the matching .c/.S in the same relative location is "used".
    for m in _TARGETS_RE.finditer(text):
        for tok in m.group(1).split():
            if tok in ("FORCE",) or tok.startswith("$("):
                tok = tok if not tok.startswith("$(obj)/") else tok
            full = _dir_relative(mk_dir, tok)
            if full and full.rsplit(".", 1)[-1] in ("o", "s", "a"):
                add_stem_sources(full.rsplit(".", 1)[0])

    # "hostprogs := name" / "hostprogs += a b" / "userprogs := name": a name
    # with no separate composite ("<name>-objs"/"<name>-y") is a single-file
    # program compiled directly from "<name>.c" (name may itself contain a
    # subdirectory, e.g. "tools/build").
    composite_names = set()
    for m in re.finditer(r"^\s*([\w./-]+)-(?:objs|y)\s*[:+]?=", text, re.MULTILINE):
        composite_names.add(m.group(1))
    for m in _HOSTUSERPROGS_RE.finditer(text):
        for name in m.group(1).split():
            if name in composite_names or name.startswith("$("):
                continue
            add_stem_sources(str(pathlib.Path(mk_dir) / name))

    # "NAME-$(CONFIG_X) += a.o b.o": composite family members added through
    # a config-conditional variable name instead of plain "NAME-y"/"NAME-m".
    for m in _COMPOSITE_FAMILY_RE.finditer(text):
        for tok in m.group(2).split():
            if tok.endswith((".o", ".a")):
                full = _dir_relative(mk_dir, tok)
                if full:
                    add_stem_sources(full.rsplit(".", 1)[0])

    # "obj-y = $(LISTVAR)" where LISTVAR is an ordinary variable whose own
    # value is a list of .o files (not a family variable kfold expands).
    plain_lists = {}
    for m in _PLAIN_VAR_DEF_RE.finditer(text):
        name, val = m.group(1), m.group(2)
        if name.startswith(("obj-", "lib-", "extra-", "always-", "CONFIG_", "targets",
                            "hostprogs", "userprogs")):
            continue
        objs = _OBJ_TOKEN_RE.findall(val)
        if objs and all(tok.endswith((".o", ".a")) for tok in objs):
            plain_lists[name] = objs
    for m in re.finditer(r"^\s*(?:obj|lib|extra|always)-[\w$()]*\s*[:+]?=\s*(.*)$",
                         text, re.MULTILINE):
        for varname in _VAR_REF_RE.findall(m.group(1)):
            for tok in plain_lists.get(varname, ()):
                full = _dir_relative(mk_dir, tok)
                if full:
                    add_stem_sources(full.rsplit(".", 1)[0])

    return out


def wildcard_dirs(mk_rel, text):
    """Tree-relative directories a Makefile globs wholesale with
    ``$(wildcard $(srctree)/$(src)/DIR/*...)`` (see the module-level regex
    comment)."""
    mk_dir = pathlib.Path(mk_rel).parent
    return {str(mk_dir / m.group(1)) for m in _WILDCARD_DIR_RE.finditer(_joined(text))}


def build_indirect_index(tree, makefiles):
    """({tree-relative .c/.S path}, {tree-relative directory}) implied by
    ``indirect_references``/``wildcard_dirs`` across every Makefile in
    ``makefiles`` (tree-relative paths)."""
    allowed, wildcards = set(), set()
    for mk in makefiles:
        p = tree / mk
        try:
            text = p.read_text(errors="ignore")
        except OSError:
            continue
        allowed |= indirect_references(mk, text)
        wildcards |= wildcard_dirs(mk, text)
    return allowed, wildcards


def orphan_check(analysis, tree, arch="x86", path_prefix=None):
    """[{file, line, message, severity}] .c/.S files with no obj-y/lib-y/
    rule reference in the cached analysis. A file counts as referenced if
    <same dir>/<stem>.o is a known object (covers direct obj-y/lib-y
    listing, composite -y/-objs members, and implicit %.o<-%.c/%.S rule
    prerequisites, all of which ``cache.Analysis.conds`` already resolves),
    or if ``indirect_references`` (see above) finds it implied by a Makefile
    idiom the analyzer itself does not model."""
    all_sources = find_sources(tree, arch)
    included = included_c_basenames(all_sources)
    # analysis.reached/.builtin/.origins only cover Makefiles kfold's own
    # analyzer actually walked -- and a host-program *executable*
    # (hostprogs names like "tools/build" with no .o/.a suffix at all, e.g.
    # arch/x86/boot/Makefile) is invisible even to rule_closure's
    # prerequisite-following (it only recognizes targets ending in .o/.a),
    # so a Makefile whose only recorded contribution is such a program never
    # appears in the cache at all -- found during checkpoint verification
    # (arch/x86/boot/mkcpustr.c/mkpiggy.c looked orphaned only because
    # their own Makefile was invisible to the cache, not because of a gap
    # in the indirect-reference scan below). Scanning every Makefile/Kbuild
    # file physically present in the in-scope directory tree (the same
    # scope find_sources uses) instead of the cache's reachability set
    # sidesteps that gap; it is safe here because this index only *adds*
    # allowed paths, so scanning a Makefile the real build order might not
    # reach cannot turn a real orphan into a false negative for any other
    # check.
    makefiles = [p.relative_to(tree) for name in ("Makefile", "Kbuild")
                for p in tree.rglob(name) if p.is_file() and in_scope(p.relative_to(tree).parts, arch)]
    indirect, wildcard_scoped = build_indirect_index(tree, sorted(str(mk) for mk in makefiles))
    findings = []
    for p in all_sources:
        rel = p.relative_to(tree)
        if path_prefix and not str(rel).startswith(path_prefix):
            continue
        if rel.name in included:
            continue
        if str(rel.parent) in wildcard_scoped:
            continue
        if "generated" in rel.parts:
            continue
        if str(rel) in indirect:
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
