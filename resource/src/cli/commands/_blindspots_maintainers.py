"""Parse a Linux-style MAINTAINERS file and map object/source paths to the
entries that claim them, following scripts/get_maintainer.pl's
``file_match_pattern``/``read_maintainer_file`` semantics as closely as is
practical for a static, non-git-aware tool.

Pattern semantics (mirrors get_maintainer.pl):
  - F:/X: patterns have ``.`` -> ``\\.``, ``*`` -> ``.*``, ``?`` -> ``.``
    applied, then are matched as a Python regex anchored at the start of the
    path (``re.match``), i.e. "path startswith something the pattern
    matches".
  - A pattern ending in ``/`` (or a literal, wildcard-free path that names an
    actual directory in the tree -- get_maintainer.pl checks ``-d $value``)
    is a recursive directory match: any path under it matches, regardless of
    depth.
  - Any other pattern only matches paths with exactly the same number of
    ``/`` as the raw pattern (get_maintainer.pl's ``$s1 == $s2`` check) --
    this is how ``drivers/net/*`` matches ``drivers/net/bonding.c`` but not
    ``drivers/net/usb/asix.c``.
  - X: patterns exclude a path from an entry entirely (checked first, like
    get_maintainer.pl).
  - N: patterns are Python ``re.VERBOSE`` regexes searched (not anchored)
    anywhere in the path, like Perl's ``m/$value/x``.
  - K: (content regex) patterns are not implemented: they match patch/file
    *contents*, not paths, and blindspots only ever looks at object paths.

Deviations from get_maintainer.pl, documented rather than fixed:
  - get_maintainer.pl's ``-d $value`` directory check runs against the
    *current working directory* at the time the script executes (usually
    the repo root); here it is always resolved against the analyzed tree
    root, which is the intended equivalent.
  - get_maintainer.pl folds in `git log`/blame history and keyword (K:)
    matches to widen the maintainer set for a patch; this module only ever
    resolves *static* F:/X:/N: path matches, since blindspots reasons about
    which entries "own" a path, not who to CC on a patch.
  - When several entries match a path, get_maintainer.pl returns *all* of
    them (sorted by pattern depth, for display only -- with the default
    ``--pattern-depth=0`` nothing is dropped). This module instead keeps
    only the entries at the *maximum* matched depth ("most specific
    matching entries"), so a catch-all entry (e.g. "THE REST", `F: *`)
    never shadows or dilutes a more specific one. This is a deliberate
    simplification for grouping/attribution, not a bug: it means a path
    claimed by both a broad and a narrow entry is attributed only to the
    narrow one.
"""
import re
from dataclasses import dataclass, field


_FIELD_RE = re.compile(r"^([A-Z]+):\s*(.*)$")


@dataclass
class Pattern:
    raw: str          # pattern text as written in MAINTAINERS
    is_dir: bool       # recursive directory match (trailing slash, or a real dir)
    depth: int         # specificity score: more slashes/chars = more specific
    regex: re.Pattern  # compiled, anchored at the start (re.match)
    slash_count: int   # slashes in the raw pattern (for the non-dir equal-count rule)

    def matches(self, path):
        if not self.regex.match(path):
            return False
        if self.is_dir:
            return True
        return path.count("/") == self.slash_count


@dataclass
class Entry:
    id: int
    title: str
    m: list = field(default_factory=list)
    l: list = field(default_factory=list)
    f: list = field(default_factory=list)   # list[Pattern]
    x: list = field(default_factory=list)   # list[Pattern]
    n: list = field(default_factory=list)   # list[re.Pattern]


def _build_regex_text(value):
    out = []
    for ch in value:
        if ch == ".":
            out.append(r"\.")
        elif ch == "*":
            out.append(".*")
        elif ch == "?":
            out.append(".")
        else:
            out.append(re.escape(ch))
    return "".join(out)


def _is_real_dir(value, tree):
    if tree is None:
        return False
    try:
        return (tree / value.rstrip("/")).is_dir()
    except OSError:
        return False


