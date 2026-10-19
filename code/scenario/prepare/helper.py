import urllib.request
import hashlib
import tarfile
import random
import os


def download(url, path, sha256):
    if not os.path.exists(path):
        urllib.request.urlretrieve(url, path)
    with open(path, 'rb') as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    # a release without a published checksum is pinned to the digest of its first download
    if sha256 is None:
        print(f'      sha256 {digest}: record it in the prepare script')
    elif digest != sha256:
        raise SystemExit(f'checksum mismatch for {path}: {digest}')


def extract(path, root, name, topdir):
    # topdir is the directory the tarball unpacks to
    dest = os.path.join(root, name)
    if os.path.exists(dest):
        return dest
    with tarfile.open(path) as tar:
        tar.extractall(root, filter='data')
    os.rename(os.path.join(root, topdir), dest)
    return dest


def read_config(path):
    # {option: value} of a .config in file order, with 'n' for "# CONFIG_X is not set"
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


def perturb(options, seed, pinned, rate):
    # flip a seeded random share `rate` of the Boolean options outside `pinned`,
    # then set the pinned ones
    candidates = [name for name, value in options.items()
                  if value in ('y', 'n') and name not in pinned]
    flipped = random.Random(seed).sample(candidates, round(rate * len(candidates)))
    perturbed = dict(options)
    for name in flipped:
        perturbed[name] = 'n' if options[name] == 'y' else 'y'
    perturbed.update(pinned)
    return perturbed, flipped


def changed(base, final):
    # options whose value differs between two .configs
    return (sum(final.get(name, 'n') != value for name, value in base.items())
            + sum(name not in base and value != 'n' for name, value in final.items()))
