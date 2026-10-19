'''Prepare Xen 4.22.0 for analysis and build --n_build configurations of its x86_64
hypervisor: the default configuration and n_build - 1 perturbations of it. The
hypervisor, in xen/, is the Kbuild tree of the release.

Input:
  https://downloads.xenproject.org/release/xen/4.22.0/xen-4.22.0.tar.gz (checked against its SHA256)
  PINNED_OPTIONS          options fixed in every perturbation
  PERTURB_RATE            share of the other Boolean options a perturbation flips

Output, under <target_dir>/xen/:
  xen-4.22.0.tar.gz       the release tarball
  src/                    the unmodified release
    xen/                  analysis tree: the hypervisor
      Makefile            top-level Makefile, the entry point of the analysis
      */Makefile          per-directory build rules (obj-y, obj-$(CONFIG_...), ...)
      */Kconfig           Kconfig option definitions and dependencies
  0/ ... <n_build-1>/     build trees, each a copy of the release + `make -C xen -k`
    xen/.config           option values to evaluate build conditions against
    xen/**/*.o            objects the build compiled, to compare with the tool's prediction

Output, under <csv_dir>/:
  prepare_xen.csv         per configuration: options flipped, options that differ from
                          the base configuration after olddefconfig, and make's return code
'''
import subprocess
import os

from scenario.prepare.helper import download, extract, read_config, write_config, perturb, changed
from scenario.helper import progress_bar

VERSION = 'xen-4.22.0'
# the hypervisor for the host architecture, x86_64
MAKE = ['make', '-C', 'xen']

# options a perturbation must not change ('y': set, 'n': not set)
PINNED_OPTIONS = {}
PERTURB_RATE = 0.05


def build(root, n_build, csv_path):
    pbar = progress_bar.create(total=n_build, unit='config',
                               desc='    - `make` defconfig and perturbations', csv_path=csv_path)
    base = None
    for i in range(n_build):
        tree = extract(os.path.join(root, f'{VERSION}.tar.gz'), root, str(i), VERSION)
        config = os.path.join(tree, 'xen', '.config')
        if i == 0:
            # 0/: the base configuration itself
            subprocess.run([*MAKE, 'defconfig'], cwd=tree, check=True, capture_output=True)
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
    print('[+] preparing xen:')
    root = os.path.join(args.target_dir, 'xen')
    os.makedirs(root, exist_ok=True)

    url = f'https://downloads.xenproject.org/release/xen/4.22.0/{VERSION}.tar.gz'
    # Xen publishes signatures and no checksum file; download() prints the digest to record here
    sha256 = None

    print('    - downloading xen')
    path = os.path.join(root, f'{VERSION}.tar.gz')
    download(url, path, sha256)

    print('    - extracting src')
    extract(path, root, 'src', VERSION)

    build(root, args.n_build, os.path.join(args.csv_dir, 'prepare_xen.csv'))
