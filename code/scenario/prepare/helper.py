import urllib.request
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


def extract(path, root, name, topdir):
    # topdir is the directory the tarball unpacks to
    dest = os.path.join(root, name)
    if os.path.exists(dest):
        return dest
    with tarfile.open(path) as tar:
        tar.extractall(root, filter='data')
    os.rename(os.path.join(root, topdir), dest)
    return dest
