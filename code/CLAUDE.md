# Coding rules

- Do not implement edge cases until they actually happen. Write the straightforward path first; add handling for a case only once a real run (a target project, a test, an error) hits it.
- Order import lines from longest to shortest within each import group (standard library, then project modules).
- Write comments (and replies) directly: state what the code does and why. Do not add reassuring negative statements about what it does not do ("X, not Y", "never touches ...", "nothing else changed").
- Use single quotes (') for strings and docstrings (''').
- Do not write a long comment or docstring at the top of a file unless asked.
- Comments outside function docstrings use `# ...` and start with a lowercase letter (proper nouns and identifiers keep their case).
- Say "path condition" (identifier `path_condition`), never "guard", for the formula under which a word, branch, or directory is present. The same rule holds in the paper.

# Environment and experiments

- The user runs every experiment by hand (`make prepare`, `make rq1`, ...), in their own venv (`~/.local/share/venv`). Do not run experiments, builds, or baselines yourself unless asked.
- Do not edit `makefile` unless asked. When new code needs a new command, give the user the line to add.
- Baselines (`baseline/`, such as Kmax and its klocalizer/krepair) run as their authors wrote them: never fix or change their behavior. The only allowed change is a syntax fix that lets them run on this Python version, applied to a copy by the scenario code (e.g., `PACKAGE_PATCHES` in `scenario/helper/kmax.py`), never to the submodule or the installed package.
- Never create a virtual environment (`.venv`, `python -m venv`, `uv venv`) and never install or uninstall packages. When code needs a new dependency or tool (a pip package, a baseline such as Kmax, a system library), tell the user the exact install command and add it to `requirements.txt` or the README setup.
