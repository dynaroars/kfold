"""Prepare BusyBox 1.38.0 for analysis and build --n_build random configurations.

Input:
  https://busybox.net/downloads/busybox-1.38.0.tar.bz2 (checked against its SHA256)

Output, under <target_dir>/busybox/:
  busybox-1.38.0.tar.bz2  the release tarball
  src/                    analysis tree: release + generated Kbuild files
    Makefile              top-level Makefile, the entry point of the analysis
    */Kbuild              per-directory build rules (obj-y, lib-y, ...) that kfold analyzes
    */Config.in           Kconfig option definitions and dependencies
  0/ ... <n_build-1>/     build trees: release + `make randconfig` + `make -k`
    .config               option values (CONFIG_X=y or unset) to evaluate build conditions against
    **/*.o                objects the build compiled, to compare with kfold's prediction

Output, under <csv_dir>/:
  busybox_build.csv       make's return code per configuration (nonzero: some file failed)
"""
import urllib.request
import subprocess
import hashlib
import tarfile
import os

from scenario.helper import progress_bar


def download(url, path, sha256):
    if not os.path.exists(path):
        urllib.request.urlretrieve(url, path)
    with open(path, 'rb') as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    if digest != sha256:
        raise SystemExit(f'checksum mismatch for {path}: {digest}')


def extract(path, root, name):
    dest = os.path.join(root, name)
    if os.path.exists(dest):
        return dest
    with tarfile.open(path) as tar:
        tar.extractall(root, filter='data')
    os.rename(os.path.join(root, 'busybox-1.38.0'), dest)
    return dest


def prepare(args):
    print('[+] preparing busybox:')
    root = os.path.join(args.target_dir, 'busybox')
    os.makedirs(root, exist_ok=True)

    url = 'https://busybox.net/downloads/busybox-1.38.0.tar.bz2'
    sha256 = '34f9ea6ff8636f2c9241153b9114eefa9e65674a45318ae1ef95bb5f31c53bb2'

    print('    - downloading busybox')
    path = os.path.join(root, f'busybox-1.38.0.tar.bz2')
    download(url, path, sha256)

    print('    - extracting analysis tree')
    src = extract(path, root, 'src')

    # BusyBox ships Kbuild.src and Config.src templates; generate the real
    # Kbuild and Config.in files from them and from //kbuild: and //config: comments.
    print('    - generating kbuild files')
    subprocess.run(['sh', 'scripts/gen_build_files.sh', '.', '.'], cwd=src, check=True,
                   capture_output=True)

    # One separate copy per random configuration, so configuring and building
    # never touch the analysis tree. Each writes <i>/.config and its objects.
    # make -k keeps going past files that fail to compile, so a nonzero
    # return code is recorded, not raised.
    pbar = progress_bar.create(total=args.n_build, unit='config', desc='    - building random configs',
                               csv_path=os.path.join(args.csv_dir, 'busybox_build.csv'))
    for i in range(args.n_build):
        build = extract(path, root, str(i))
        subprocess.run(['make', 'randconfig'], cwd=build, check=True,
                       capture_output=True)
        result = subprocess.run(['make', '-k', f'-j{os.cpu_count()}'], cwd=build,
                                capture_output=True)
        pbar.step(config=i, returncode=result.returncode)
    pbar.to_csv()
