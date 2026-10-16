"""kfold subcommands.

Each module here is a subcommand and must define ``register(subparsers)``,
which adds its parser with ``subparsers.add_parser(NAME, help=...)`` and sets
``func`` (``parser.set_defaults(func=run)``); ``run(args)`` returns an exit
status (None means 0). ``cli.main`` discovers the modules automatically, so
adding a command never requires editing a shared file. Modules whose names
start with ``_`` are skipped.
"""