def _make_pattern(raw, tree):
    has_wildcard = ("*" in raw) or ("?" in raw)
    is_dir = raw.endswith("/") or (not has_wildcard and _is_real_dir(raw, tree))
    normalized = raw if raw.endswith("/") or not is_dir else raw + "/"
    slash_count = raw.count("/")
    depth = normalized.count("/") if is_dir else slash_count
    regex = re.compile("^" + _build_regex_text(normalized))
    return Pattern(raw=raw, is_dir=is_dir, depth=depth, regex=regex, slash_count=slash_count)


def parse(text, tree=None):
    """Entries of a MAINTAINERS file's text. ``tree`` (a Path), if given, is
    used to detect wildcard-free F:/X: patterns that name a real directory
    (get_maintainer.pl's ``-d $value``), so they get recursive-directory
    semantics even without a trailing slash."""
    entries = []
    block = []

    def flush(block):
        if len(block) < 2:
            return
        title = block[0].strip()
        fields = []
        for line in block[1:]:
            m = _FIELD_RE.match(line)
            if m:
                fields.append((m.group(1), m.group(2).strip()))
        if not fields or _FIELD_RE.match(block[0]):
            return
        e = Entry(id=len(entries), title=title)
        for typ, value in fields:
            if typ == "M":
                e.m.append(value)
            elif typ == "L":
                e.l.append(value)
            elif typ == "F":
                e.f.append(_make_pattern(value, tree))
            elif typ == "X":
                e.x.append(_make_pattern(value, tree))
            elif typ == "N":
                try:
                    e.n.append(re.compile(value, re.VERBOSE))
                except re.error:
                    pass
        entries.append(e)

    for line in text.splitlines():
        if line.strip() == "":
            flush(block)
            block = []
        else:
            block.append(line)
    flush(block)
    return entries


class MaintainersIndex:
    """Maps object/source paths to the most specific MAINTAINERS entries
    that claim them (see module docstring for the matching semantics)."""

    def __init__(self, entries):
        self.entries = entries
        self._dir_buckets = {}      # top segment -> [(entry, Pattern)]
        self._file_buckets = {}     # top segment -> [(entry, Pattern)]
        self._wild_global = []      # [(entry, Pattern)] with no literal top segment
        self._n_global = []         # [(entry, re.Pattern)]
        for e in entries:
            for pat in e.f:
                top = pat.raw.split("/", 1)[0]
                has_wc = ("*" in top) or ("?" in top)
                if pat.is_dir and not has_wc:
                    self._dir_buckets.setdefault(top, []).append((e, pat))
                elif not has_wc:
                    self._file_buckets.setdefault(top, []).append((e, pat))
                else:
                    self._wild_global.append((e, pat))
            for rx in e.n:
                self._n_global.append((e, rx))

    def _candidate_patterns(self, path):
        top = path.split("/", 1)[0]
        cands = list(self._dir_buckets.get(top, ())) + list(self._file_buckets.get(top, ()))
        cands += self._wild_global
        # a top-level directory pattern (e.g. "drivers/") also has "drivers"
        # as its own top segment, already covered above; but a dir pattern
        # for an ancestor bucketed under a *different* literal top segment
        # than the file's own can't match a startswith-anchored regex, so
        # bucketing by the path's own top segment is exhaustive for F:.
        return cands

    def entries_for(self, path):
        """(entries, depth) of the most specific MAINTAINERS entries
        claiming ``path``; ``([], None)`` if none do."""
        depths = {}  # entry.id -> (best depth for this entry, entry)
        for e, pat in self._candidate_patterns(path):
            if not pat.matches(path):
                continue
            if any(xp.matches(path) for xp in e.x):
                continue
            prev = depths.get(e.id)
            if prev is None or pat.depth > prev[0]:
                depths[e.id] = (pat.depth, e)
        N_DEPTH = 0
        for e, rx in self._n_global:
            if e.id in depths:
                continue
            if any(xp.matches(path) for xp in e.x):
                continue
            if rx.search(path):
                depths[e.id] = (N_DEPTH, e)
        if not depths:
            return [], None
        best_depth = max(d for d, _ in depths.values())
        best = [e for d, e in depths.values() if d == best_depth]
        return best, best_depth
