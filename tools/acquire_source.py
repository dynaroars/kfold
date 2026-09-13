#!/usr/bin/env python3
"""Acquire a source tree or archive into an atomic, manifest-backed workspace."""

import argparse
import hashlib
import json
import os
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath


DEFAULT_MAX_FILES = 500_000
DEFAULT_MAX_EXPANDED_BYTES = 20 * 1024 * 1024 * 1024
DEFAULT_MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024


class AcquireError(Exception):
    """An input or extraction safety error suitable for a CLI user."""


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def tree_digest(root):
    digest = hashlib.sha256()
    count = 0
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        if path.is_symlink():
            digest.update(b"symlink\0")
            digest.update(os.readlink(path).encode("utf-8"))
        elif path.is_file():
            count += 1
            with path.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
        elif path.is_dir():
            digest.update(b"directory")
        else:
            raise AcquireError(f"unsupported special file in source tree: {path}")
        digest.update(b"\0")
    return digest.hexdigest(), count


def safe_member(name):
    """Return a normalized relative archive name or reject traversal."""
    if "\x00" in name:
        raise AcquireError("archive member contains NUL")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        raise AcquireError(f"archive member escapes extraction root: {name}")
    normalized = PurePosixPath(*[part for part in path.parts if part not in ("", ".")])
    if not normalized.parts:
        raise AcquireError(f"archive member has no usable path: {name}")
    return Path(*normalized.parts)


def safe_link_target(member_path, target):
    target_path = PurePosixPath(target)
    if target_path.is_absolute() or "\x00" in target:
        raise AcquireError(f"archive link has unsafe target: {target}")
    combined = PurePosixPath(member_path.parent.as_posix(), target)
    if any(part == ".." for part in combined.parts):
        normalized = []
        for part in combined.parts:
            if part in ("", "."):
                continue
            if part == "..":
                if not normalized:
                    raise AcquireError(f"archive link escapes extraction root: {target}")
                normalized.pop()
            else:
                normalized.append(part)
        return Path(*normalized)
    return Path(*[part for part in combined.parts if part not in ("", ".")])


def ensure_parent(path):
    path.parent.mkdir(parents=True, exist_ok=True)


def extract_tar(archive, destination, limits):
    files = 0
    expanded = 0
    with tarfile.open(archive, "r:*") as stream:
        members = stream.getmembers()
        for member in members:
            relative = safe_member(member.name)
            if member.isdir():
                (destination / relative).mkdir(parents=True, exist_ok=True)
                continue
            files += 1
            if files > limits["max_files"]:
                raise AcquireError("archive exceeds maximum member count")
            target = destination / relative
            if member.isfile():
                expanded += member.size
                if expanded > limits["max_expanded_bytes"]:
                    raise AcquireError("archive exceeds maximum expanded size")
                ensure_parent(target)
                source = stream.extractfile(member)
                if source is None:
                    raise AcquireError(f"cannot read archive member: {member.name}")
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, 1024 * 1024)
                os.chmod(target, member.mode & 0o777)
            elif member.issym():
                ensure_parent(target)
                link_target = safe_link_target(relative, member.linkname)
                target.symlink_to(link_target)
            elif member.islnk():
                ensure_parent(target)
                link_target = safe_link_target(relative, member.linkname)
                if not (destination / link_target).exists():
                    raise AcquireError(f"archive hardlink target is missing: {member.linkname}")
                os.link(destination / link_target, target)
            else:
                raise AcquireError(f"archive contains unsupported special member: {member.name}")
    return files, expanded


def extract_zip(archive, destination, limits):
    files = 0
    expanded = 0
    with zipfile.ZipFile(archive) as stream:
        for member in stream.infolist():
            relative = safe_member(member.filename)
            target = destination / relative
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            files += 1
            if files > limits["max_files"]:
                raise AcquireError("archive exceeds maximum member count")
            mode = member.external_attr >> 16
            is_symlink = (mode & 0o170000) == 0o120000
            if is_symlink:
                link_target = safe_link_target(relative, stream.read(member).decode("utf-8"))
                ensure_parent(target)
                target.symlink_to(link_target)
                continue
            if (mode & 0o170000) not in (0, 0o100000):
                raise AcquireError(f"archive contains unsupported special member: {member.filename}")
            expanded += member.file_size
            if expanded > limits["max_expanded_bytes"]:
                raise AcquireError("archive exceeds maximum expanded size")
            ensure_parent(target)
            with stream.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output, 1024 * 1024)
    return files, expanded


