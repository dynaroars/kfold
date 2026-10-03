"""Target-scoped capability mapping records."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from autokernel.capabilities import RECIPES


def _declared_symbols(source: Path) -> set[str]:
    declared: set[str] = set()
    for path in source.rglob("Kconfig*"):
        if path.is_file():
            try:
                text = path.read_text(errors="replace")
            except OSError:
                continue
            declared.update(re.findall(r"(?m)^\s*(?:config|menuconfig)\s+([A-Z0-9_]+)\s*$", text))
    return {"CONFIG_" + name for name in declared}


def _symbols(condition: Any) -> list[str]:
    if not isinstance(condition, dict):
        return []
    result: list[str] = []
    if condition.get("symbol"):
        value = str(condition["symbol"])
        result.append(value if value.startswith("CONFIG_") else "CONFIG_" + value)
    for key in ("all", "any"):
        for item in condition.get(key, []):
            result.extend(_symbols(item))
    if "not" in condition:
        result.extend(_symbols(condition["not"]))
    return sorted(set(result))


def build_mapping(source: Path, capabilities: list[str] | None = None) -> dict[str, Any]:
    source = source.resolve()
    names = capabilities or list(RECIPES)
    identity = hashlib.sha256()
    for filename in ("Makefile", "Kconfig"):
        path = source / filename
        if path.exists():
            identity.update(filename.encode() + b"\0" + path.read_bytes())
    records = []
    declared = _declared_symbols(source)
    for name in names:
        recipe = RECIPES[name]
        symbols = _symbols(recipe.condition)
        available: bool | None = None
        method = "maintained_recipe"
        try:
            from autokernel.kconfig_walk import walk
            surface = walk(source)
            known = {"CONFIG_" + t.name for t in surface.toggles + surface.tunables}
            known.update("CONFIG_" + option.name for choice in surface.choices for option in choice.options)
            # The surface walker intentionally omits tristates; source
            # declaration presence is the fallback needed for capability
            # recipes whose providers are commonly tristate.
            available = all(symbol in known or symbol in declared for symbol in symbols)
            method = "native+source-declaration+maintained_recipe"
        except Exception:
            method = "maintained_recipe"
        records.append({"capability": name, "symbols": symbols, "available": available,
                        "method": method, "completeness": "complete" if available else "unknown"})
    return {"schema": "smartconfig.mapping.v1", "target_identity": identity.hexdigest(),
            "source": str(source), "records": records,
            "limitations": ["mapping does not certify runtime behavior or firmware"]}


def write_mapping(source: Path, out: Path, capabilities: list[str] | None = None) -> dict[str, Any]:
    data = build_mapping(source, capabilities)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    tmp.replace(out)
    return data
