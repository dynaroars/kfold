#!/usr/bin/env python3
"""Record reproducible metadata and output for one skbuild analysis run."""

import argparse
import hashlib
import json
import os
import platform
import resource
import subprocess
import sys
import time
from pathlib import Path


def run(command, *, cwd):
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True)


def git_value(root, *args):
    result = run(["git", *args], cwd=root)
    return result.stdout.strip() if result.returncode == 0 else None


def snapshot_digest(path):
    digest = hashlib.sha256()
    files = []
    if path.is_file():
        files = [path]
    else:
        for candidate in path.rglob("*"):
            if candidate.is_file() or candidate.is_symlink():
                files.append(candidate)
    for candidate in sorted(files, key=lambda item: item.relative_to(path.parent).as_posix()):
        relative = candidate.relative_to(path).as_posix() if path.is_dir() else candidate.name
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        if candidate.is_symlink():
            digest.update(b"symlink\0")
            digest.update(os.readlink(candidate).encode("utf-8"))
        else:
            with candidate.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest(), len(files)


def file_digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analyzer", default=".lake/build/bin/skbuild")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("input", type=Path)
    parser.add_argument("analyzer_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    input_path = args.input.resolve()
    output_dir = args.output_dir.resolve()
    analyzer = Path(args.analyzer)
    if not analyzer.is_absolute():
        analyzer = root / analyzer
    if not input_path.exists():
        parser.error(f"input does not exist: {input_path}")
    output_dir.mkdir(parents=True, exist_ok=True)

    source_digest, input_file_count = snapshot_digest(input_path)
    revision = git_value(root, "rev-parse", "HEAD")
    dirty_result = run(["git", "diff", "HEAD"], cwd=root)
    dirty_diff = dirty_result.stdout if dirty_result.returncode == 0 else ""
    (output_dir / "dirty.diff").write_text(dirty_diff, encoding="utf-8")
    dirty_diff_digest = hashlib.sha256(dirty_diff.encode("utf-8")).hexdigest()
    command = [str(analyzer), "--json", *args.analyzer_args, str(input_path)]

    started = time.time()
    monotonic_started = time.perf_counter()
    result = subprocess.run(command, cwd=root, text=True, capture_output=True)
    elapsed = time.perf_counter() - monotonic_started
    (output_dir / "stderr.txt").write_text(result.stderr, encoding="utf-8")
    report_path = output_dir / "report.json"
    report = None
    if result.stdout.strip():
        try:
            report = json.loads(result.stdout)
            report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        except json.JSONDecodeError:
            report_path.write_text(result.stdout, encoding="utf-8")

    manifest = {
        "schema": 1,
        "started_unix_seconds": started,
        "elapsed_seconds": elapsed,
        "exit_code": result.returncode,
        "status": "success" if result.returncode == 0 else "command-failed",
        "command": command,
        "repository": str(root),
        "revision": revision,
        "dirty": bool(dirty_diff),
        "dirty_diff_sha256": dirty_diff_digest,
        "artifacts": {
            "dirty_diff": "dirty.diff",
            "report": "report.json" if report_path.exists() else None,
            "stderr": "stderr.txt",
        },
        "artifact_sha256": {
            "dirty_diff": dirty_diff_digest,
            "report": file_digest(report_path) if report_path.exists() else None,
            "stderr": file_digest(output_dir / "stderr.txt"),
        },
        "machine": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python": platform.python_version(),
        },
        "lean_toolchain": (root / "lean-toolchain").read_text(encoding="utf-8").strip(),
        "input": str(input_path),
        "input_sha256": source_digest,
        "input_file_count": input_file_count,
        "peak_rss_kib": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
    }
    if report is not None:
        files = report.get("files", [])
        diagnostics = report.get("diagnostics", [])
        manifest["result"] = {
            "schema": report.get("schema"),
            "complete": report.get("complete"),
            "file_count": len(files),
            "unique_condition_count": len({json.dumps(item.get("condition"), sort_keys=True) for item in files}),
            "diagnostic_count": len(diagnostics),
            "diagnostic_codes": sorted({item.get("code") for item in diagnostics}),
        }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
