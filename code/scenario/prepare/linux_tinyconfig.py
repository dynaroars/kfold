'''Prepare Linux 7.2.8 for analysis and build its i386 tinyconfig.

Input:
  https://cdn.kernel.org/pub/linux/kernel/v7.x/linux-7.2.8.tar.xz (checked against its SHA256)

Output, under <target_dir>/linux_tinyconfig/:
  linux-7.2.8.tar.xz      the release tarball
  src/                    analysis tree: the unmodified release
    Makefile              top-level Makefile, the entry point of the analysis
    Kbuild, */Makefile    per-directory build rules (obj-y, obj-m, lib-y, ...) that the tool analyzes
    */Kconfig             Kconfig option definitions and dependencies
  0/                      build tree: release + `make ARCH=i386 tinyconfig` + `make -k`
    .config               option values to evaluate build conditions against
    **/*.o                objects the build compiled, to compare with the tool's prediction

Output, under <csv_dir>/:
  prepare_linux_tinyconfig.csv  make's return code (nonzero: some file failed)
'''
import subprocess
import os

from scenario.prepare.helper import download, extract
from scenario.helper import progress_bar

VERSION = 'linux-7.2.8'
# tinyconfig is the smallest Linux configuration; i386 as in the earlier evaluation
MAKE = ['make', 'ARCH=i386']


def build_tinyconfig(path, root, csv_path):
    # one build tree 0/, so rq1 reads it like the first of --n_build trees
    pbar = progress_bar.create(total=1, unit='config', desc='    - `make` tinyconfig',
                               csv_path=csv_path)
    build = extract(path, root, '0', VERSION)
    subprocess.run([*MAKE, 'tinyconfig'], cwd=build, check=True, capture_output=True)
    result = subprocess.run([*MAKE, '-k', f'-j{os.cpu_count()}'], cwd=build,
                            capture_output=True)
    pbar.step(returncode=result.returncode)
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

    build_tinyconfig(path, root, os.path.join(args.csv_dir, 'prepare_linux_tinyconfig.csv'))
