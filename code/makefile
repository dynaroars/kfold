
all: prepare rq1


prepare:
	# python3 -m scenario.prepare --target=busybox
	python3 -m scenario.prepare --target=linux_tinyconfig


main:
	python3 -m scenario.main


rq1:
	# python3 -m scenario.exp.rq1_run --tool=tool
	# python3 -m scenario.exp.rq1_run --tool=kmax
	# python3 -m scenario.exp.rq1_plot
	python3 -m scenario.exp.rq1_run --target=linux_tinyconfig --tool=tool
	python3 -m scenario.exp.rq1_run --target=linux_tinyconfig --tool=kmax
	python3 -m scenario.exp.rq1_plot
