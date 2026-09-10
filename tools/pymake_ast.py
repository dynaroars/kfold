#!/usr/bin/env python3
"""Serialize the frozen pymake3 AST into skbuild's versioned JSON schema."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from typing import Any


SCHEMA_VERSION = 1
PYMAKE_REVISION = "034ae9ea5b726e03647d049147c5dbf688e94aaf"


def _location(loc: Any, fallback_file: str) -> dict[str, Any]:
    if loc is None:
        return {
            "file": fallback_file,
            "start": {"offset": 0, "line": 1, "column": 0},
            "stop": {"offset": 0, "line": 1, "column": 0},
        }

    line = int(getattr(loc, "line", 1))
    column = int(getattr(loc, "column", 0))
    file_name = str(getattr(loc, "path", fallback_file) or fallback_file)
    pos = {"offset": 0, "line": line, "column": column}
    return {"file": file_name, "start": pos, "stop": dict(pos)}


def _expr(exp: Any, fallback_file: str) -> dict[str, Any]:
    from pymake3 import data, functions

    if isinstance(exp, data.StringExpansion):
        return {"kind": "literal", "value": exp.s}

    if isinstance(exp, data.Expansion):
        parts: list[dict[str, Any]] = []
        for elem, is_function in exp:
            if not is_function:
                parts.append({"kind": "literal", "value": elem})
            elif isinstance(elem, functions.VariableRef):
                parts.append({"kind": "variable", "name": _expr(elem.vname, fallback_file)})
            else:
                args = [_expr(arg, fallback_file) for arg in elem._arguments]
                parts.append({"kind": "function", "name": elem.name, "args": args})

        if not parts:
            return {"kind": "literal", "value": ""}
        if len(parts) == 1:
            return parts[0]
        return {"kind": "concat", "parts": parts}

    raise TypeError(f"unsupported expansion node: {type(exp).__name__}")


def _parse_value(value: str, fallback_file: str) -> dict[str, Any]:
    from pymake3 import parser, parserdata

    statements = parser.parsestring(value, fallback_file)
    if not statements:
        return {"kind": "literal", "value": ""}
    if len(statements) != 1 or not isinstance(statements[0], parserdata.EmptyDirective):
        raise TypeError(f"assignment value did not parse as an expansion: {value!r}")
    return _expr(statements[0].exp, fallback_file)


def _condition(condition: Any, fallback_file: str) -> dict[str, Any]:
    from pymake3 import parserdata

    if isinstance(condition, parserdata.EqCondition):
        return {
            "kind": "equals",
            "left": _expr(condition.exp1, fallback_file),
            "right": _expr(condition.exp2, fallback_file),
            "expected": condition.expected,
        }
    if isinstance(condition, parserdata.IfdefCondition):
        return {
            "kind": "defined",
            "name": _expr(condition.exp, fallback_file),
            "expected": condition.expected,
        }
    if isinstance(condition, parserdata.ElseCondition):
        return {"kind": "otherwise"}
    raise TypeError(f"unsupported condition node: {type(condition).__name__}")


def _statement(statement: Any, fallback_file: str) -> dict[str, Any]:
    from pymake3 import parserdata

    if isinstance(statement, parserdata.SetVariable):
        return {
            "kind": "assignment",
            "name": _expr(statement.vnameexp, fallback_file),
            "operator": statement.token,
            "value": _parse_value(statement.value, fallback_file),
            "target": (
                _expr(statement.targetexp, fallback_file)
                if statement.targetexp is not None
                else None
            ),
            "span": _location(statement.vnameexp.loc, fallback_file),
        }

    if isinstance(statement, parserdata.ConditionBlock):
        return {
            "kind": "conditional",
            "branches": [
                {
                    "condition": _condition(condition, fallback_file),
                    "statements": [_statement(child, fallback_file) for child in statements],
                    "span": _location(getattr(condition, "loc", None), fallback_file),
                }
                for condition, statements in statement
            ],
            "span": _location(getattr(statement, "loc", None), fallback_file),
        }

    if isinstance(statement, parserdata.Include):
        return {
            "kind": "include",
            "paths": _expr(statement.exp, fallback_file),
            "required": bool(statement.required),
            "span": _location(statement.exp.loc, fallback_file),
        }

    if isinstance(statement, (parserdata.Rule, parserdata.StaticPatternRule)):
        return {
            "kind": "rule",
            "source": statement.to_source(),
            "span": _location(statement.targetexp.loc, fallback_file),
        }

    if isinstance(statement, parserdata.Command):
        return {
            "kind": "command",
            "source": statement.to_source(),
            "span": _location(statement.exp.loc, fallback_file),
        }

    if isinstance(statement, parserdata.EmptyDirective):
        return {
            "kind": "expression",
            "value": _expr(statement.exp, fallback_file),
            "span": _location(statement.exp.loc, fallback_file),
        }

    raise TypeError(f"unsupported statement node: {type(statement).__name__}")


def serialize(path: pathlib.Path) -> dict[str, Any]:
    from pymake3 import parser

    source = str(path)
    statements = parser.parsestring(path.read_text(encoding="utf-8"), path)
    return {
        "schema": SCHEMA_VERSION,
        "generator": {"name": "pymake3", "revision": PYMAKE_REVISION},
        "source": source,
        "statements": [_statement(statement, source) for statement in statements],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("makefile", type=pathlib.Path)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    if not args.makefile.is_file():
        parser.error(f"not a file: {args.makefile}")

    json.dump(
        serialize(args.makefile),
        sys.stdout,
        indent=2 if args.pretty else None,
        sort_keys=True,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
