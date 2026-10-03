"""Artifact identity and post-build inventory records."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory(source: Path, config: Path | None = None) -> dict[str, Any]:
    source = source.resolve()
    files = [
        source / "arch/x86/boot/bzImage",
        source / "vmlinux",
    ]
    artifacts = []
    for path in files:
        if path.is_file():
            artifacts.append({"path": str(path), "bytes": path.stat().st_size,
                              "sha256": _sha256(path), "kind": path.name})
    modules = []
    for root in (source / "lib/modules", source / "modules"):
        if root.is_dir():
            for path in sorted(root.rglob("*.ko*")):
                if path.is_file():
                    modules.append({"path": str(path), "bytes": path.stat().st_size,
                                    "sha256": _sha256(path)})
    release = "unknown"
    if (source / "Makefile").exists():
        result = subprocess.run(["make", "-s", "-C", str(source), "kernelrelease"],
                                capture_output=True, text=True, timeout=30, check=False)
        if result.returncode == 0 and result.stdout.strip():
            release = result.stdout.strip().splitlines()[-1]
    return {"schema": "smartconfig.artifacts.v1", "source": str(source),
            "kernelrelease": release, "config": ({"path": str(config.resolve()),
            "sha256": _sha256(config)} if config and config.is_file() else None),
            "artifacts": artifacts, "modules": modules,
            "limitations": ["initramfs inclusion is not inferred from module files",
                            "package metadata is unavailable until a package is built"]}


def write_inventory(source: Path, out: Path, config: Path | None = None) -> dict[str, Any]:
    data = inventory(source, config)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    tmp.replace(out)
    return data


def vm_validation(kernel: Path, out: Path) -> dict[str, Any]:
    qemu = shutil.which("qemu-system-x86_64")
    result = {"schema": "smartconfig.validation.v1", "test_id": "vm-smoke",
              "environment": "VM", "kernel": str(kernel.resolve()),
              "status": "unknown", "preconditions": [], "cleanup": "not_applicable"}
    if not kernel.is_file():
        result["status"] = "skip"
        result["preconditions"].append("kernel artifact is missing")
    elif not qemu:
        result["status"] = "skip"
        result["preconditions"].append("qemu-system-x86_64 is unavailable")
    else:
        result["status"] = "unknown"
        result["preconditions"].append("VM harness is available but no guest image was supplied")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    tmp.replace(out)
    return result
