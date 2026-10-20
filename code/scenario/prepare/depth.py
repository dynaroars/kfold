'''Generate a synthetic Kbuild tree that descends --n_ifeq directories deep, a benchmark
of RQ4. Each level is a subdirectory d/ of the one above, entered under an ifeq on its own
option, and builds one object, so the object of level j is built when the options of
levels 1 to j hold.

Output, under <target_dir>/depth-<n_ifeq>/:
  src/                    analysis tree
    Makefile              top-level Makefile, the entry point of the analysis; its default
                          goal descends into bench/ with $(MAKE) $(build)=bench, as Kbuild does
    bench/Makefile        enters level 1, bench/d/
    bench/d/.../Makefile  level j: obj-y += file.o, and enters level j + 1; n_ifeq objects
'''
import os

import z3

from scenario.prepare.length import TOP


def descent(level):
    # the lines that enter level `level` below the current directory
    return [f'ifeq ($(CONFIG_LEVEL_{level}),y)', 'obj-y += d/', 'endif']


def truth(n_ifeq):
    # {object: build condition} by construction: level j needs levels 1 to j
    return {'bench/' + 'd/' * j + 'file.o': z3.And([z3.Bool(f'CONFIG_LEVEL_{l}') for l in range(1, j + 1)])
            for j in range(1, n_ifeq + 1)}


def prepare(args):
    name = f'depth-{args.n_ifeq}'
    print(f'[+] preparing {name}:')
    src = os.path.join(args.target_dir, name, 'src')
    directory = os.path.join(src, 'bench')
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(src, 'Makefile'), 'w') as f:
        f.write(TOP)
    lines = descent(1) if args.n_ifeq else []
    for level in range(1, args.n_ifeq + 1):
        with open(os.path.join(directory, 'Makefile'), 'w') as f:
            f.write('\n'.join(lines) + '\n')
        directory = os.path.join(directory, 'd')
        os.makedirs(directory, exist_ok=True)
        lines = ['obj-y += file.o'] + (descent(level + 1) if level < args.n_ifeq else [])
    with open(os.path.join(directory, 'Makefile'), 'w') as f:
        f.write('\n'.join(lines) + '\n')
    print(f'    - wrote {src}')
