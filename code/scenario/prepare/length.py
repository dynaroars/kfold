'''Generate a synthetic Kbuild tree whose Makefile grows by --n_ifeq independent
conditional blocks, the scaling benchmark of RQ2. Each block tests its own option and
appends a distinct object to an intermediate variable that obj-y takes at the end, so the
directory Makefile has 2^n_ifeq execution paths and n_ifeq objects.

Output, under <target_dir>/length-<n_ifeq>/:
  src/                    analysis tree
    Makefile              top-level Makefile, the entry point of the analysis; its default
                          goal descends into bench/ with $(MAKE) $(build)=bench, as Kbuild does
    bench/Makefile        the n_ifeq conditional blocks
'''
import os

import z3

TOP = '''build := -f scripts/Makefile.build obj

all:
\t$(MAKE) $(build)=bench
'''


def bench(n_ifeq):
    # the directory Makefile: OPTION_i selects file_i.o through OBJS
    lines = ['OBJS :=']
    for i in range(1, n_ifeq + 1):
        lines += [f'ifeq ($(CONFIG_OPTION_{i}),y)', f'OBJS += file_{i}.o', 'endif']
    lines.append('obj-y += $(OBJS)')
    return '\n'.join(lines) + '\n'


def truth(n_ifeq):
    # {object: build condition} by construction: file_i.o is built with OPTION_i
    return {f'bench/file_{i}.o': z3.Bool(f'CONFIG_OPTION_{i}') for i in range(1, n_ifeq + 1)}


def prepare(args):
    name = f'length-{args.n_ifeq}'
    print(f'[+] preparing {name}:')
    src = os.path.join(args.target_dir, name, 'src')
    os.makedirs(os.path.join(src, 'bench'), exist_ok=True)
    with open(os.path.join(src, 'Makefile'), 'w') as f:
        f.write(TOP)
    with open(os.path.join(src, 'bench', 'Makefile'), 'w') as f:
        f.write(bench(args.n_ifeq))
    print(f'    - wrote {src}')
