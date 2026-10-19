'''Prepare Linux for i386 (32-bit x86) with the host compiler: see linux.py.'''
from scenario.prepare import linux


def prepare(args):
    linux.prepare(args, 'i386')
