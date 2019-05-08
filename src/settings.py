import pathlib
tmpdir = pathlib.Path("/var/tmp")
logger_level = 3
do_mp = True
mp_task_len = 50  # parallel processing when >= mp_task_len
detail = False

target_vars = frozenset(["obj-", "lib-"])
ignore_vars = frozenset(["src"])

sym_prefix = "CONFIG_"
results_ext = ".kbuild"  # extensions of result files

# Linux config var that might not be tristate
# CONFIG_EXTRA_FIRMWARE_DIR in /firmware/Makefile
