tmpdir = "/var/tmp"
logger_level = 3
target_vars = frozenset(["obj-", "lib-"])
ignore_vars = frozenset(["src"])
do_mp = True
mp_task_len = 50  # start parallel processing when having >= mp_task_len
trace_target = "__TRACE__"
sym_prefix = "CONFIG_"

ignore_setvar_startswith = {}
ignore_setvar_endswith = {}
ignore_setvar_kws = {}
detail = False


results_ext = ".kbuild"  # extension of files containing path condition results

# Solver settings

y_str = "y"
m_str = "m"
undef_str = "undef"
undef_val = ''

tristate = (undef_val, "TriState", [y_str, m_str, undef_str], [
            y_str, m_str, undef_val])
twostate = (undef_val, "TwoState", [y_str, undef_str], [y_str, undef_val])

zstate = twostate  # default


# Linux config var that might not be tristate
# CONFIG_EXTRA_FIRMWARE_DIR in /firmware/Makefile
