'''Prepare U-Boot 2026.07 for analysis and build --n_build configurations: the QEMU
arm64 board and n_build - 1 perturbations of it.

Input:
  https://ftp.denx.de/pub/u-boot/u-boot-2026.07.tar.bz2 (checked against its SHA256)
  DEFCONFIG               the base configuration
  PINNED_OPTIONS          options fixed in every perturbation
  PERTURB_RATE            share of the other Boolean options a perturbation flips

Output, under <target_dir>/uboot/:
  u-boot-2026.07.tar.bz2  the release tarball
  src/                    analysis tree: the unmodified release
    Makefile              top-level Makefile, the entry point of the analysis
    */Makefile            per-directory build rules (obj-y, obj-$(CONFIG_...), ...)
    */Kconfig             Kconfig option definitions and dependencies
  0/ ... <n_build-1>/     build trees, each a copy of the release + .config + `make -k`
    .config               option values to evaluate build conditions against
    **/*.o                objects the build compiled, to compare with the tool's prediction

Output, under <csv_dir>/:
  prepare_uboot.csv       per configuration: options flipped, options that differ from
                          the base configuration after olddefconfig, and make's return code
'''
import subprocess
import os

from scenario.prepare.helper import download, extract, read_config, write_config, perturb, changed
from scenario.helper import progress_bar

VERSION = 'u-boot-2026.07'
# the arm64 board QEMU emulates, built with the aarch64 cross compiler
MAKE = ['make', 'CROSS_COMPILE=aarch64-linux-gnu-']
DEFCONFIG = 'qemu_arm64_defconfig'

# options a perturbation must not change ('y': set, 'n': not set)
PINNED_OPTIONS = {}
PERTURB_RATE = 0.05


def build(root, n_build, csv_path):
    pbar = progress_bar.create(total=n_build, unit='config',
                               desc=f'    - `make` {DEFCONFIG} and perturbations', csv_path=csv_path)
    base = None
    for i in range(n_build):
        tree = extract(os.path.join(root, f'{VERSION}.tar.bz2'), root, str(i), VERSION)
        config = os.path.join(tree, '.config')
        if i == 0:
            # 0/: the base configuration itself
            subprocess.run([*MAKE, DEFCONFIG], cwd=tree, check=True, capture_output=True)
            flipped = []
        else:
            # perturbation i uses seed i; olddefconfig repairs the Kconfig dependencies,
            # which can undo some flips, so changed counts what survives
            perturbed, flipped = perturb(base, i, PINNED_OPTIONS, PERTURB_RATE)
            write_config(config, perturbed)
            subprocess.run([*MAKE, 'olddefconfig'], cwd=tree, check=True, capture_output=True)
        final = read_config(config)
        if i == 0:
            base = final
        result = subprocess.run([*MAKE, '-k', f'-j{os.cpu_count()}'], cwd=tree, capture_output=True)
        pbar.step(flipped=len(flipped), changed=changed(base, final), returncode=result.returncode)
    pbar.to_csv()


def prepare(args):
    print('[+] preparing uboot:')
    root = os.path.join(args.target_dir, 'uboot')
    os.makedirs(root, exist_ok=True)

    url = f'https://ftp.denx.de/pub/u-boot/{VERSION}.tar.bz2'
    # U-Boot publishes no checksum file; download() prints the digest to record here
    sha256 = None

    print('    - downloading uboot')
    path = os.path.join(root, f'{VERSION}.tar.bz2')
    download(url, path, sha256)

    print('    - extracting src')
    extract(path, root, 'src', VERSION)

    build(root, args.n_build, os.path.join(args.csv_dir, 'prepare_uboot.csv'))
