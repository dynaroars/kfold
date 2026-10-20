'''Generate a synthetic Kbuild tree of BLOCKS independent blocks, each --n_ifeq ifeq
statements deep, a benchmark of RQ4. Level j of block b tests its own option and appends
file_<b>_<j>.o to an intermediate variable that obj-y takes at the end, so the object of
level j is built when the options of levels 1 to j hold.

Output, under <target_dir>/nested-<n_ifeq>/:
  src/                    analysis tree
    Makefile              top-level Makefile, the entry point of the analysis; its default
                          goal descends into bench/ with $(MAKE) $(build)=bench, as Kbuild does
    bench/Makefile        the BLOCKS nested blocks, BLOCKS * n_ifeq objects
'''
import os

from scenario.prepare.synthetic import TOP

BLOCKS = 100


def bench(depth):
    lines = ['OBJS :=']
    for b in range(1, BLOCKS + 1):
        for j in range(1, depth + 1):
            lines += [f'ifeq ($(CONFIG_OPTION_{b}_{j}),y)', f'OBJS += file_{b}_{j}.o']
        lines += ['endif'] * depth
    lines.append('obj-y += $(OBJS)')
    return '\n'.join(lines) + '\n'


def prepare(args):
    name = f'nested-{args.n_ifeq}'
    print(f'[+] preparing {name}:')
    src = os.path.join(args.target_dir, name, 'src')
    os.makedirs(os.path.join(src, 'bench'), exist_ok=True)
    with open(os.path.join(src, 'Makefile'), 'w') as f:
        f.write(TOP)
    with open(os.path.join(src, 'bench', 'Makefile'), 'w') as f:
        f.write(bench(args.n_ifeq))
    print(f'    - wrote {src}')
