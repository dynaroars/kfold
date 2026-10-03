#!/usr/bin/env bash
# Run the available SmartConfig pipeline. Defaults are non-destructive.
set -Eeuo pipefail

usage() {
    cat <<'EOF'
Usage: scripts/smartconfig-all.sh [OPTIONS]
  --source DIR       use an existing complete kernel source tree
  --tag TAG          fetch an exact stable kernel tag (repeatable)
  --kernels DIR      checkout directory (default: $HOME/smartconfig-kernels)
  --work DIR         output directory (default: $HOME/smartconfig-runs)
  --snapshot DIR     existing snapshot; otherwise use $HOME/smartconfig-snapshot
  --collect-root     collect privileged read-only host evidence
  --install-deps     install Debian/Ubuntu build, Python, QEMU, and collection tools
  --build            build bzImage/modules after checking
  --vm-test          boot the built kernel with AutoKernel after --build
EOF
}

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
KERNELS="${HOME:?HOME is required}/smartconfig-kernels"
WORK="${HOME:?HOME is required}/smartconfig-runs"
SNAPSHOT=""
SOURCE=""
TAGS=()
COLLECT_ROOT=0
INSTALL_DEPS=0
BUILD=0
VM_TEST=0

while (($#)); do
    case "$1" in
        --source) SOURCE="$2"; shift 2;;
        --tag) TAGS+=("$2"); shift 2;;
        --kernels) KERNELS="$2"; shift 2;;
        --work) WORK="$2"; shift 2;;
        --snapshot) SNAPSHOT="$2"; shift 2;;
        --collect-root) COLLECT_ROOT=1; shift;;
        --install-deps) INSTALL_DEPS=1; shift;;
        --build) BUILD=1; shift;;
        --vm-test) VM_TEST=1; shift;;
        -h|--help) usage; exit 0;;
        *) echo "unknown option: $1" >&2; usage >&2; exit 2;;
    esac
done

if ((INSTALL_DEPS || COLLECT_ROOT)) && [[ "$(id -u)" -ne 0 ]]; then
    echo "error: --install-deps and --collect-root require root" >&2
    exit 2
