#!/usr/bin/env python3
"""Download, verify, and extract the pinned source releases.

Usage: experiments/fetch.py [SUBJECT ...]

Each release is extracted once into work/src/<topdir> and made read-only.
The analyzed tree work/prepared/<topdir> is a copy of it, after the
subject's build-file generator if any, with experiments/settings/<subject>.ini
installed as skbuild.ini (reinstalled on every run, so edits to the tracked
settings take effect). It is read-only too, so no experiment can modify it. Digests are written to
results/manifest.json under "sources".
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from subjects import DOWNLOADS, RESULTS, SRC, SUBJECTS, analysis_dir, settings_file, source_dir  # noqa: E402


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def download(url, expected):
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    dest = DOWNLOADS / url.rsplit("/", 1)[1]
    if not dest.exists():
        tmp = dest.with_suffix(dest.suffix + ".part")
        print(f"downloading {url}", flush=True)
        with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
        tmp.rename(dest)
    digest = sha256(dest)
    if expected and digest != expected:
        sys.exit(f"checksum mismatch for {dest}: {digest} != {expected}")
    return dest, digest


def extract(archive, into):
    into.mkdir(parents=True, exist_ok=True)
    subprocess.run(["tar", "-xf", str(archive), "-C", str(into)], check=True)


def update_manifest(key, value):
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / "manifest.json"
    manifest = json.loads(path.read_text()) if path.exists() else {}
    manifest.setdefault("sources", {})[key] = value
    path.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")


def install_settings(subject):
    """(Re)install the tracked settings as the analyzed tree's skbuild.ini."""
    dest = analysis_dir(subject) / "skbuild.ini"
    os.chmod(dest.parent, 0o755)
    if dest.exists():
        os.chmod(dest, 0o644)
    shutil.copyfile(settings_file(subject), dest)
    os.chmod(dest, 0o444)
    os.chmod(dest.parent, 0o555)


def fetch(subject):
    spec = SUBJECTS[subject]
    tree = source_dir(subject)
    archive, digest = download(spec["url"], spec["sha256"])
    extras = [download(u, s) for u, s in spec.get("extra", [])]
    if not tree.exists():
        extract(archive, SRC)
        for extra, _ in extras:  # e.g. coreboot blobs unpack into the same topdir
            extract(extra, SRC)
        subprocess.run(["chmod", "-R", "a-w", str(tree)], check=True)
    prepared = analysis_dir(subject)
    if not prepared.exists():
        prepared.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["cp", "-a", "--reflink=auto", str(tree), str(prepared)], check=True)
        subprocess.run(["chmod", "-R", "u+w", str(prepared)], check=True)
        if spec.get("prepare"):
            subprocess.run(spec["prepare"], shell=True, cwd=prepared, check=True)
        subprocess.run(["chmod", "-R", "a-w", str(prepared)], check=True)
    install_settings(subject)
    update_manifest(subject, {
        "version": spec["version"], "url": spec["url"], "sha256": digest,
        "sha256_verified_against_upstream": bool(spec["sha256"]),
        "extra": [{"file": e.name, "sha256": d} for e, d in extras],
        "tree": str(tree.relative_to(SRC.parent.parent)),
        "prepare": spec.get("prepare"),
        "analyzed_tree": str(prepared.relative_to(SRC.parent.parent)),
    })
    print(f"{subject}: {tree} ({digest[:12]})", flush=True)


if __name__ == "__main__":
    for s in sys.argv[1:] or SUBJECTS:
        fetch(s)
