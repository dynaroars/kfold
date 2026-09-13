#!/usr/bin/env python3
"""Resume a prepared skbuild analysis workspace without reacquiring sources."""

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path


def write_json(path, value):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    try:
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        commands = json.loads((run_dir / "command.json").read_text(encoding="utf-8"))
        acquisition = json.loads(
            (run_dir / manifest["acquisition"]).read_text(encoding="utf-8")
        )
        source = (run_dir / manifest["analysis_root"]).resolve()
        command = commands["analyze"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(f"skbuild_resume: invalid run workspace: {error}", file=sys.stderr)
        return 2
    if manifest.get("schema") != 1 or acquisition.get("schema") != 1:
        print("skbuild_resume: unsupported workspace schema", file=sys.stderr)
        return 2
    if not source.is_dir() or not isinstance(command, list) or not command:
        print("skbuild_resume: workspace has no usable source or analyzer command", file=sys.stderr)
        return 2

    started = time.time()
    analyzed = subprocess.run(command, cwd=Path(__file__).resolve().parent.parent,
                              text=True, capture_output=True)
    (run_dir / "resume.stderr").write_text(analyzed.stderr, encoding="utf-8")
    report = None
    if analyzed.stdout.strip():
        try:
            report = json.loads(analyzed.stdout)
        except json.JSONDecodeError:
            report = None
        if report is not None:
            (run_dir / "report.json.tmp").write_text(analyzed.stdout, encoding="utf-8")
            (run_dir / "report.json.tmp").replace(run_dir / "report.json")
    complete = report is not None and report.get("complete") is True
    resume = {
        "started_unix_seconds": started,
        "elapsed_seconds": time.time() - started,
        "exit_code": analyzed.returncode,
        "status": "complete" if analyzed.returncode == 0 and complete
            else "analyzer-failed-or-incomplete",
        "report_sha256": sha256_bytes(analyzed.stdout.encode("utf-8"))
            if report is not None else None,
        "stderr_sha256": sha256_bytes(analyzed.stderr.encode("utf-8")),
    }
    manifest["last_resume"] = resume
    manifest["analyzer_exit_code"] = analyzed.returncode
    manifest["complete"] = complete
    if report is not None:
        manifest["coverage"] = report.get("coverage")
    manifest["status"] = resume["status"]
    write_json(run_dir / "manifest.json", manifest)
    sys.stdout.write(analyzed.stdout)
    sys.stderr.write(analyzed.stderr)
    return analyzed.returncode


if __name__ == "__main__":
    sys.exit(main())
