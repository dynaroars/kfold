'''Prepare Linux 7.2.8 for analysis and build --n_build configurations of one
architecture: its tinyconfig and n_build - 1 perturbations of it. The analysis does not
depend on the configuration; tinyconfig is only the starting point of the configurations
evaluated. linux_i386.py, linux_x86_64.py, linux_arm64.py, and linux_arm.py call prepare()
with their ARCH and cross compiler.

Input:
  https://cdn.kernel.org/pub/linux/kernel/v7.x/linux-7.2.8.tar.xz (checked against its SHA256)
  PINNED_OPTIONS          options fixed in every perturbation
  PERTURB_RATE            share of the other Boolean options a perturbation flips

Output, under <target_dir>/linux-<arch>/:
  linux-7.2.8.tar.xz      the release tarball
  src/                    analysis tree: the unmodified release
    Makefile              top-level Makefile, the entry point of the analysis
    Kbuild, */Makefile    per-directory build rules (obj-y, obj-m, lib-y, ...) that the tool analyzes
    */Kconfig             Kconfig option definitions and dependencies
  0/                      build tree: release + `make ARCH=<arch> tinyconfig` + `make -k`
  1/ ... <n_build-1>/     build trees of the perturbations, built from src/ with `make O=<i>`
    .config               option values to evaluate build conditions against
    **/*.o                objects the build compiled, to compare with the tool's prediction

Output, under <csv_dir>/:
  prepare_linux-<arch>.csv  per configuration: options flipped, options that differ from
                            tinyconfig after olddefconfig, and make's return code
'''
import subprocess
import shutil
import glob
import os

from scenario.prepare.helper import download, extract, read_config, write_config, perturb, changed
from scenario.helper import progress_bar

VERSION = 'linux-7.2.8'

# options a perturbation must not change ('y': set, 'n': not set)
PINNED_OPTIONS = {
    'MODULES': 'n',  # the tool and the Kmax baseline treat options as Boolean
    'WERROR': 'n',   # GCC warnings would become errors, as in the earlier evaluation
}
PERTURB_RATE = 0.05


def build(root, n_build, csv_path, make):
    pbar = progress_bar.create(total=n_build, unit='config',
                               desc='    - `make` tinyconfig and perturbations', csv_path=csv_path)
    # 0/: tinyconfig itself, built in its own copy of the release
    tree = os.path.join(root, '0')
    subprocess.run([*make, 'tinyconfig'], cwd=tree, check=True, capture_output=True)
    result = subprocess.run([*make, '-k', f'-j{os.cpu_count()}'], cwd=tree, capture_output=True)
    base = read_config(os.path.join(tree, '.config'))
    pbar.step(flipped=0, changed=0, returncode=result.returncode)

    # 1/ ... <n_build-1>/: perturbation i uses seed i; olddefconfig repairs the Kconfig
    # dependencies, which can undo some flips, so changed counts what survives
    src = os.path.abspath(os.path.join(root, 'src'))
    for i in range(1, n_build):
        tree = os.path.abspath(os.path.join(root, str(i)))
        os.makedirs(tree, exist_ok=True)
        perturbed, flipped = perturb(base, i, PINNED_OPTIONS, PERTURB_RATE)
        write_config(os.path.join(tree, '.config'), perturbed)
        subprocess.run([*make, '-C', src, f'O={tree}', 'olddefconfig'], check=True,
                       capture_output=True)
        final = read_config(os.path.join(tree, '.config'))
        result = subprocess.run([*make, '-C', src, f'O={tree}', '-k', f'-j{os.cpu_count()}'],
                                capture_output=True)
        pbar.step(flipped=len(flipped), changed=changed(base, final), returncode=result.returncode)
    pbar.to_csv()


def prepare(args, arch, cross_compile=None):
    # arch is Make's ARCH; cross_compile the prefix of the cross compiler, None for the host's
    name = f'linux-{arch}'
    make = ['make', f'ARCH={arch}'] + ([f'CROSS_COMPILE={cross_compile}'] if cross_compile else [])
    print(f'[+] preparing {name}:')
    root = os.path.join(args.target_dir, name)
    os.makedirs(root, exist_ok=True)

    url = f'https://cdn.kernel.org/pub/linux/kernel/v7.x/{VERSION}.tar.xz'
    sha256 = '12e8d5a973d1ad7c5a5c69882e4022b131ed715db7003fdcd760ddf8c3e51941'

    # another architecture's target may hold the tarball already; download() then
    # finds it and checks its checksum
    path = os.path.join(root, f'{VERSION}.tar.xz')
    others = glob.glob(os.path.join(args.target_dir, 'linux-*', f'{VERSION}.tar.xz'))
    if not os.path.exists(path) and others:
        print(f'    - copying linux from {os.path.dirname(others[0])}')
        shutil.copy(others[0], path)
    else:
        print('    - downloading linux')
    download(url, path, sha256)

    print('    - extracting src')
    extract(path, root, 'src', VERSION)
    extract(path, root, '0', VERSION)

    build(root, args.n_build, os.path.join(args.csv_dir, f'prepare_{name}.csv'), make)
