'''Prepare coreboot 26.06 for analysis and build --n_build configurations: the QEMU
i440fx mainboard and n_build - 1 perturbations of it.

Input:
  https://coreboot.org/releases/coreboot-26.06.tar.xz (checked against its SHA256)
  BOARD_OPTIONS           the options that select the mainboard
  PINNED_OPTIONS          options fixed in every configuration
  PERTURB_RATE            share of the other Boolean options a perturbation flips

Output, under <target_dir>/coreboot/:
  coreboot-26.06.tar.xz   the release tarball
  src/                    analysis tree: the unmodified release
    Makefile, Makefile.mk top-level Makefiles, the entry point of the analysis
    src/**/Makefile.mk    per-directory build rules (bootblock-y, romstage-y, ramstage-y, ...)
    src/**/Kconfig        Kconfig option definitions and dependencies
  0/ ... <n_build-1>/     build trees, each a copy of the release + .config + `make -k`
    .config               option values to evaluate build conditions against
    build/**/*.o          objects the build compiled, to compare with the tool's prediction

Output, under <csv_dir>/:
  prepare_coreboot.csv    per configuration: options flipped, options that differ from
                          the base configuration after olddefconfig, and make's return code
'''
import subprocess
import os

from scenario.prepare.helper import download, extract, read_config, write_config, perturb, changed
from scenario.helper import progress_bar

VERSION = 'coreboot-26.06'

# the base configuration, as in the earlier evaluation: the QEMU i440fx board
BOARD_OPTIONS = {'VENDOR_EMULATION': 'y', 'BOARD_EMULATION_QEMU_X86_I440FX': 'y'}

# options a configuration must not change ('y': set, 'n': not set)
PINNED_OPTIONS = {
    **BOARD_OPTIONS,
    'PAYLOAD_NONE': 'y',   # the default SeaBIOS payload would be cloned mid-build
    'ANY_TOOLCHAIN': 'y',  # build with the host gcc -m32 instead of coreboot's crossgcc
}
PERTURB_RATE = 0.05


def build(root, n_build, csv_path):
    pbar = progress_bar.create(total=n_build, unit='config',
                               desc='    - `make` qemu-i440fx and perturbations', csv_path=csv_path)
    base = None
    for i in range(n_build):
        tree = extract(os.path.join(root, f'{VERSION}.tar.xz'), root, str(i), VERSION)
        config = os.path.join(tree, '.config')
        if i == 0:
            # 0/: the base configuration; olddefconfig fills in the defaults
            write_config(config, PINNED_OPTIONS)
            flipped = []
        else:
            perturbed, flipped = perturb(base, i, PINNED_OPTIONS, PERTURB_RATE)
            write_config(config, perturbed)
        subprocess.run(['make', 'olddefconfig'], cwd=tree, check=True, capture_output=True)
        final = read_config(config)
        if i == 0:
            base = final
        result = subprocess.run(['make', '-k', f'-j{os.cpu_count()}'], cwd=tree,
                                capture_output=True)
        pbar.step(flipped=len(flipped), changed=changed(base, final),
                  returncode=result.returncode)
    pbar.to_csv()


def prepare(args):
    print('[+] preparing coreboot:')
    root = os.path.join(args.target_dir, 'coreboot')
    os.makedirs(root, exist_ok=True)

    url = f'https://coreboot.org/releases/{VERSION}.tar.xz'
    sha256 = 'c573be035061abc93ad5097f7fec7a8ebb84b4fdd3c475f301a8f2ca5d06fd0d'

    print('    - downloading coreboot')
    path = os.path.join(root, f'{VERSION}.tar.xz')
    download(url, path, sha256)

    print('    - extracting src')
    extract(path, root, 'src', VERSION)

    build(root, args.n_build, os.path.join(args.csv_dir, 'prepare_coreboot.csv'))
