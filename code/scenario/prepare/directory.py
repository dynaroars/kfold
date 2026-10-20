'''Generate a synthetic Kbuild tree that descends into --n_ifeq subdirectories, a benchmark
of RQ4. bench/Makefile enters dir_<i>/ under an ifeq on its own option, and each
subdirectory builds one object, so the cost of the analysis is the descent itself.

Output, under <target_dir>/directory-<n_ifeq>/:
  src/                    analysis tree
    Makefile              top-level Makefile, the entry point of the analysis; its default
                          goal descends into bench/ with $(MAKE) $(build)=bench, as Kbuild does
    bench/Makefile        the n_ifeq conditional descents
    bench/dir_<i>/Makefile  obj-y += file.o, n_ifeq objects in all
'''
import os

from scenario.prepare.synthetic import TOP


def prepare(args):
    name = f'directory-{args.n_ifeq}'
    print(f'[+] preparing {name}:')
    src = os.path.join(args.target_dir, name, 'src')
    os.makedirs(os.path.join(src, 'bench'), exist_ok=True)
    with open(os.path.join(src, 'Makefile'), 'w') as f:
        f.write(TOP)
    lines = []
    for i in range(1, args.n_ifeq + 1):
        lines += [f'ifeq ($(CONFIG_DIR_{i}),y)', f'obj-y += dir_{i}/', 'endif']
        os.makedirs(os.path.join(src, 'bench', f'dir_{i}'), exist_ok=True)
        with open(os.path.join(src, 'bench', f'dir_{i}', 'Makefile'), 'w') as f:
            f.write('obj-y += file.o\n')
    with open(os.path.join(src, 'bench', 'Makefile'), 'w') as f:
        f.write('\n'.join(lines) + '\n')
    print(f'    - wrote {src}')
