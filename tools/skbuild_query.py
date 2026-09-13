#!/usr/bin/env python3
"""Query persisted skbuild report records by file path or controlling option."""

import argparse
import json
import sys
from pathlib import Path


def formula_mentions(formula, option):
    if not isinstance(formula, dict):
        return False
    if formula.get("kind") == "equals":
        return formula.get("symbol") == option
    return any(formula_mentions(formula.get(key), option) for key in ("body", "left", "right"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file")
    group.add_argument("--option")
    args = parser.parse_args()
    report_path = args.run_dir.resolve() / "report.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"skbuild_query: cannot read report: {error}", file=sys.stderr)
        return 2
    files = report.get("files")
    if not isinstance(files, list):
        print("skbuild_query: report has no files array", file=sys.stderr)
        return 2
    if args.file is not None:
        result = [item for item in files if item.get("path") == args.file]
    else:
        result = [item for item in files if formula_mentions(item.get("condition"), args.option)]
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