fi
mkdir -p -- "$WORK"
if ((${#TAGS[@]})) || [[ -z "$SOURCE" ]]; then
    mkdir -p -- "$KERNELS"
fi
PYTHON="$REPO_DIR/.venv/bin/python"
SMARTCONFIG="$REPO_DIR/.venv/bin/smartconfig"
AUTOKERNEL="$REPO_DIR/.venv/bin/autokernel"

if ((INSTALL_DEPS)); then
    [[ -x "$(command -v apt-get || true)" ]] || { echo "error: apt-get unavailable" >&2; exit 4; }
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y --no-install-recommends \
        ca-certificates curl git python3 python3-venv python3-pip \
        pciutils usbutils dmidecode lshw kmod initramfs-tools \
        build-essential bc flex bison libssl-dev libelf-dev libncurses-dev \
        dwarves cpio rsync clang lld llvm qemu-system-x86 qemu-utils ovmf busybox-static
fi

if [[ ! -x "$PYTHON" || ! -x "$SMARTCONFIG" ]]; then
    if ((INSTALL_DEPS)); then
        python3 -m venv "$REPO_DIR/.venv"
        "$REPO_DIR/.venv/bin/python" -m pip install -e "$REPO_DIR"
    else
        echo "error: missing .venv; rerun with --install-deps or bootstrap python3 -m venv .venv && .venv/bin/python -m pip install -e ." >&2
        exit 3
    fi
fi

if ((COLLECT_ROOT)); then
    [[ -n "$SNAPSHOT" ]] || SNAPSHOT="$WORK/snapshot"
    bash "$SCRIPT_DIR/smartconfig-root.sh" --out "$SNAPSHOT"
elif [[ -z "$SNAPSHOT" ]]; then
    SNAPSHOT="${HOME:?HOME is required}/smartconfig-snapshot"
fi
[[ -r "$SNAPSHOT/running_config" ]] || { echo "error: missing $SNAPSHOT/running_config" >&2; exit 5; }

BOOT_SNAPSHOT="$SNAPSHOT"
if ((VM_TEST)); then
    # AutoKernel records serial output beside the snapshot. Keep analysis
    # read-only when the snapshot was collected elsewhere or is not writable.
    if ! mkdir -p -- "$SNAPSHOT/boot-test" 2>/dev/null; then
        BOOT_SNAPSHOT="$WORK/vm-snapshot"
        mkdir -p -- "$BOOT_SNAPSHOT"
        cp -a -- "$SNAPSHOT"/. "$BOOT_SNAPSHOT"/
        echo "vm snapshot: $BOOT_SNAPSHOT (writable copy)"
    fi
fi

"$SMARTCONFIG" require overlayfs tun-tap usb-mass-storage root-storage \
    --out "$WORK/requirements.json"

for tag in "${TAGS[@]}"; do
    target="$KERNELS/linux-${tag#v}"
    if [[ ! -d "$target/.git" ]]; then
        git clone --depth 1 --branch "$tag" \
            https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git "$target"
    fi
done

if [[ -n "$SOURCE" ]]; then
    SOURCES=("$SOURCE")
else
    mapfile -t SOURCES < <(find "$KERNELS" -mindepth 1 -maxdepth 1 -type d -name 'linux-*' -print | sort)
fi
((${#SOURCES[@]})) || { echo "error: provide --source or --tag" >&2; exit 6; }
for source in "${SOURCES[@]}"; do
    if [[ ! -d "$source" || ! -f "$source/Kconfig" || ! -f "$source/Makefile" ]]; then
        echo "error: not a complete kernel source tree: $source" >&2
        echo "provide a real path containing Kconfig and Makefile, or use --tag TAG" >&2
        exit 7
    fi
done

for source in "${SOURCES[@]}"; do
    name="$(basename "$source")"
    run="$WORK/$name"
    mkdir -p -- "$run"
    baseline_config="$SNAPSHOT/running_config"
    candidate_config="$SNAPSHOT/running_config"
    if ((BUILD)); then
        native="$run/native"
        mkdir -p -- "$native"
        make -C "$source" O="$native" ARCH=x86_64 defconfig >/dev/null
        cp "$native/.config" "$native/baseline.config"
        if [[ -x "$source/scripts/config" ]]; then
            "$source/scripts/config" --file "$native/.config" \
                --enable OVERLAY_FS --enable TUN --enable USB_STORAGE \
                --enable EXT4_FS --enable KVM --enable KVM_INTEL
        else
            echo "error: $source lacks scripts/config; cannot generate target-native candidate" >&2
            exit 9
        fi
        make -C "$source" O="$native" ARCH=x86_64 olddefconfig >/dev/null
        baseline_config="$native/baseline.config"
        candidate_config="$native/.config"
    fi
    "$SMARTCONFIG" map --source "$source" --out "$run/mapping.json"
    set +e
    "$SMARTCONFIG" check --source "$source" --baseline "$baseline_config" \
        --candidate "$candidate_config" --requirements "$WORK/requirements.json" \
        --snapshot "$SNAPSHOT" --out "$run/check"
    check_rc=$?
    set -e
    if ((BUILD)) && ((check_rc != 0)); then
        echo "error: refusing to build $source because configuration check failed (exit $check_rc)" >&2
        exit 8
    fi
    "$SMARTCONFIG" artifacts --source "$source" --config "$candidate_config" \
        --out "$run/artifacts.json"
    if ((BUILD)); then
        build="$run/build"
        mkdir -p -- "$build"
        cp "$candidate_config" "$build/.config"
        make -C "$source" O="$build" olddefconfig
        make -C "$source" O="$build" -j"$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 1)" bzImage modules
        "$SMARTCONFIG" validate --source "$source" --config "$build/.config" \
            --requirements "$WORK/requirements.json" --out "$run/validation"
        "$SMARTCONFIG" artifacts --source "$build" --config "$build/.config" \
            --out "$run/built-artifacts.json"
        if ((VM_TEST)); then
            "$AUTOKERNEL" boot-test "$BOOT_SNAPSHOT" --kernel-source "$build" --method auto
        fi
    fi
done
echo "completed: $WORK"
