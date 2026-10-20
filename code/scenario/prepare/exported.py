'''Generate a synthetic Kbuild tree whose top-level Makefile exports a variable that
--n_ifeq goal definitions in a subdirectory name objects with, a benchmark of RQ2. The
top-level Makefile sets BITS to 64 or 32 by CONFIG_64BIT, as Linux's arch/x86/Makefile
does, and block i of bench/Makefile adds base_<i>.o and part_<i>_$(BITS).o under its own
option, as in arch/x86/mm/Makefile.

Output, under <target_dir>/exported-<n_ifeq>/:
  src/                    analysis tree
    Makefile              top-level Makefile, the entry point of the analysis: sets and
                          exports BITS, and its default goal descends into bench/ with
                          $(MAKE) $(build)=bench, as Kbuild does
    bench/Makefile        the n_ifeq blocks, 3 * n_ifeq objects
'''
import os

import z3

from scenario.prepare.length import TOP

EXPORT = '''ifeq ($(CONFIG_64BIT),y)
BITS := 64
else
BITS := 32
endif
export BITS

'''


def bench(n_ifeq):
    lines = []
    for i in range(1, n_ifeq + 1):
        lines += [f'ifeq ($(CONFIG_OPTION_{i}),y)', f'obj-y += base_{i}.o part_{i}_$(BITS).o', 'endif']
    return '\n'.join(lines) + '\n'


def truth(n_ifeq):
    # {object: build condition} by construction: base_i.o with OPTION_i, and part_i_64.o or
    # part_i_32.o with OPTION_i and the value of BITS
    bits = z3.Bool('CONFIG_64BIT')
    conditions = {}
    for i in range(1, n_ifeq + 1):
        option = z3.Bool(f'CONFIG_OPTION_{i}')
        conditions[f'bench/base_{i}.o'] = option
        conditions[f'bench/part_{i}_64.o'] = z3.And(option, bits)
        conditions[f'bench/part_{i}_32.o'] = z3.And(option, z3.Not(bits))
    return conditions


def prepare(args):
    name = f'exported-{args.n_ifeq}'
    print(f'[+] preparing {name}:')
    src = os.path.join(args.target_dir, name, 'src')
    os.makedirs(os.path.join(src, 'bench'), exist_ok=True)
    with open(os.path.join(src, 'Makefile'), 'w') as f:
        f.write(EXPORT + TOP)
    with open(os.path.join(src, 'bench', 'Makefile'), 'w') as f:
        f.write(bench(args.n_ifeq))
    print(f'    - wrote {src}')
