"""``python3 -m cli`` (with ``src`` on PYTHONPATH) runs the kfold CLI."""
import sys

from cli.main import main

sys.exit(main())
