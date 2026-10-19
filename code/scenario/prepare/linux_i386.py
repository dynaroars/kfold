'''Prepare Linux for i386 (32-bit x86) with the host compiler: see linux.py.'''
from scenario.prepare import linux

# no distribution among Debian, Fedora, and Arch builds an i386 kernel 7.2
BASES = {
    'tinyconfig': None,
    'defconfig': None,
    'allnoconfig': None,
    'allyesconfig': None,
}


def prepare(args):
    linux.prepare(args, 'i386', None, BASES)
