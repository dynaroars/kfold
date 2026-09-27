#!/bin/sh
# Package the kfold artifact: the committed tree at HEAD (tool, tests,
# pipeline, settings, results, and the small evidence files) without the
# paper, as dist/kfold-artifact-<commit>.tar.xz with a SHA256SUMS file.
#
# Usage: tools/make_artifact.sh [OUTDIR]
#
# Only committed files are packaged (git archive), so the downloaded
# releases, prepared trees and build directories under work/ and the
# untracked results/legacy/ and evidence/legacy/ never enter the archive.
# Commit (or stash) local changes first; the script refuses a dirty tree
# outside paper/.
set -e
cd "$(dirname "$0")/.."
out=${1:-dist}
if [ -n "$(git status --porcelain --untracked-files=no -- . ':!paper')" ]; then
    echo "make_artifact: uncommitted changes outside paper/; commit them first" >&2
    exit 1
fi
commit=$(git rev-parse --short=12 HEAD)
name=kfold-artifact-$commit
mkdir -p "$out"
git archive --format=tar --prefix="$name/" HEAD -- . ':!paper' ':!TAGS' | xz -9 -T0 > "$out/$name.tar.xz"
(cd "$out" && sha256sum "$name.tar.xz" > "$name.SHA256SUMS")
ls -l "$out/$name.tar.xz"
cat "$out/$name.SHA256SUMS"
