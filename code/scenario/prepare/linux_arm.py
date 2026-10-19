'''Prepare Linux for 32-bit arm with the arm-none-eabi cross compiler: see linux.py.'''
from scenario.prepare import linux


def prepare(args):
    linux.prepare(args, 'arm', 'arm-none-eabi-')
