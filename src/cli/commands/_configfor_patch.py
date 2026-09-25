"""Extract touched file paths from a unified diff (``git diff`` or
``git format-patch`` output)."""
import re

_PLUS_HEADER = re.compile(r"^\+\+\+ (?:b/)?(\S+)")
_GIT_HEADER = re.compile(r"^diff --git a/(\S+) b/(\S+)")


def looks_like_patch(text):
    return bool(_GIT_HEADER.search(text) or re.search(r"^--- ", text, re.M)
                or re.search(r"^\+\+\+ ", text, re.M))


def touched_paths(text):
    """Paths added or modified by a unified diff, in order, de-duplicated;
    deleted files (``+++ /dev/null``) are omitted."""
    paths, seen = [], set()
    for m in _GIT_HEADER.finditer(text):
        pass  # git headers alone don't tell us add/mod/delete; +++ lines do
    for line in text.splitlines():
        m = _PLUS_HEADER.match(line)
        if not m:
            continue
        path = m.group(1).split("\t", 1)[0]
        if path == "/dev/null" or path in seen:
            continue
        seen.add(path)
        paths.append(path)
    return paths
