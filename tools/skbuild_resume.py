#!/usr/bin/env python3
"""Resume a prepared skbuild analysis workspace without reacquiring sources."""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def write_json(path, value):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


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
    if analyzed.stdout.strip():
        (run_dir / "report.json.tmp").write_text(analyzed.stdout, encoding="utf-8")
        (run_dir / "report.json.tmp").replace(run_dir / "report.json")
    resume = {
        "started_unix_seconds": started,
        "elapsed_seconds": time.time() - started,
        "exit_code": analyzed.returncode,
        "status": "success" if analyzed.returncode == 0 else "analyzer-failed-or-incomplete",
    }
    manifest["last_resume"] = resume
    write_json(run_dir / "manifest.json", manifest)
    sys.stdout.write(analyzed.stdout)
    sys.stderr.write(analyzed.stderr)
    return analyzed.returncode


if __name__ == "__main__":
    sys.exit(main())
