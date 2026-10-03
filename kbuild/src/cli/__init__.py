"""kfold command-line interface.

The analyzer's modules (``alg``, ``objects``, ``helpers`` ...) live flat in
``src/`` and import each other by top-level name, and helpers such as
``kconfig_solver`` live in ``tools/``. Importing this package puts both
directories on ``sys.path`` so the CLI works from an editable install, from
``PYTHONPATH=src python3 -m cli``, and under pytest.
"""
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parent.parent
ROOT = SRC.parent
TOOLS = ROOT / "tools"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if TOOLS.is_dir() and str(TOOLS) not in sys.path:
    sys.path.append(str(TOOLS))
