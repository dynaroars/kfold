'''Prepare Linux for 32-bit arm with the arm-none-eabi cross compiler: see linux.py.'''
from scenario.prepare import linux

# 32-bit arm has no plain defconfig; multi_v7_defconfig covers the ARMv7 boards, and
# Debian's armmp flavour is its multi-platform kernel
BASES = {
    'tinyconfig': None,
    'multi_v7_defconfig': None,
    'allnoconfig': None,
    'allyesconfig': None,
    'debian': (linux.DEBIAN.format(arch='armhf'), 'config.armhf_none_armmp.xz'),
}


def prepare(args):
    linux.prepare(args, 'arm', 'arm-none-eabi-', BASES)
