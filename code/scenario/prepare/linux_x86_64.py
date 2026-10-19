'''Prepare Linux for x86-64 with the host compiler: see linux.py.'''
from scenario.prepare import linux


def prepare(args):
    linux.prepare(args, 'x86_64')
