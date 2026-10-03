"""Deterministic, offline configuration checking for SmartConfig.

This module deliberately keeps the authoritative Kconfig operation in the
kernel's native ``make olddefconfig`` target.  It never edits the source tree:
each normalization uses a private ``O=`` directory and a controlled argv.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "smartconfig.run.v1"
_SET = re.compile(r"^(CONFIG_[A-Za-z0-9_]+)=(.*)$")
_UNSET = re.compile(r"^#\s+(CONFIG_[A-Za-z0-9_]+) is not set\s*$")


@dataclass(frozen=True)
class Assignment:
    symbol: str
    value: str
    line: int


@dataclass
class ParsedConfig:
    assignments: list[Assignment] = field(default_factory=list)
    unknown_lines: list[tuple[int, str]] = field(default_factory=list)

    @property
    def values(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for assignment in self.assignments:
            out[assignment.symbol] = assignment.value
        return out

    @property
    def duplicates(self) -> dict[str, list[Assignment]]:
        seen: dict[str, list[Assignment]] = {}
        for assignment in self.assignments:
            seen.setdefault(assignment.symbol, []).append(assignment)
        return {k: v for k, v in seen.items() if len(v) > 1}


def parse_config(text: str) -> ParsedConfig:
    parsed = ParsedConfig()
    for line_no, line in enumerate(text.splitlines(), 1):
        match = _SET.match(line.strip())
        if match:
            parsed.assignments.append(Assignment(match[1], match[2].strip(), line_no))
            continue
        match = _UNSET.match(line.strip())
        if match:
            parsed.assignments.append(Assignment(match[1], "n", line_no))
            continue
        if line.strip() and not line.lstrip().startswith("#"):
            parsed.unknown_lines.append((line_no, line))
    return parsed


def _load_data(path: Path) -> Any:
    text = path.read_text()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise ValueError(
                f"{path} is YAML; install PyYAML or provide JSON"
            ) from exc
        return yaml.safe_load(text)


def _condition(value: Any, actual: dict[str, str], *, arch: str = "x86_64") -> tuple[bool, str]:
    """Evaluate the intentionally small, data-only requirement language."""
    if not isinstance(value, dict):
        raise ValueError("requirement must be an object")
    if "all" in value:
        results = [_condition(x, actual, arch=arch) for x in value["all"]]
        return all(x[0] for x in results), "all(" + "; ".join(x[1] for x in results) + ")"
    if "any" in value:
        results = [_condition(x, actual, arch=arch) for x in value["any"]]
        return any(x[0] for x in results), "any(" + "; ".join(x[1] for x in results) + ")"
    if "not" in value:
        ok, detail = _condition(value["not"], actual, arch=arch)
        return not ok, f"not({detail})"
    symbol = value.get("symbol") or value.get("config")
    if symbol and not str(symbol).startswith("CONFIG_"):
        symbol = "CONFIG_" + str(symbol)
    if not symbol:
        raise ValueError("leaf requirement needs symbol/config")
    observed = actual.get(symbol, "n")
    if "equals" in value or "value" in value:
        expected = str(value.get("equals", value.get("value")))
        return observed == expected, f"{symbol}={observed!r}, expected {expected!r}"
    allowed = value.get("allowed") or value.get("values")
    if allowed is not None:
        expected = [str(x) for x in allowed]
        return observed in expected, f"{symbol}={observed!r}, allowed {expected!r}"
    if "min" in value or "max" in value:
        try:
            number = int(observed, 0)
            lo = int(value["min"], 0) if "min" in value else number
            hi = int(value["max"], 0) if "max" in value else number
            return lo <= number <= hi, f"{symbol}={number}, expected {lo}..{hi}"
        except ValueError:
            return False, f"{symbol}={observed!r} is not numeric"
    raise ValueError(f"unsupported requirement leaf for {symbol}")


def _applies(item: dict[str, Any], arch: str) -> bool:
    target = item.get("target")
    if not target:
        return True
    if not isinstance(target, dict):
        raise ValueError("target predicate must be an object")
    allowed = target.get("arch") or target.get("architectures")
    if allowed is None:
        raise ValueError("target predicate needs arch/architectures")
    return arch in ([allowed] if isinstance(allowed, str) else [str(x) for x in allowed])


def _validate_recipe_data(data: Any) -> None:
    forbidden = {"python", "shell", "lua", "command", "exec"}
    def walk(value: Any) -> None:
        if isinstance(value, dict):
            bad = forbidden.intersection(value)
            if bad:
                raise ValueError(f"embedded execution fields are forbidden: {sorted(bad)}")
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(data)


def _atomic_write(path: Path, data: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(data)
    os.replace(tmp, path)


def _normalize(source: Path, requested: Path, out: Path, arch: str) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(requested, out / ".config")
    started = time.monotonic()
    proc = subprocess.run(
        ["make", "-C", str(source), f"O={out}", f"ARCH={arch}", "olddefconfig"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=300,
        check=False,
        env={**os.environ, "LC_ALL": "C", "LANG": "C"},
    )
    output = proc.stdout
    _atomic_write(out / "native.log", output)
    effective_path = out / ".config"
    effective = effective_path.read_text() if effective_path.exists() else ""
    return {
        "ok": proc.returncode == 0 and bool(effective),
        "exit_code": proc.returncode,
        "duration_s": round(time.monotonic() - started, 6),
        "effective": effective,
        "effective_hash": hashlib.sha256(effective.encode()).hexdigest(),
        "native_output": output,
        "log": "native.log",
    }


def _source_identity(source: Path) -> dict[str, str]:
    """Return a stable identity without trusting a release string."""
    try:
        commit = subprocess.run(
            ["git", "-C", str(source), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = ""
    digest = hashlib.sha256()
    for name in ("Makefile", "Kconfig"):
        path = source / name
        if path.exists():
            digest.update(name.encode() + b"\0" + path.read_bytes())
    return {"commit": commit, "content_digest": digest.hexdigest()}


def _with_removals(text: str, removals: list[str]) -> str:
    """Apply only explicit CONFIG removals while preserving input layout."""
    wanted = {s if s.startswith("CONFIG_") else "CONFIG_" + s for s in removals}
    lines = text.splitlines(keepends=True)
    seen: set[str] = set()
    result: list[str] = []
    for line in lines:
        match = _SET.match(line.strip()) or _UNSET.match(line.strip())
        symbol = match[1] if match else None
        if symbol in wanted:
            if symbol in seen:
                continue
            newline = "\n" if line.endswith("\n") else ""
            result.append(f"# {symbol} is not set{newline}")
            seen.add(symbol)
        else:
            result.append(line)
    for symbol in sorted(wanted - seen):
        result.append(f"# {symbol} is not set\n")
    return "".join(result)


def check(*, source: Path, baseline: Path, candidate: Path, requirements: Path, out: Path, arch: str, snapshot: Path | None = None) -> dict[str, Any]:
    source = source.resolve()
    out = out.resolve()
    source_identity_before = _source_identity(source)
    req_data = _load_data(requirements) or {}
    _validate_recipe_data(req_data)
    reqs = req_data.get("requirements", req_data) if isinstance(req_data, dict) else req_data
    base_parsed = parse_config(baseline.read_text())
    cand_parsed = parse_config(candidate.read_text())
    base = _normalize(source, baseline, out / "baseline", arch)
    cand = _normalize(source, candidate, out / "candidate", arch)
    base_values = parse_config(base["effective"]).values
    cand_values = parse_config(cand["effective"]).values
    findings: list[dict[str, Any]] = []
    idempotent = None
    if cand["ok"]:
        second = _normalize(source, out / "candidate" / ".config", out / "idempotence", arch)
        idempotent = second["ok"] and second["effective_hash"] == cand["effective_hash"]
        if not idempotent:
            findings.append({"id": "non-idempotent-normalization", "severity": "warning", "message": "normalizing the effective candidate changed it again"})
    if base_parsed.duplicates or cand_parsed.duplicates:
        findings.append({"id": "duplicate-assignment", "severity": "warning", "message": "conflicting duplicate assignments were retained for review"})
    if base_parsed.unknown_lines or cand_parsed.unknown_lines:
        findings.append({"id": "unparsed-input", "severity": "warning", "message": "non-comment, non-assignment input lines were ignored"})
    native_warnings = [line for line in cand.get("native_output", "").splitlines()
                       if "warning" in line.lower()]
    if not base["ok"] or not cand["ok"]:
        status = "execution_error"
    else:
        status = "pass"
        for item in reqs if isinstance(reqs, list) else []:
            if not isinstance(item, dict):
                raise ValueError("each requirement must be an object")
            if not _applies(item, arch):
                findings.append({"id": str(item.get("id", "unknown")), "severity": "skip", "message": f"not applicable to arch {arch}"})
                continue
            rid = str(item.get("id", f"requirement-{len(findings)+1}"))
            ok, detail = _condition(item.get("condition", item), cand_values, arch=arch)
            if not ok:
                status = "violation"
                findings.append({"id": rid, "requirement_id": rid, "severity": "error", "message": detail, "next_step": "adjust the candidate or requirement"})
    baseline_violations = []
    for item in reqs if isinstance(reqs, list) else []:
        if not _applies(item, arch):
            continue
        ok, detail = _condition(item.get("condition", item), base_values, arch=arch)
        if not ok:
            baseline_violations.append({"requirement_id": item.get("id"), "message": detail})
    requested = cand_parsed.values
    ineffective = [{"symbol": s, "requested": v, "effective": cand_values.get(s, "n")} for s, v in requested.items() if cand_values.get(s, "n") != v]
    if native_warnings:
        findings.append({"id": "native-warning", "severity": "warning", "message": "native normalization emitted warnings; result is provisional"})
        if status == "pass":
            status = "incomplete"
    source_identity_after = _source_identity(source)
    if source_identity_after != source_identity_before:
        status = "execution_error"
        findings.append({"id": "source-changed-during-run", "severity": "error", "message": "target source identity changed during normalization"})
    base_record = {key: value for key, value in base.items() if key not in {"effective", "native_output"}}
    candidate_record = {key: value for key, value in cand.items() if key not in {"effective", "native_output"}}
    report = {"schema": SCHEMA_VERSION, "backend": "native-olddefconfig", "status": status, "source": str(source), "source_identity": source_identity_after, "arch": arch, "idempotent": idempotent, "baseline": {**base_record, "effective_config": "baseline/.config", "violations": baseline_violations}, "candidate": {**candidate_record, "effective_config": "candidate/.config", "violations": [x for x in findings if x.get("severity") == "error"]}, "requested_changes": ineffective, "findings": findings}
    if snapshot:
        from autokernel.snapshot import load
        snap = load(snapshot)
        report["snapshot"] = {
            "schema_version": snap.schema_version, "host": snap.host,
            "collected_at": snap.collected_at.isoformat(), "kernel": snap.kernel.model_dump(),
            "evidence_counts": {"pci": len(snap.pci), "usb": len(snap.usb),
                                "modaliases": len(snap.modaliases), "loaded_modules": len(snap.loaded_modules),
                                "firmware": len(snap.firmware)},
            "limitations": ["snapshot evidence is from the running kernel and is not a target mapping"],
        }
    _atomic_write(out / "report.json", json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def plan(*, source: Path, baseline: Path, requirements: Path, out: Path, removals: list[str], arch: str, history: Path | None = None) -> dict[str, Any]:
    """Create and check a conservative removal plan."""
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    candidate = out / "requested.config"
    _atomic_write(candidate, _with_removals(baseline.read_text(), removals))
    report = check(source=source, baseline=baseline, candidate=candidate,
                   requirements=requirements, out=out / "check", arch=arch)
    plan_report = {
        "schema": "smartconfig.plan.v1", "policy": "explicit-removals-only",
        "requested_removals": [s if s.startswith("CONFIG_") else "CONFIG_" + s for s in removals],
        "status": "checked" if report["status"] == "pass" else "blocked",
        "check_report": "check/report.json", "candidate": "requested.config",
    }
    if history:
        history_data = json.loads(history.read_text())
        plan_report["history"] = {
            "source": history_data.get("source"),
            "source_hash": history_data.get("source_hash"),
            "observed_count": len(history_data.get("observed_modules", [])),
            "absence_means": history_data.get("coverage", {}).get("absence_means", "unknown"),
        }
    effective = out / "check" / "candidate" / ".config"
    if report["status"] == "pass" and effective.exists():
        shutil.copyfile(effective, out / "effective.config")
        plan_report["effective"] = "effective.config"
    _atomic_write(out / "plan.json", json.dumps(plan_report, indent=2, sort_keys=True) + "\n")
    return plan_report


def diagnose(*, source: Path, good: Path, bad: Path, requirements: Path,
             out: Path, test_command: str | None, arch: str) -> dict[str, Any]:
    """Run bounded one-symbol-at-a-time diagnosis over a normalized delta."""
    out.mkdir(parents=True, exist_ok=True)
    good_values = parse_config(good.read_text()).values
    bad_values = parse_config(bad.read_text()).values
    changed = sorted(s for s in set(good_values) | set(bad_values)
                     if good_values.get(s, "n") != bad_values.get(s, "n"))
    trials: list[dict[str, Any]] = []
    argv = shlex.split(test_command) if test_command else None
    for symbol in changed:
        trial = out / "trials" / symbol.removeprefix("CONFIG_")
        trial_config = trial / "trial.config"
        trial_config.parent.mkdir(parents=True, exist_ok=True)
        values = dict(bad_values)
        values[symbol] = good_values.get(symbol, "n")
        lines = [f"{s}={v}\n" if v != "n" else f"# {s} is not set\n"
                 for s, v in sorted(values.items())]
        _atomic_write(trial_config, "".join(lines))
        normalized = _normalize(source, trial_config, trial, arch)
        test_status = "unknown"
        test_output = ""
        if normalized["ok"] and argv:
            try:
                result = subprocess.run(argv, capture_output=True, text=True,
                                        timeout=300, check=False, cwd=source)
                test_status = "pass" if result.returncode == 0 else "fail"
                test_output = (result.stdout + result.stderr)[-4000:]
            except subprocess.TimeoutExpired:
                test_status = "inconclusive"
                test_output = "test timeout after 300 seconds"
        trials.append({"symbol": symbol, "restored_value": values[symbol],
                       "normalization": normalized["ok"], "test": test_status,
                       "output": test_output})
    failing = [t["symbol"] for t in trials if t["test"] == "pass"]
    report = {"schema": "smartconfig.diagnosis.v1", "status": "complete" if argv else "unknown",
              "claim": "failure-inducing set relative to tested trials; not globally minimal",
              "changed_symbols": changed, "trials": trials,
              "likely_causes": failing, "requirements": str(requirements),
              "test_command": argv}
    _atomic_write(out / "diagnosis.json", json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def upgrade(*, old_source: Path, new_source: Path, config: Path,
            requirements: Path, out: Path, arch: str) -> dict[str, Any]:
    """Compare effective configuration across two exact target trees."""
    out.mkdir(parents=True, exist_ok=True)
    old = _normalize(old_source, config, out / "old", arch)
    new = _normalize(new_source, config, out / "new", arch)
    old_values = parse_config(old["effective"]).values
    new_values = parse_config(new["effective"]).values
    removed = sorted(set(old_values) - set(new_values))
    changed = sorted(s for s in set(old_values) & set(new_values)
                     if old_values[s] != new_values[s])
    check_report = check(source=new_source, baseline=config, candidate=config,
                         requirements=requirements, out=out / "check", arch=arch)
    report = {"schema": "smartconfig.upgrade.v1", "status": check_report["status"],
              "old_source": str(old_source.resolve()), "new_source": str(new_source.resolve()),
              "removed_symbols": removed,
              "changed_effective_values": [{"symbol": s, "old": old_values[s], "new": new_values[s]} for s in changed],
              "requirement_report": "check/report.json",
              "limitations": ["symbol changes are not semantic rename proof", "runtime regressions require validation"]}
    _atomic_write(out / "upgrade.json", json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def _catalog_json() -> str:
    from autokernel.capabilities import RECIPES, recipe_requirements
    return json.dumps({"schema": "smartconfig.capabilities.v1", "recipes": [
        *recipe_requirements(list(RECIPES))
    ]}, indent=2, sort_keys=True) + "\n"


def _main() -> int:
    parser = argparse.ArgumentParser(prog="smartconfig")
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("doctor", help="check checker prerequisites without changing files")
    d.add_argument("--source", type=Path)
    d.add_argument("--arch", default="x86_64")
    sub.add_parser("catalog", help="print the bounded built-in capability catalog")
    req = sub.add_parser("require", help="write a versioned requirements file from capabilities")
    req.add_argument("capabilities", nargs="+", choices=sorted(__import__("autokernel.capabilities", fromlist=["RECIPES"]).RECIPES))
    req.add_argument("--out", type=Path, required=True)
    pl = sub.add_parser("plan", help="plan explicit conservative CONFIG removals")
    pl.add_argument("--source", type=Path, required=True)
    pl.add_argument("--baseline", type=Path, required=True)
    pl.add_argument("--requirements", type=Path, required=True)
    pl.add_argument("--out", type=Path, required=True)
    pl.add_argument("--remove", action="append", default=[], metavar="CONFIG_SYMBOL")
    pl.add_argument("--history", type=Path, help="optional imported history metadata")
    pl.add_argument("--arch", default="x86_64")
    ex = sub.add_parser("export", help="export a checked effective configuration")
    ex.add_argument("--run", type=Path, required=True)
    ex.add_argument("--out", type=Path, required=True)
    va = sub.add_parser("validate", help="recheck one final effective configuration")
    va.add_argument("--source", type=Path, required=True)
    va.add_argument("--config", type=Path, required=True)
    va.add_argument("--requirements", type=Path, required=True)
    va.add_argument("--out", type=Path, required=True)
    va.add_argument("--arch", default="x86_64")
    hi = sub.add_parser("history", help="import an observed module history")
    hi.add_argument("--input", type=Path, required=True)
    hi.add_argument("--out", type=Path, required=True)
    di = sub.add_parser("diagnose", help="bounded diagnosis of a known-good/bad config delta")
    di.add_argument("--source", type=Path, required=True)
    di.add_argument("--good", type=Path, required=True)
    di.add_argument("--bad", type=Path, required=True)
    di.add_argument("--requirements", type=Path, required=True)
    di.add_argument("--out", type=Path, required=True)
    di.add_argument("--test", dest="test_command", help="optional shell-free command string")
    di.add_argument("--arch", default="x86_64")
    up = sub.add_parser("upgrade", help="compare effective configs across target trees")
    up.add_argument("--old-source", type=Path, required=True)
    up.add_argument("--new-source", type=Path, required=True)
    up.add_argument("--config", type=Path, required=True)
    up.add_argument("--requirements", type=Path, required=True)
    up.add_argument("--out", type=Path, required=True)
    up.add_argument("--arch", default="x86_64")
    ai = sub.add_parser("artifacts", help="inventory built artifacts and identity")
    ai.add_argument("--source", type=Path, required=True)
    ai.add_argument("--config", type=Path)
    ai.add_argument("--out", type=Path, required=True)
    vm = sub.add_parser("vm-test", help="record a safe VM validation preflight")
    vm.add_argument("--kernel", type=Path, required=True)
    vm.add_argument("--out", type=Path, required=True)
    mp = sub.add_parser("map", help="build target-scoped capability mappings")
    mp.add_argument("--source", type=Path, required=True)
    mp.add_argument("--out", type=Path, required=True)
    mp.add_argument("--capability", action="append", dest="capabilities")
    p = sub.add_parser("check")
    for name, required in (("source", True), ("baseline", True), ("candidate", True), ("requirements", True), ("out", True)):
        p.add_argument("--" + name, type=Path, required=required)
    p.add_argument("--arch", default="x86_64")
    p.add_argument("--snapshot", type=Path, help="optional AutoKernel snapshot directory for traceable host context")
    e = sub.add_parser("explain")
    e.add_argument("--run", type=Path, required=True)
    e.add_argument("symbol")
    args = parser.parse_args()
    if args.command == "catalog":
        print(_catalog_json(), end="")
        return 0
    if args.command == "require":
        from autokernel.capabilities import recipe_requirements
        payload = {"schema": "smartconfig.requirements.v1", "requirements": recipe_requirements(args.capabilities)}
        _atomic_write(args.out, json.dumps(payload, indent=2, sort_keys=True) + "\n")
        print(f"requirements: {args.out}")
        return 0
    if args.command == "plan":
        result = plan(source=args.source, baseline=args.baseline, requirements=args.requirements,
                      out=args.out, removals=args.remove, arch=args.arch, history=args.history)
        print(f"status: {result['status']}\nplan: {args.out / 'plan.json'}")
        return 0 if result["status"] == "checked" else 1
    if args.command == "export":
        report_path = args.run / "report.json"
        effective = args.run / "candidate" / ".config"
        if not report_path.exists() and (args.run / "check" / "report.json").exists():
            report_path = args.run / "check" / "report.json"
            effective = args.run / "check" / "candidate" / ".config"
        report = json.loads(report_path.read_text())
        if report.get("status") != "pass":
            print("refusing export: run is not a passing checked report", file=sys.stderr)
            return 1
        if not effective.exists():
            print("refusing export: candidate effective config is missing", file=sys.stderr)
            return 2
        shutil.copyfile(effective, args.out)
        print(f"export: {args.out}")
        return 0
    if args.command == "validate":
        report = check(source=args.source, baseline=args.config, candidate=args.config,
                       requirements=args.requirements, out=args.out, arch=args.arch)
        print(f"status: {report['status']}\nreport: {args.out / 'report.json'}")
        return {"pass": 0, "violation": 1, "execution_error": 3}.get(report["status"], 2)
    if args.command == "history":
        from autokernel.history import write_import
        write_import(args.input, args.out)
        print(f"history: {args.out}")
        return 0
    if args.command == "diagnose":
        result = diagnose(source=args.source, good=args.good, bad=args.bad,
                          requirements=args.requirements, out=args.out,
                          test_command=args.test_command, arch=args.arch)
        print(f"status: {result['status']}\ndiagnosis: {args.out / 'diagnosis.json'}")
        return 0
    if args.command == "upgrade":
        result = upgrade(old_source=args.old_source, new_source=args.new_source,
                         config=args.config, requirements=args.requirements,
                         out=args.out, arch=args.arch)
        print(f"status: {result['status']}\nreport: {args.out / 'upgrade.json'}")
        return 0 if result["status"] == "pass" else 1
    if args.command == "artifacts":
        from autokernel.artifacts import write_inventory
        data = write_inventory(args.source, args.out, args.config)
        print(f"artifacts: {args.out}\nartifacts_found: {len(data['artifacts'])}")
        return 0
    if args.command == "vm-test":
        from autokernel.artifacts import vm_validation
        data = vm_validation(args.kernel, args.out)
        print(f"status: {data['status']}\nvalidation: {args.out}")
        return 0 if data["status"] == "pass" else 2
    if args.command == "map":
        from autokernel.mapping import write_mapping
        data = write_mapping(args.source, args.out, args.capabilities)
        print(f"mapping: {args.out}\nrecords: {len(data['records'])}")
        return 0
    if args.command == "doctor":
        checks: dict[str, Any] = {"python": sys.version.split()[0], "make": shutil.which("make") or None}
        if args.source:
            checks["source"] = str(args.source.resolve())
            checks["kconfig"] = (args.source / "Kconfig").exists()
            checks["makefile"] = (args.source / "Makefile").exists()
        print(json.dumps({"schema": "smartconfig.doctor.v1", "arch": args.arch, "checks": checks}, indent=2, sort_keys=True))
        return 0 if checks["make"] and (not args.source or checks["kconfig"] and checks["makefile"]) else 2
    if args.command == "explain":
        report = json.loads((args.run / "report.json").read_text())
        hits = [x for x in report.get("findings", []) if args.symbol in json.dumps(x)]
        print(json.dumps(hits, indent=2, sort_keys=True))
        return 1 if hits else 0
    report = check(source=args.source, baseline=args.baseline, candidate=args.candidate, requirements=args.requirements, out=args.out, arch=args.arch, snapshot=args.snapshot)
    print(f"status: {report['status']}")
    print(f"report: {args.out / 'report.json'}")
    return {"pass": 0, "violation": 1, "execution_error": 3}.get(report["status"], 2)


if __name__ == "__main__":
    sys.exit(_main())
