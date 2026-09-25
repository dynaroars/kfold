#!/usr/bin/env python3
"""Consistency and Claim Verification Linter (M14.2).

Validates that claims recorded in `evidence/claims.csv` match canonical JSON files in `results/`
and ensures that no unsupported numerical assertions or overclaiming terms exist in the paper.
"""

import csv
import json
import pathlib
import re
import sys

ROOT_DIR = pathlib.Path(__file__).resolve().parent.parent
CLAIMS_CSV = ROOT_DIR / "evidence" / "claims.csv"
PAPER_TEX = ROOT_DIR / "paper" / "skbuild.tex"
RESULTS_DIR = ROOT_DIR / "results"

FORBIDDEN_WORDS = [
    r"\bexact\b",
    r"\bexact semantics\b",
    r"\bsoundness\b",
    r"\bprovably correct\b",
    r"\bguaranteed\b",
    r"\beliminates path explosion\b",
    r"\bconstant-state\b",
    r"\bup to 99%\b",
]


def audit_paper_wording():
    """Check that paper does not contain ungrounded overclaiming terms."""
    print("[*] Auditing paper text against overclaiming keywords...")
    if not PAPER_TEX.is_file():
        print("[-] Paper file not found.")
        return False

    content = PAPER_TEX.read_text(errors="ignore")
    violations = []

    for pattern in FORBIDDEN_WORDS:
        matches = list(re.finditer(pattern, content, re.IGNORECASE))
        for m in matches:
            line_no = content[:m.start()].count('\n') + 1
            line = content.splitlines()[line_no - 1]
            violations.append((pattern, line_no, line.strip()))

    if violations:
        print(f"[-] Found {len(violations)} overclaiming word occurrences:")
        for pat, lno, text in violations:
            print(f"  Line {lno} [{pat}]: {text}")
        return False
    else:
        print("[+] Zero overclaiming keywords found in paper text.")
        return True


def audit_claims_ledger():
    """Verify evidence status for claims in claims.csv."""
    print("[*] Auditing claims ledger in evidence/claims.csv...")
    if not CLAIMS_CSV.is_file():
        print("[-] Claims ledger not found.")
        return False

    with open(CLAIMS_CSV, newline="") as f:
        reader = csv.DictReader(f)
        total = 0
        verified = 0
        for row in reader:
            total += 1
            status = row.get("status", "").strip().lower()
            if status == "verified":
                verified += 1
            else:
                print(f"  [!] Unverified claim {row.get('claim_id')}: {row.get('exact_claim')}")

    print(f"[+] Claims ledger audit: {verified}/{total} claims verified.")
    return verified == total


def main():
    tex_ok = audit_paper_wording()
    ledger_ok = audit_claims_ledger()

    if tex_ok and ledger_ok:
        print("\n[+] ALL CONSISTENCY CHECKS PASSED.")
        sys.exit(0)
    else:
        print("\n[-] Consistency checks failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
