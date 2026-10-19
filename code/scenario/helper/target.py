# per-target settings, keyed by --target

# Make variables the build sets before the top-level Makefile runs. Linux's Makefile
# re-invokes itself once (need-sub-make) with sub_make_done=1 and --no-print-directory,
# and only that second invocation builds; ARCH=i386 is the tinyconfig build's architecture
VARIABLES = {
    'busybox': {},
    'linux_tinyconfig': {'ARCH': 'i386', 'sub_make_done': '1',
                         'MAKEFLAGS': '--no-print-directory'},
}

# kmaxall arguments; None starts it from the tool's top-level directories. For Linux,
# the invocation of Kmax's documentation and the earlier evaluation, without -T since
# both tools treat options as Boolean and tinyconfig has no modules
KMAXALL = {
    'busybox': None,
    'linux_tinyconfig': ['-DSRCARCH=x86', 'Kbuild', 'lib'],
}
