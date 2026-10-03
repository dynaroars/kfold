"""Import conservative historical module observations.

The importer records what a source said was observed; it never turns absence
from a history file into proof that a module is unused.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def import_modules(path: Path) -> dict[str, Any]:
    raw = path.read_text(errors="replace")
    modules: set[str] = set()
    for line in raw.splitlines():
        value = line.strip().split()[0] if line.strip() else ""
        if value and not value.startswith("#"):
            modules.add(value.removesuffix(".ko").replace("-", "_"))
    return {
        "schema": "smartconfig.history.v1",
        "source": str(path.resolve()),
        "source_hash": hashlib.sha256(raw.encode()).hexdigest(),
        "observed_modules": sorted(modules),
        "coverage": {
            "kind": "imported_module_list",
            "absence_means": "unknown",
            "timing": "unknown",
            "scope": "source-file",
        },
    }


def write_import(path: Path, out: Path) -> dict[str, Any]:
    data = import_modules(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    tmp.replace(out)
    return data
