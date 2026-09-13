#!/usr/bin/env python3
"""Acquire input and run the native Lean analyzer in one reproducible workspace."""

import argparse
import json
import platform
import subprocess
import sys
import time
from pathlib import Path


def analysis_root(source):
    if (source / "Kbuild").is_file() or (source / "Makefile").is_file():
        return source
    candidates = sorted(
        {
            path.parent
            for name in ("Kbuild", "Makefile")
            for path in source.rglob(name)
            if path.is_file()
        },
        key=lambda path: (len(path.relative_to(source).parts), path.as_posix()),
    )
    return candidates[0] if candidates else source


def detect_project(source):
    """Return a conservative project identity from root build metadata."""
    text = ""
    for name in ("Makefile", "Kbuild"):
        path = source / name
        if path.is_file():
            try:
                text += path.read_text(encoding="utf-8", errors="replace")[:200_000]
            except OSError:
                pass
    if "BusyBox" in text or "BUSYBOX_VERSION" in text:
        return "busybox"
    if "KERNELRELEASE" in text or "KERNELVERSION" in text:
        return "linux"
    return "unknown"


def stage_record(started, result, stderr_path):
    return {
        "started_unix_seconds": started,
        "elapsed_seconds": time.time() - started,
        "exit_code": result.returncode,
        "status": "success" if result.returncode == 0 else "failed",
        "stderr": str(stderr_path),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="local tree/archive or HTTP(S) archive URL")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--analyzer", type=Path, default=Path(".lake/build/bin/skbuild"))
    parser.add_argument("--acquirer", type=Path, default=Path("tools/acquire_source.py"))
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--sha256")
    parser.add_argument("--checksum-url")
    parser.add_argument("--tristate", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--no-recursive", action="store_true")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--build-dir", type=Path)
    parser.add_argument("--src-dir", type=Path)
    parser.add_argument("--project", choices=("auto", "linux", "busybox", "unknown"), default="auto")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    workspace = output / "workspace"
    directories = {
        "source": workspace / "source",
        "generated": output / "generated",
        "build": output / "build",
        "temporary": output / "tmp",
        "report": output / "report",
    }
    for name, directory in directories.items():
        if name != "source":
            directory.mkdir(parents=True, exist_ok=True)
    cache = args.cache_dir.resolve() if args.cache_dir else output / ".source-cache"
    acquirer = args.acquirer if args.acquirer.is_absolute() else root / args.acquirer
    analyzer = args.analyzer if args.analyzer.is_absolute() else root / args.analyzer

    acquire_command = [
        sys.executable,
        str(acquirer),
        args.input,
        "--output-dir",
        str(workspace),
        "--cache-dir",
        str(cache),
    ]
    if args.sha256:
        acquire_command += ["--sha256", args.sha256]
    if args.checksum_url:
        acquire_command += ["--checksum-url", args.checksum_url]
    acquire_started = time.time()
    acquired = subprocess.run(acquire_command, cwd=root, text=True, capture_output=True)
    (output / "acquire.stderr").write_text(acquired.stderr, encoding="utf-8")
    if acquired.returncode != 0:
        (output / "manifest.json").write_text(json.dumps({
            "schema": 1,
            "status": "acquisition-failed",
            "directories": {name: str(path.relative_to(output)) for name, path in directories.items()},
            "stages": {"acquire": stage_record(acquire_started, acquired, output / "acquire.stderr")},
        }, indent=2) + "\n", encoding="utf-8")
        return acquired.returncode
    try:
        acquisition_manifest = json.loads((workspace / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"skbuild_analyze: invalid acquisition manifest: {error}", file=sys.stderr)
        return 2

    source = analysis_root(workspace / acquisition_manifest["source_directory"])
    detected_project = detect_project(source)
    selected_project = detected_project if args.project == "auto" else args.project
    analyzer_command = [str(analyzer), "--json"]
    if args.tristate:
        analyzer_command.append("--tristate")
    if args.strict:
        analyzer_command.append("--strict")
    if args.no_recursive:
        analyzer_command.append("--no-recursive")
    for option, value in (("--config", args.config), ("--build-dir", args.build_dir), ("--src-dir", args.src_dir)):
        if value is not None:
            analyzer_command.append(f"{option}={value.resolve()}")
    analyzer_command.append(str(source))
    analyze_started = time.time()
    analyzed = subprocess.run(analyzer_command, cwd=root, text=True, capture_output=True)
    (output / "analyzer.stderr").write_text(analyzed.stderr, encoding="utf-8")
    (output / "command.json").write_text(
        json.dumps({"acquire": acquire_command, "analyze": analyzer_command}, indent=2) + "\n",
        encoding="utf-8",
    )
    report_path = output / "report.json"
    report_path.write_text(analyzed.stdout, encoding="utf-8")
    run_manifest = {
        "schema": 1,
        "acquisition": "workspace/manifest.json",
        "analysis_root": str(source.relative_to(output)),
        "analyzer_exit_code": analyzed.returncode,
        "report": "report.json",
        "project": {
            "requested": args.project,
            "detected": detected_project,
            "selected": selected_project,
        },
        "architecture": platform.machine(),
        "command_policy": {
            "recipes_executed": False,
            "shell_commands_executed": False,
        },
        "directories": {name: str(path.relative_to(output)) for name, path in directories.items()},
        "stages": {
            "acquire": stage_record(acquire_started, acquired, output / "acquire.stderr"),
            "analyze": stage_record(analyze_started, analyzed, output / "analyzer.stderr"),
        },
    }
    try:
        report = json.loads(analyzed.stdout)
        run_manifest["complete"] = report.get("complete")
        run_manifest["coverage"] = report.get("coverage")
    except json.JSONDecodeError:
        run_manifest["complete"] = False
    run_manifest["status"] = (
        "complete" if analyzed.returncode == 0 and run_manifest["complete"] is True
        else "analyzer-failed-or-incomplete"
    )
    (output / "manifest.json").write_text(json.dumps(run_manifest, indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(analyzed.stdout)
    sys.stderr.write(analyzed.stderr)
    return analyzed.returncode


if __name__ == "__main__":
    sys.exit(main())
