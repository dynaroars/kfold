# per-target settings, keyed by --target; a target is a source tree, analyzed once,
# and its build trees are the configurations the analysis is evaluated against

# Make variables the build sets before the top-level Makefile runs. Linux's Makefile
# re-invokes itself once (need-sub-make) with sub_make_done=1 and --no-print-directory,
# and only that second invocation builds; ARCH=i386 selects the x86 tree (SRCARCH=x86),
# which i386 and x86_64 configurations share. coreboot derives MAINBOARDDIR from the
# string option CONFIG_MAINBOARD_DIR, which the analysis takes as fixed to the board
# the configurations share, as the earlier evaluation did
VARIABLES = {
    'busybox': {},
    'linux': {'ARCH': 'i386', 'sub_make_done': '1', 'MAKEFLAGS': '--no-print-directory'},
    'coreboot': {'MAINBOARDDIR': 'emulation/qemu-i440fx'},
}

# kmaxall arguments; None starts it from the tool's top-level directories. For Linux,
# the invocation of Kmax's documentation and the earlier evaluation, without -T since
# both tools treat options as Boolean and the evaluated configurations have no modules.
# coreboot has none: Kmax analyzes Kbuild goal definitions (obj-y), and coreboot lists
# its sources in per-stage variables (bootblock-y, romstage-y, ...) instead
KMAXALL = {
    'busybox': None,
    'linux': ['-DSRCARCH=x86', 'Kbuild', 'lib'],
}
