
tmpdir = "/var/tmp"
logger_level = 3
do_mp = True
mp_task_len = 50  # start parallel processing when having >= mp_task_len
detail = False

target_vars = frozenset(["obj-", "lib-"])
ignore_vars = frozenset(["src"])

sym_prefix = "CONFIG_"

results_ext = ".kbuild"  # extension of files containing path condition results


# # Specific settings for case study (e.g., Linux, Busybox)
# ignore_setvar_startswith = frozenset()
# ignore_setvar_endswith = frozenset()
# ignore_setvar_kws = frozenset()

# ## ignore files for analysis
# ignore_dirs = frozenset()
# ignore_exts = frozenset()


# Linux config var that might not be tristate
# CONFIG_EXTRA_FIRMWARE_DIR in /firmware/Makefile


