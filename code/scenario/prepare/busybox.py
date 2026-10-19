import urllib.request
import subprocess
import hashlib
import tarfile
import os


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
    root = os.path.join(args.target_dir, 'busybox')
    os.makedirs(root, exist_ok=True)

    url = 'https://busybox.net/downloads/busybox-1.38.0.tar.bz2'
    sha256 = '34f9ea6ff8636f2c9241153b9114eefa9e65674a45318ae1ef95bb5f31c53bb2'

    path = os.path.join(root, f'busybox-1.38.0.tar.bz2')
    download(url, path, sha256)

    src = extract(path, root, 'src')

    # BusyBox ships Kbuild.src templates; generate the real Kbuild files.
    subprocess.run(['sh', 'scripts/gen_build_files.sh', '.', '.'], cwd=src, check=True)
