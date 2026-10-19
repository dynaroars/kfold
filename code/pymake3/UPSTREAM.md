# pymake upstream provenance

This directory is a Python 3 port of Mozilla's `pymake`, a mostly
GNU-Make-compatible Make implementation originally written by Benjamin
Smedberg and later maintained by Mozilla contributors.

The authoritative repository is archived and unmaintained:

- Repository: <https://github.com/mozilla/pymake>
- Final revision: `034ae9ea5b726e03647d049147c5dbf688e94aaf`
- Final revision date: 2014-07-08
- Archive date checked: 2026-09-09
- Upstream archive SHA-256:
  `4d3f2cafd55a0c8a5e8052495feb27fdc58cd98fdba37b338166e8135d065475`
- License: MIT; see `LICENSE` in this directory.

There are no upstream releases or later official revisions. The similarly
named `mfpymake` project on PyPI and conda is unrelated and is not a valid
update source.

Compared with the final upstream tree, this copy has package imports updated
from `pymake` to `pymake3`, Python 3 compatibility changes, and formatting
changes. The obsolete, unused `imp` import was removed for Python 3.12+ and
the Windows-only package import was corrected to `pymake3`. Replacing this
copy with the upstream snapshot would restore Python 2 code and break the
current analyzer.

During the Lean migration this code is frozen except for narrowly scoped fixes
needed by differential tests. It is a temporary parsing and behavioral oracle,
not a production dependency of the final Lean executable.
