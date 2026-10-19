from pymake3 import parser


def parse(path):
    '''Return the statements of the Makefile at `path`.'''
    with open(path) as f:
        return parser.parsestring(f.read(), path)
