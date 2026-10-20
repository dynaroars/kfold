'''Prepare BusyBox 1.38.0 for analysis and build --n_build random configurations.

Input:
  https://busybox.net/downloads/busybox-1.38.0.tar.bz2 (checked against its SHA256)
  PINNED_OPTIONS          options fixed in every random configuration

Output, under <target_dir>/busybox/:
  busybox-1.38.0.tar.bz2  the release tarball
  src/                    analysis tree: release + generated Kbuild files
    Makefile              top-level Makefile, the entry point of the analysis
    */Kbuild              per-directory build rules (obj-y, lib-y, ...) that the tool analyzes
    */Config.in           Kconfig option definitions and dependencies
  0/ ... <n_build-1>/     build trees: release + `make randconfig` + `make -k`
    .config               option values (CONFIG_X=y or unset) to evaluate build conditions against
    **/*.o                objects the build compiled, to compare with the tool's prediction

Output, under <csv_dir>/:
  busybox_build.csv       make's return code per configuration (nonzero: some file failed)
'''
import subprocess
import shutil
import os
import re

from scenario.prepare.helper import download, extract
from scenario.helper import progress_bar

TOPDIR = 'busybox-1.38.0'

# options `make randconfig` must not change, each of which made random builds
# fail for reasons unrelated to Kbuild ('y': set, 'n': not set).
PINNED_OPTIONS = {
    'WERROR': 'n',               # GCC warnings in lzop.c, od.c, vi.c, ... become errors
    'TC': 'n',                   # networking/tc.c uses the CBQ API removed from kernel headers
    'SELINUX': 'n',              # needs libselinux, not installed
    'STATIC': 'n',               # needs static libcrypt and libpam, not installed
    'FEATURE_INETD_RPC': 'n',    # includes rpc/rpc.h, removed from glibc
    'FEATURE_MOUNT_NFS': 'n',    # includes rpc/rpc.h, removed from glibc
    'FEATURE_2_4_MODULES': 'n',  # calls query_module/create_module, removed from glibc
    'NOMMU': 'n',                # telnetd.c still calls fork(); link fails
    # DMALLOC and EFENCE are entries of a choice; NO_DEBUG_LIB is the entry kept.
    'NO_DEBUG_LIB': 'y',
    'DMALLOC': 'n',              # links -ldmalloc, not installed
    'EFENCE': 'n',               # links -lefence, not installed
}


def gen_build_files(src):
    # BusyBox ships Kbuild.src and Config.src templates; generate the real
    # Kbuild and Config.in files from them and from //kbuild: and //config: comments.
    subprocess.run(['sh', 'scripts/gen_build_files.sh', '.', '.'], cwd=src, check=True,
                   capture_output=True)


def pin_options(config, options):
    # replace the given options in .config with their fixed values. BusyBox's
    # old kconfig keeps the first value it reads and re-randomizes choices
    # under KCONFIG_ALLCONFIG, so this deletes the old lines first.
    with open(config) as f:
        kept = [line for line in f
                if not (m := re.search(r'CONFIG_(\w+)', line)) or m.group(1) not in options]
    pinned = [f'CONFIG_{name}=y\n' if value == 'y' else f'# CONFIG_{name} is not set\n'
              for name, value in options.items()]
    with open(config, 'w') as f:
        f.writelines(kept + pinned)


def build_random_configs(path, root, n_build, csv_path):
    # each random configuration gets its own copy <i>/ holding its .config and
    # objects. make -k keeps going past files that fail to compile, and the
    # CSV records its return code.
    pbar = progress_bar.create(total=n_build, unit='config', desc='    - `make` random configs',
                               csv_path=csv_path)
    for i in range(n_build):
        # randconfig draws a new configuration on every run, so a rerun starts from a
        # fresh copy; objects of the previous configuration would count as compiled
        if os.path.exists(os.path.join(root, str(i))):
            shutil.rmtree(os.path.join(root, str(i)))
        build = extract(path, root, str(i), TOPDIR)
        subprocess.run(['make', 'randconfig'], cwd=build, check=True,
                       capture_output=True)
        # pin options that break the build for reasons unrelated to Kbuild,
        # then let oldconfig resolve the options that depend on them.
        pin_options(os.path.join(build, '.config'), PINNED_OPTIONS)
        subprocess.run(['make', 'oldconfig'], cwd=build, check=True,
                       stdin=subprocess.DEVNULL, capture_output=True)
        result = subprocess.run(['make', '-k', f'-j{os.cpu_count()}'], cwd=build,
                                capture_output=True)
        pbar.step(returncode=result.returncode)
    pbar.to_csv()


def prepare(args):
    print('[+] preparing busybox:')
    root = os.path.join(args.target_dir, 'busybox')
    os.makedirs(root, exist_ok=True)

    url = 'https://busybox.net/downloads/busybox-1.38.0.tar.bz2'
    sha256 = '34f9ea6ff8636f2c9241153b9114eefa9e65674a45318ae1ef95bb5f31c53bb2'

    print('    - downloading busybox')
    path = os.path.join(root, f'busybox-1.38.0.tar.bz2')
    download(url, path, sha256)

    print('    - extracting src')
    src = extract(path, root, 'src', TOPDIR)

    print('    - generating kbuild files')
    gen_build_files(src)

    build_random_configs(path, root, args.n_build,
                         os.path.join(args.csv_dir, 'prepare_busybox.csv'))
