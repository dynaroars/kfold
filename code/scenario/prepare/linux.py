'''Prepare Linux 7.2.8 for analysis and build --n_build configurations per base
configuration of one architecture: the base itself and n_build - 1 perturbations of it.
The analysis does not depend on the configuration and runs once per architecture on src/;
the bases spread the evaluated configurations from the smallest kernel to distribution
kernels. linux_i386.py, linux_x86_64.py, linux_arm64.py, and linux_arm.py call prepare()
with their ARCH, cross compiler, and bases.

Input:
  https://cdn.kernel.org/pub/linux/kernel/v7.x/linux-7.2.8.tar.xz (checked against its SHA256)
  bases                   {name: source} of the architecture: a make target such as
                          tinyconfig, or a distribution's configuration downloaded from a
                          pinned release (Debian package, Fedora commit, Arch tag)
  PINNED_OPTIONS          options fixed in every configuration
  PERTURB_RATE            share of the other Boolean options a perturbation flips

Output, under <target_dir>/linux-<arch>/:
  linux-7.2.8.tar.xz      the release tarball
  <file>                  the downloaded distribution configurations
  src/                    analysis tree: the unmodified release
    Makefile              top-level Makefile, the entry point of the analysis
    Kbuild, */Makefile    per-directory build rules (obj-y, obj-m, lib-y, ...) that the tool analyzes
    */Kconfig             Kconfig option definitions and dependencies
  <base>-0/               build tree of the base, built from src/ with `make O=<base>-0`
  <base>-1/ ... <base>-<n_build-1>/  build trees of the perturbations of the base
    .config               option values to evaluate build conditions against
    **/*.o                objects the build compiled, to compare with the tool's prediction

Output, under <csv_dir>/:
  prepare_linux-<arch>.csv  per configuration: its base, options flipped, options that
                            differ from the base after olddefconfig, and make's return code
'''
import urllib.parse
import subprocess
import shutil
import lzma
import glob
import os

from scenario.prepare.helper import download, extract, fetch, deb_member, read_config, write_config, perturb, changed
from scenario.helper import progress_bar

VERSION = 'linux-7.2.8'

# options every configuration fixes ('y': set, 'n': not set)
PINNED_OPTIONS = {
    'MODULES': 'n',  # the tool and the Kmax baseline treat options as Boolean
    'WERROR': 'n',   # GCC warnings would become errors, as in the earlier evaluation
}
PERTURB_RATE = 0.05

# the configurations of distribution kernels 7.2.11, at pinned addresses: a Debian
# linux-config package holds one compressed configuration per flavour, Fedora's at a
# commit of its f45 branch, Arch's at a release tag
DEBIAN = 'https://deb.debian.org/debian/pool/main/l/linux/linux-config-7.2_7.2.11-1_{arch}.deb'
FEDORA = ('https://src.fedoraproject.org/rpms/kernel/raw/'
          '178a0acce5e2efa309b71c69e5371a2d6584f700/f/kernel-{arch}-fedora.config')
ARCH = ('https://gitlab.archlinux.org/archlinux/packaging/packages/linux/-/raw/'
        '7.2.11.arch1-1/config.x86_64')


def run(make, *arguments):
    # the result of make; olddefconfig and the configuration targets must succeed
    check = '-k' not in arguments
    return subprocess.run([*make, *arguments], check=check, capture_output=True)


def configure(root, tree, base, source, make):
    # write the base's .config into tree: `make <base>`, or a distribution's file;
    # then fix PINNED_OPTIONS, and olddefconfig repairs the Kconfig dependencies
    src = os.path.abspath(os.path.join(root, 'src'))
    config = os.path.join(tree, '.config')
    if source is None:
        run(make, '-C', src, f'O={tree}', base)
    else:
        url, member = source
        path = os.path.join(root, os.path.basename(urllib.parse.urlparse(url).path))
        fetch(url, path)
        if member is None:
            shutil.copy(path, config)
        else:
            with open(config, 'wb') as f:
                f.write(lzma.decompress(deb_member(path, member)))
    options = read_config(config)
    options.update(PINNED_OPTIONS)
    write_config(config, options)
    run(make, '-C', src, f'O={tree}', 'olddefconfig')


def build(root, n_build, csv_path, make, bases):
    pbar = progress_bar.create(total=n_build * len(bases), unit='build',
                               desc='    - `make` bases and perturbations', csv_path=csv_path)
    src = os.path.abspath(os.path.join(root, 'src'))
    for base, source in bases.items():
        # <base>-0/: the base itself; <base>-<i>/: perturbation i, with seed i, of the base;
        # olddefconfig can undo some flips, so changed counts what survives
        for i in range(n_build):
            tree = os.path.abspath(os.path.join(root, f'{base}-{i}'))
            os.makedirs(tree, exist_ok=True)
            if i == 0:
                configure(root, tree, base, source, make)
                options = read_config(os.path.join(tree, '.config'))
                flipped = []
            else:
                perturbed, flipped = perturb(options, i, PINNED_OPTIONS, PERTURB_RATE)
                write_config(os.path.join(tree, '.config'), perturbed)
                run(make, '-C', src, f'O={tree}', 'olddefconfig')
            final = read_config(os.path.join(tree, '.config'))
            result = run(make, '-C', src, f'O={tree}', '-k', f'-j{os.cpu_count()}')
            pbar.step(base=base, config=i, flipped=len(flipped), changed=changed(options, final),
                      returncode=result.returncode)
    pbar.to_csv()


def prepare(args, arch, cross_compile, bases):
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

    build(root, args.n_build, os.path.join(args.csv_dir, f'prepare_{name}.csv'), make, bases)
