'''Prepare Linux for arm64 with the aarch64 cross compiler: see linux.py.'''
from scenario.prepare import linux

BASES = {
    'tinyconfig': None,
    'defconfig': None,
    'allnoconfig': None,
    'debian': (linux.DEBIAN.format(arch='arm64'), 'config.arm64_none_arm64.xz'),
    'fedora': (linux.FEDORA.format(arch='aarch64'), None),
}


def prepare(args):
    linux.prepare(args, 'arm64', 'aarch64-linux-gnu-', BASES)
