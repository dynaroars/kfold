import glob
import os
import re
import sys
import shutil
import subprocess

import pytest

this_dir = os.path.dirname(__file__)
make_pattern = os.path.join(this_dir, "*.mk")
makes = glob.glob(make_pattern)
tmpdir = "_mktemp"
pymake = os.path.join(
    os.path.dirname(this_dir), "make.py"
)

tre = re.compile('^#T (gmake |pymake )?([a-z-]+)(?:: (.*))?$')

def make_metadata(make):
    options = {
        "returncode": 0,
        "grepfor": None,
        "env": os.environ.copy(),
        "pass": True,
        "skip": False,
        "commandline": [],
    }
    with open(make) as h:
        lines = h.readlines()
    for line in  lines:
        match = tre.search(line)
        if not match:
            break

        make, key, data = match.group(1, 2, 3)
        if data is not None:
            data = eval(data)
        if key == 'commandline':
            assert make is None
            options['commandline'].extend(data)
        elif key == 'returncode':
            options['returncode'] = data
        elif key == 'returncode-on':
            if sys.platform in data:
                options['returncode'] = data[sys.platform]
        elif key == 'environment':
            for k, v in data.items():
                options['env'][k] = v
        elif key == 'grep-for':
            options['grepfor'] = data
        elif key == 'fail':
            options['pass'] = False
        elif key == 'skip':
            options['skip'] = True
        else:
            sys.stderr.write("%s: Unexpected #T key: %s\n" % (makefile, key))
            assert False
    return options

def check_text(text, check):
    for line in text.split("\n"):
        if check in line and "echo" not in line:
            return True
    return False


@pytest.mark.parametrize("make", makes)
def test_make(make, capfd):
    if os.path.exists(tmpdir):
        shutil.rmtree(tmpdir)
    assert os.path.exists(tmpdir) is False
    os.mkdir(tmpdir, 0o755)

    commands = [
        "-C", tmpdir, "-f", os.path.abspath(make),
        "TESTPATH={}".format(this_dir.replace("\\", "/")),
        "NATIVE_TESTPATH={}".format(this_dir),
    ]
    options = make_metadata(make)
    full_commands = [sys.executable, pymake] + commands
    full_commands.extend(options["commandline"])
    run = subprocess.Popen(full_commands, env=options["env"])
    code = run.wait()
    stdout, stderr = capfd.readouterr()
    print(stdout)
    print("----- STDERR -----")
    print(stderr)
    merged = stdout + stderr    

    assert code == options["returncode"]
    assert check_text(merged, "TEST-FAIL") is False
    grepfor = options["grepfor"]
    if grepfor:
        assert grepfor in merged
    if code == 0:
        assert check_text(merged, "TEST-PASS")


