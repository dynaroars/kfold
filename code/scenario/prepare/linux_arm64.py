'''Prepare Linux for arm64 with the aarch64 cross compiler: see linux.py.'''
from scenario.prepare import linux


def prepare(args):
    linux.prepare(args, 'arm64', 'aarch64-linux-gnu-')
