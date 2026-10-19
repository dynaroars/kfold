'''Prepare Linux for x86-64 with the host compiler: see linux.py.'''
from scenario.prepare import linux

BASES = {
    'tinyconfig': None,
    'defconfig': None,
    'allnoconfig': None,
    'debian': (linux.DEBIAN.format(arch='amd64'), 'config.amd64_none_amd64.xz'),
    'fedora': (linux.FEDORA.format(arch='x86_64'), None),
    'arch': (linux.ARCH, None),
}


def prepare(args):
    linux.prepare(args, 'x86_64', None, BASES)