def download(url, destination, max_bytes, retries):
    partial = destination.with_name(destination.name + ".part")
    error = None
    for _ in range(retries):
        try:
            offset = partial.stat().st_size if partial.exists() else 0
            request = urllib.request.Request(url)
            if offset:
                request.add_header("Range", f"bytes={offset}-")
            with urllib.request.urlopen(request, timeout=30) as response:
                resumed = offset > 0 and getattr(response, "status", None) == 206
                if not resumed:
                    offset = 0
                total = offset
                mode = "ab" if resumed else "wb"
                content_length = response.headers.get("Content-Length")
                expected = offset + int(content_length) if content_length is not None else None
                with partial.open(mode) as output:
                    while chunk := response.read(1024 * 1024):
                        total += len(chunk)
                        if total > max_bytes:
                            raise AcquireError("download exceeds maximum size")
                        output.write(chunk)
                if expected is not None and total != expected:
                    raise AcquireError(f"incomplete download: received {total} of {expected} bytes")
            partial.replace(destination)
            return
        except (OSError, urllib.error.URLError, AcquireError) as caught:
            error = caught
    raise AcquireError(f"download failed after {retries} attempts: {error}")


def acquire(input_value, output_dir, limits, retries):
    if output_dir.exists():
        raise AcquireError(f"output directory already exists: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        source = temporary / "source"
        archive = temporary / "archive"
        started = time.time()
        if input_value.startswith(("https://", "http://")):
            download(input_value, archive, limits["max_download_bytes"], retries)
            input_kind = "https-archive"
            input_digest = sha256_file(archive)
            archive_size = archive.stat().st_size
        else:
            input_path = Path(input_value).resolve()
            if not input_path.exists():
                raise AcquireError(f"input does not exist: {input_path}")
            if input_path.is_dir():
                input_kind = "local-tree"
                input_digest, _ = tree_digest(input_path)
                shutil.copytree(input_path, source, symlinks=True)
                archive_size = None
            else:
                input_kind = "local-archive"
                input_digest = sha256_file(input_path)
                archive_size = input_path.stat().st_size
                if archive_size > limits["max_download_bytes"]:
                    raise AcquireError("local archive exceeds maximum size")
                shutil.copy2(input_path, archive)

        if input_kind != "local-tree":
            source.mkdir()
            try:
                if tarfile.is_tarfile(archive):
                    archive_format = "tar"
                    extract_tar(archive, source, limits)
                elif zipfile.is_zipfile(archive):
                    archive_format = "zip"
                    extract_zip(archive, source, limits)
                else:
                    raise AcquireError("unsupported archive format; expected tar or zip")
            except (OSError, tarfile.TarError, zipfile.BadZipFile, UnicodeError) as error:
                raise AcquireError(f"cannot extract archive: {error}") from error
        else:
            archive_format = None

        source_digest, source_file_count = tree_digest(source)
        manifest = {
            "schema": 1,
            "input": input_value,
            "input_kind": input_kind,
            "input_sha256": input_digest,
            "archive_format": archive_format,
            "archive_size": archive_size,
            "source_sha256": source_digest,
            "source_file_count": source_file_count,
            "retrieved_unix_seconds": started,
            "limits": limits,
            "source_directory": "source",
        }
        (temporary / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        temporary.rename(output_dir)
        return manifest
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="local tree/archive or http(s) archive URL")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    parser.add_argument("--max-expanded-bytes", type=int, default=DEFAULT_MAX_EXPANDED_BYTES)
    parser.add_argument("--max-download-bytes", type=int, default=DEFAULT_MAX_DOWNLOAD_BYTES)
    args = parser.parse_args()
    if args.retries < 1 or args.max_files < 1 or args.max_expanded_bytes < 1 or args.max_download_bytes < 1:
        parser.error("limits and retries must be positive")
    limits = {
        "max_files": args.max_files,
        "max_expanded_bytes": args.max_expanded_bytes,
        "max_download_bytes": args.max_download_bytes,
    }
    try:
        manifest = acquire(args.input, args.output_dir.resolve(), limits, args.retries)
    except AcquireError as error:
        print(f"acquire_source: {error}", file=sys.stderr)
        return 2
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
