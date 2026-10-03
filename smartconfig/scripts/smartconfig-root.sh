#!/usr/bin/env bash
# Privileged, opt-in helper for SmartConfig evidence collection.
# Default operation is read-only. Package installation requires --install-deps.
set -Eeuo pipefail

usage() {
    cat <<'EOF'
Usage: scripts/smartconfig-root.sh [OPTIONS]
  --out DIR          Snapshot directory (default: ./root-snapshot-UTC)
  --install-deps     Install Debian/Ubuntu collection, build, Python, and QEMU tools
  --no-sudo-probes   Compatibility option; root already has probe access
  -h, --help         Show help

No kernel build, installation, bootloader change, or reboot is performed.
Raw evidence may contain local identifiers; sanitize it before sharing.
EOF
}

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
CALLER_HOME="${HOME:?HOME is required}"
if [[ -n "${SUDO_USER:-}" ]] && command -v getent >/dev/null 2>&1; then
    CALLER_HOME="$(getent passwd "$SUDO_USER" | cut -d: -f6)"
fi
OUT="$CALLER_HOME/smartconfig-snapshot-$(date -u +%Y%m%dT%H%M%SZ)"
INSTALL_DEPS=0
while (($#)); do
    case "$1" in
        --out) (($# >= 2)) || { echo "error: --out needs a directory" >&2; exit 2; }; OUT="$2"; shift 2;;
        --install-deps) INSTALL_DEPS=1; shift;;
        --no-sudo-probes) shift;;
        -h|--help) usage; exit 0;;
        *) echo "error: unknown option: $1" >&2; usage >&2; exit 2;;
    esac
done
if [[ "$(id -u)" -ne 0 ]]; then
    echo "error: run this helper as root (or use sudo)." >&2
    exit 2
fi
if [[ "$OUT" != /* ]]; then OUT="$REPO_DIR/$OUT"; fi
mkdir -p -- "$OUT"
chmod 700 -- "$OUT"

if ((INSTALL_DEPS)); then
    command -v apt-get >/dev/null 2>&1 || { echo "error: apt-get is required" >&2; exit 3; }
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y --no-install-recommends \
        ca-certificates curl git python3 python3-venv python3-pip \
        pciutils usbutils dmidecode lshw kmod initramfs-tools \
        build-essential bc flex bison libssl-dev libelf-dev libncurses-dev \
        dwarves cpio rsync clang lld llvm qemu-system-x86 qemu-utils ovmf busybox-static
    for required_tool in qemu-system-x86_64 git make python3; do
        command -v "$required_tool" >/dev/null 2>&1 || {
            echo "error: package installation did not provide $required_tool" >&2
            exit 6
        }
    done
    echo "installed: qemu=$(command -v qemu-system-x86_64) build-tools=make git python3"
fi

COLLECTOR="$REPO_DIR/scripts/collect.sh"
[[ -f "$COLLECTOR" ]] || { echo "error: collector missing: $COLLECTOR" >&2; exit 4; }
AUTOKERNEL_SCAN_SUDO=1 bash "$COLLECTOR" "$OUT" >/dev/null
PYTHON_BIN="$REPO_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
    PYTHON_BIN="$(command -v python3 || true)"
fi
if [[ -z "$PYTHON_BIN" ]] || ! PYTHONPATH="$REPO_DIR/src" "$PYTHON_BIN" -c 'import pydantic' >/dev/null 2>&1; then
    if ((INSTALL_DEPS)); then
        python3 -m venv "$REPO_DIR/.venv"
        "$REPO_DIR/.venv/bin/python" -m pip install -e "$REPO_DIR"
        PYTHON_BIN="$REPO_DIR/.venv/bin/python"
    else
        echo "error: project Python dependencies are missing." >&2
        echo "rerun with --install-deps or create .venv and install the project." >&2
        exit 5
    fi
fi
PYTHONPATH="$REPO_DIR/src" "$PYTHON_BIN" -c 'import sys; from pathlib import Path; from autokernel.snapshot import load; p=Path(sys.argv[1]); s=load(p); (p / "snapshot.json").write_text(s.model_dump_json(indent=2, exclude_none=True) + "\n"); print(f"host={s.host} pci={len(s.pci)} usb={len(s.usb)} modules={len(s.loaded_modules)} firmware={len(s.firmware)} initramfs_modules={len(s.initramfs_modules)}")' "$OUT"
if [[ -n "${SUDO_UID:-}" && -n "${SUDO_GID:-}" ]]; then
    chown -R -- "$SUDO_UID:$SUDO_GID" "$OUT"
    if [[ -d "$REPO_DIR/.venv" ]]; then
        chown -R -- "$SUDO_UID:$SUDO_GID" "$REPO_DIR/.venv"
    fi
fi
echo "snapshot: $OUT"
