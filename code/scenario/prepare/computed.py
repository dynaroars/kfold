'''Generate a synthetic Kbuild tree with --n_ifeq conditional lists, a benchmark of RQ2.
Block i assigns a_<i>.o to the list named list_<i>-$(CONFIG_A_<i>), which is list_<i>-y
when A_<i> is set, and adds b_<i>.o and, on a line of its own, $(list_<i>-y) to
obj-$(CONFIG_B_<i>), as drivers/firmware/efi/Makefile does in Linux; a_<i>.o is then built
when both options are set.

Output, under <target_dir>/computed-<n_ifeq>/:
  src/                    analysis tree
    Makefile              top-level Makefile, the entry point of the analysis; its default
                          goal descends into bench/ with $(MAKE) $(build)=bench, as Kbuild does
    bench/Makefile        the n_ifeq blocks, 2 * n_ifeq objects
'''
import os

import z3

from scenario.prepare.length import TOP


def bench(n_ifeq):
    lines = []
    for i in range(1, n_ifeq + 1):
        lines += [f'list_{i}-$(CONFIG_A_{i}) := a_{i}.o', f'obj-$(CONFIG_B_{i}) += b_{i}.o',
                  f'obj-$(CONFIG_B_{i}) += $(list_{i}-y)']
    return '\n'.join(lines) + '\n'


def truth(n_ifeq):
    # {object: build condition} by construction: b_i.o with B_i, and a_i.o with A_i and B_i
    conditions = {}
    for i in range(1, n_ifeq + 1):
        b = z3.Bool(f'CONFIG_B_{i}')
        conditions[f'bench/b_{i}.o'] = b
        conditions[f'bench/a_{i}.o'] = z3.And(z3.Bool(f'CONFIG_A_{i}'), b)
    return conditions


def prepare(args):
    name = f'computed-{args.n_ifeq}'
    print(f'[+] preparing {name}:')
    src = os.path.join(args.target_dir, name, 'src')
    os.makedirs(os.path.join(src, 'bench'), exist_ok=True)
    with open(os.path.join(src, 'Makefile'), 'w') as f:
        f.write(TOP)
    with open(os.path.join(src, 'bench', 'Makefile'), 'w') as f:
        f.write(bench(args.n_ifeq))
    print(f'    - wrote {src}')
