"""Pinned subjects and configurations for the canonical kfold evaluation.

Every experiment in experiments/ reads its inputs from here, so the paper's
numbers all come from one set of source releases, configurations, and
toolchains. Sources are downloaded release tarballs, verified against the
upstream checksum when the project publishes one (``sha256``); otherwise
fetch.py records the digest it observed in the run manifest.

Large artifacts (sources, build trees) live under work/ (gitignored). Small
artifacts (manifest, .config files, object inventories, results) are written
under results/ and evidence/ and are tracked.
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
SRC = WORK / "src"            # pristine, read-only extracted releases
BUILD = WORK / "build"        # one writable copy per (subject, config)
PREPARED = WORK / "prepared"  # analyzed trees: release + prepare step + skbuild.ini
DOWNLOADS = WORK / "downloads"
RESULTS = ROOT / "results"
EVIDENCE = ROOT / "evidence"
SETTINGS = ROOT / "experiments" / "settings"

# Toolchain used for every physical build (recorded in the manifest).
CC = "gcc"

SUBJECTS = {
    "linux": {
        "name": "Linux",
        "version": "7.2.8",
        "url": "https://cdn.kernel.org/pub/linux/kernel/v7.x/linux-7.2.8.tar.xz",
        "sha256": "12e8d5a973d1ad7c5a5c69882e4022b131ed715db7003fdcd760ddf8c3e51941",
        "topdir": "linux-7.2.8",
        "tristate": True,
        "configs": {
            # name: (how to produce .config, make variables)
            "tinyconfig": {"arch": "i386", "base": "tinyconfig"},
            "defconfig": {"arch": "x86_64", "base": "defconfig"},
            "debian": {"arch": "x86_64", "base": "file:/boot/config-7.2.6+deb14-amd64"},
            "allmodconfig": {"arch": "x86_64", "base": "allmodconfig"},
            # Configuration only (no build): used by the blind-spot query.
            "allyesconfig": {"arch": "x86_64", "base": "allyesconfig", "build": False},
        },
    },
    "busybox": {
        "name": "BusyBox",
        "version": "1.38.0",
        "url": "https://busybox.net/downloads/busybox-1.38.0.tar.bz2",
        "sha256": "34f9ea6ff8636f2c9241153b9114eefa9e65674a45318ae1ef95bb5f31c53bb2",
        "topdir": "busybox-1.38.0",
        # BusyBox ships Kbuild.src templates; its build generates each Kbuild
        # from them and from //kbuild: comments in the applet sources. The
        # analysis runs on a copy after this generator, before any configure.
        "prepare": "scripts/gen_build_files.sh . .",
        "tristate": False,
        "configs": {"defconfig": {"base": "defconfig"}},
    },
    "barebox": {
        "name": "Barebox",
        "version": "2026.09.0",
        "url": "https://www.barebox.org/download/barebox-2026.09.0.tar.bz2",
        "sha256": None,
        "topdir": "barebox-2026.09.0",
        "tristate": False,
        "configs": {"sandbox_defconfig": {"arch": "sandbox", "base": "sandbox_defconfig"}},
    },
    "uboot": {
        "name": "Das U-Boot",
        "version": "2026.07",
        "url": "https://ftp.denx.de/pub/u-boot/u-boot-2026.07.tar.bz2",
        "sha256": None,
        "topdir": "u-boot-2026.07",
        "tristate": False,
        "configs": {"sandbox_defconfig": {"base": "sandbox_defconfig"}},
    },
    "coreboot": {
        "name": "coreboot",
        "version": "26.06",
        "url": "https://coreboot.org/releases/coreboot-26.06.tar.xz",
        "sha256": "c573be035061abc93ad5097f7fec7a8ebb84b4fdd3c475f301a8f2ca5d06fd0d",
        "extra": [("https://coreboot.org/releases/coreboot-blobs-26.06.tar.xz",
                   "a9c0cb146975482c2faa685b12fd24056ccdb66422793eb3bdb848a80a6dc499")],
        "topdir": "coreboot-26.06",
        "tristate": False,
        "configs": {"qemu-i440fx": {"base": "mainboard:EMULATION_QEMU_X86_I440FX"}},
    },
}


def source_dir(subject):
    return SRC / SUBJECTS[subject]["topdir"]


def analysis_dir(subject):
    """Tree that kfold (and Kmax) analyze: a copy of the pristine release,
    after the subject's own build-file generator if it has a "prepare" step,
    with experiments/settings/<subject>.ini installed as skbuild.ini."""
    return PREPARED / SUBJECTS[subject]["topdir"]


def build_dir(subject, config):
    return BUILD / f"{subject}-{config}"


def settings_file(subject):
    return SETTINGS / f"{subject}.ini"
