'''Generate a synthetic Kbuild tree with --n_ifeq ifeq/else blocks that choose a value,
a benchmark of RQ4. Block i sets V_i to wide or narrow by its own option, and obj-y takes
file_<i>_$(V_i).o, so each object name holds a value with two path conditions.

Output, under <target_dir>/value-<n_ifeq>/:
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
        lines += [f'ifeq ($(CONFIG_OPTION_{i}),y)', f'V_{i} := wide', 'else', f'V_{i} := narrow',
                  'endif', f'obj-y += file_{i}_$(V_{i}).o']
    return '\n'.join(lines) + '\n'


def truth(n_ifeq):
    # {object: build condition} by construction: wide with OPTION_i, narrow without it
    conditions = {}
    for i in range(1, n_ifeq + 1):
        option = z3.Bool(f'CONFIG_OPTION_{i}')
        conditions[f'bench/file_{i}_wide.o'] = option
        conditions[f'bench/file_{i}_narrow.o'] = z3.Not(option)
    return conditions


def prepare(args):
    name = f'value-{args.n_ifeq}'
    print(f'[+] preparing {name}:')
    src = os.path.join(args.target_dir, name, 'src')
    os.makedirs(os.path.join(src, 'bench'), exist_ok=True)
    with open(os.path.join(src, 'Makefile'), 'w') as f:
        f.write(TOP)
    with open(os.path.join(src, 'bench', 'Makefile'), 'w') as f:
        f.write(bench(args.n_ifeq))
    print(f'    - wrote {src}')
