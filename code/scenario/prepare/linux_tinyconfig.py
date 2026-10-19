'''Prepare Linux 7.2.8 for analysis and build --n_build configurations: its i386
tinyconfig and n_build - 1 perturbations of it.

Input:
  https://cdn.kernel.org/pub/linux/kernel/v7.x/linux-7.2.8.tar.xz (checked against its SHA256)
  PINNED_OPTIONS          options fixed in every perturbation
  PERTURB_RATE            share of the other Boolean options a perturbation flips

Output, under <target_dir>/linux_tinyconfig/:
  linux-7.2.8.tar.xz      the release tarball
  src/                    analysis tree: the unmodified release
    Makefile              top-level Makefile, the entry point of the analysis
    Kbuild, */Makefile    per-directory build rules (obj-y, obj-m, lib-y, ...) that the tool analyzes
    */Kconfig             Kconfig option definitions and dependencies
  0/                      build tree: release + `make ARCH=i386 tinyconfig` + `make -k`
  1/ ... <n_build-1>/     build trees of the perturbations, built from src/ with `make O=<i>`
    .config               option values to evaluate build conditions against
    **/*.o                objects the build compiled, to compare with the tool's prediction

Output, under <csv_dir>/:
  prepare_linux_tinyconfig.csv  per configuration: options flipped, options that differ
                                from tinyconfig after olddefconfig, and make's return code
'''
import subprocess
import random
import os

from scenario.prepare.helper import download, extract
from scenario.helper import progress_bar

VERSION = 'linux-7.2.8'
# tinyconfig is the smallest Linux configuration; i386 as in the earlier evaluation
MAKE = ['make', 'ARCH=i386']

# options a perturbation must not change ('y': set, 'n': not set)
PINNED_OPTIONS = {
    'MODULES': 'n',  # the tool and the Kmax baseline treat options as Boolean
    'WERROR': 'n',   # GCC warnings would become errors, as in the earlier evaluation
}
PERTURB_RATE = 0.05


def read_config(path):
    # {option: value} in file order, with 'n' for "# CONFIG_X is not set"
    options = {}
    with open(path) as f:
        for line in f:
            if line.startswith('CONFIG_'):
                name, value = line.rstrip('\n').split('=', 1)
                options[name[len('CONFIG_'):]] = value
            elif line.startswith('# CONFIG_') and line.endswith(' is not set\n'):
                options[line[len('# CONFIG_'):-len(' is not set\n')]] = 'n'
    return options


def write_config(path, options):
    with open(path, 'w') as f:
        for name, value in options.items():
            f.write(f'# CONFIG_{name} is not set\n' if value == 'n' else f'CONFIG_{name}={value}\n')


def perturb(options, seed):
    # flip a seeded random PERTURB_RATE of the unpinned Boolean options, then pin
    candidates = [name for name, value in options.items()
                  if value in ('y', 'n') and name not in PINNED_OPTIONS]
    flipped = random.Random(seed).sample(candidates, round(PERTURB_RATE * len(candidates)))
    perturbed = dict(options)
    for name in flipped:
        perturbed[name] = 'n' if options[name] == 'y' else 'y'
    perturbed.update(PINNED_OPTIONS)
    return perturbed, flipped


def build(root, n_build, csv_path):
    pbar = progress_bar.create(total=n_build, unit='config',
                               desc='    - `make` tinyconfig and perturbations', csv_path=csv_path)
    # 0/: tinyconfig itself, built in its own copy of the release
    tree = os.path.join(root, '0')
    subprocess.run([*MAKE, 'tinyconfig'], cwd=tree, check=True, capture_output=True)
    result = subprocess.run([*MAKE, '-k', f'-j{os.cpu_count()}'], cwd=tree, capture_output=True)
    base = read_config(os.path.join(tree, '.config'))
    pbar.step(flipped=0, changed=0, returncode=result.returncode)

    # 1/ ... <n_build-1>/: perturbation i uses seed i; olddefconfig repairs the Kconfig
    # dependencies, which can undo some flips, so changed counts what survives
    src = os.path.abspath(os.path.join(root, 'src'))
    for i in range(1, n_build):
        tree = os.path.abspath(os.path.join(root, str(i)))
        os.makedirs(tree, exist_ok=True)
        perturbed, flipped = perturb(base, seed=i)
        write_config(os.path.join(tree, '.config'), perturbed)
        subprocess.run([*MAKE, '-C', src, f'O={tree}', 'olddefconfig'], check=True,
                       capture_output=True)
        final = read_config(os.path.join(tree, '.config'))
        changed = sum(final.get(name, 'n') != value for name, value in base.items()) + \
            sum(name not in base and value != 'n' for name, value in final.items())
        result = subprocess.run([*MAKE, '-C', src, f'O={tree}', '-k', f'-j{os.cpu_count()}'],
                                capture_output=True)
        pbar.step(flipped=len(flipped), changed=changed, returncode=result.returncode)
    pbar.to_csv()


def prepare(args):
    print('[+] preparing linux tinyconfig:')
    root = os.path.join(args.target_dir, 'linux_tinyconfig')
    os.makedirs(root, exist_ok=True)

    url = f'https://cdn.kernel.org/pub/linux/kernel/v7.x/{VERSION}.tar.xz'
    sha256 = '12e8d5a973d1ad7c5a5c69882e4022b131ed715db7003fdcd760ddf8c3e51941'

    print('    - downloading linux')
    path = os.path.join(root, f'{VERSION}.tar.xz')
    download(url, path, sha256)

    print('    - extracting src')
    extract(path, root, 'src', VERSION)
    extract(path, root, '0', VERSION)

    build(root, args.n_build, os.path.join(args.csv_dir, 'prepare_linux_tinyconfig.csv'))
