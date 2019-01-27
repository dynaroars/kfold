logger_level = 3
target_vars = frozenset(["obj-", "lib-"])
ignore_vars = frozenset(["src"])
do_mp = True
mp_task_len = 50  # start parallel processing when having >= mp_task_len
trace_target = "__TRACE__"
sym_prefix = "CONFIG_"
