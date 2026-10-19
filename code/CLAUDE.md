# Coding rules

- Do not implement edge cases until they actually happen. Write the straightforward path first; add handling for a case only once a real run (a target project, a test, an error) hits it.
- Order import lines from longest to shortest within each import group (standard library, then project modules).
- Write comments (and replies) directly: state what the code does and why. Do not add reassuring negative statements about what it does not do ("X, not Y", "never touches ...", "nothing else changed").
- Use single quotes (') for strings and docstrings (''').
- Do not write a long comment or docstring at the top of a file unless asked.
- Comments outside function docstrings use `# ...` and start with a lowercase letter (proper nouns and identifiers keep their case).
