'''Generate a synthetic Kbuild tree with --n_ifeq composite objects, a benchmark of RQ4.
Composite i, comp_<i>.o, is selected by an ifeq on its own option and linked from three
members in comp_<i>-y, the third under a second option, so Kbuild compiles the members
and never compiles comp_<i>.o from a source file.

Output, under <target_dir>/composite-<n_ifeq>/:
  src/                    analysis tree
    Makefile              top-level Makefile, the entry point of the analysis; its default
                          goal descends into bench/ with $(MAKE) $(build)=bench, as Kbuild does
    bench/Makefile        the n_ifeq composites, 3 * n_ifeq member objects
'''
import os

import z3

from scenario.prepare.length import TOP

MEMBERS = 3


def bench(n_ifeq):
    lines = []
    for i in range(1, n_ifeq + 1):
        lines += [f'ifeq ($(CONFIG_OPTION_{i}),y)', f'obj-y += comp_{i}.o', 'endif',
                  f'comp_{i}-y := member_{i}_1.o member_{i}_2.o',
                  f'comp_{i}-$(CONFIG_EXTRA_{i}) += member_{i}_3.o']
    return '\n'.join(lines) + '\n'


def truth(n_ifeq):
    # {object: build condition} by construction: the members of comp_i.o, the third also
    # needing EXTRA_i; comp_i.o itself is never built
    conditions = {}
    for i in range(1, n_ifeq + 1):
        option = z3.Bool(f'CONFIG_OPTION_{i}')
        conditions[f'bench/member_{i}_1.o'] = option
        conditions[f'bench/member_{i}_2.o'] = option
        conditions[f'bench/member_{i}_3.o'] = z3.And(option, z3.Bool(f'CONFIG_EXTRA_{i}'))
    return conditions


def prepare(args):
    name = f'composite-{args.n_ifeq}'
    print(f'[+] preparing {name}:')
    src = os.path.join(args.target_dir, name, 'src')
    os.makedirs(os.path.join(src, 'bench'), exist_ok=True)
    with open(os.path.join(src, 'Makefile'), 'w') as f:
        f.write(TOP)
    with open(os.path.join(src, 'bench', 'Makefile'), 'w') as f:
        f.write(bench(args.n_ifeq))
    print(f'    - wrote {src}')
