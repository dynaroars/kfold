# per-target settings, keyed by --target; a target is a source tree, analyzed once,
# and its build trees are the configurations the analysis is evaluated against

# Make variables the build sets before the top-level Makefile runs. Linux's Makefile
# re-invokes itself once (need-sub-make) with sub_make_done=1 and --no-print-directory,
# and only that second invocation builds; ARCH selects the tree under arch/ (SRCARCH),
# which i386 and x86_64 share as arch/x86. BusyBox and Xen derive the source root from
# CURDIR, Make's working directory, which is the tree root.
# U-Boot derives ARCH, CPU, VENDOR, and BOARD from string options, and coreboot MAINBOARDDIR
# from CONFIG_MAINBOARD_DIR; the analysis takes them as fixed to the board the
# configurations share, as the earlier evaluation did for coreboot
VARIABLES = {
    'busybox': {'CURDIR': '.'},
    'linux-i386': {'ARCH': 'i386', 'sub_make_done': '1', 'MAKEFLAGS': '--no-print-directory'},
    'linux-x86_64': {'ARCH': 'x86_64', 'sub_make_done': '1', 'MAKEFLAGS': '--no-print-directory'},
    'linux-arm64': {'ARCH': 'arm64', 'sub_make_done': '1', 'MAKEFLAGS': '--no-print-directory'},
    'linux-arm': {'ARCH': 'arm', 'sub_make_done': '1', 'MAKEFLAGS': '--no-print-directory'},
    'uboot': {'CONFIG_SYS_ARCH': '"arm"', 'CONFIG_SYS_CPU': '"armv8"',
              'CONFIG_SYS_VENDOR': '"emulation"', 'CONFIG_SYS_BOARD': '"qemu-arm"'},
    'barebox': {'ARCH': 'arm', 'sub_make_done': '1', 'MAKEFLAGS': '--no-print-directory'},
    'xen': {'CURDIR': '.', 'XEN_TARGET_ARCH': 'x86_64', 'sub_make_done': '1',
            'MAKEFLAGS': '--no-print-directory'},
    'coreboot': {'MAINBOARDDIR': 'emulation/qemu-i440fx'},
}

# the directory of a release that holds its Kbuild tree; the others are the release root
SUBDIR = {
    'xen': 'xen',
}

# kmaxall arguments; None starts it from the tool's top-level directories. For Linux,
# the invocation of Kmax's documentation and the earlier evaluation, without -T since
# both tools treat options as Boolean and the evaluated configurations have no modules.
# coreboot has none: Kmax analyzes Kbuild goal definitions (obj-y), and coreboot lists
# its sources in per-stage variables (bootblock-y, romstage-y, ...) instead
KMAXALL = {
    'busybox': None,
    'linux-i386': ['-DSRCARCH=x86', 'Kbuild', 'lib'],
    'linux-x86_64': ['-DSRCARCH=x86', 'Kbuild', 'lib'],
    'linux-arm64': ['-DSRCARCH=arm64', 'Kbuild', 'lib'],
    'linux-arm': ['-DSRCARCH=arm', 'Kbuild', 'lib'],
    'uboot': None,
    'barebox': None,
    'xen': None,
}
