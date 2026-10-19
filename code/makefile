
all: prepare rq1


prepare:
	python3 -m scenario.prepare --target=busybox
	python3 -m scenario.prepare --target=linux-i386
	python3 -m scenario.prepare --target=linux-x86_64
	python3 -m scenario.prepare --target=linux-arm64
	python3 -m scenario.prepare --target=linux-arm
	python3 -m scenario.prepare --target=uboot
	python3 -m scenario.prepare --target=barebox
	python3 -m scenario.prepare --target=xen


main:
	python3 -m scenario.main


rq1:
	python3 -m scenario.exp.rq1_run --tool=tool
	python3 -m scenario.exp.rq1_run --tool=kmax
	python3 -m scenario.exp.rq1_run --target=linux-i386 --tool=tool
	python3 -m scenario.exp.rq1_run --target=linux-i386 --tool=kmax
	python3 -m scenario.exp.rq1_run --target=linux-x86_64 --tool=tool
	python3 -m scenario.exp.rq1_run --target=linux-x86_64 --tool=kmax
	python3 -m scenario.exp.rq1_run --target=linux-arm64 --tool=tool
	python3 -m scenario.exp.rq1_run --target=linux-arm64 --tool=kmax
	python3 -m scenario.exp.rq1_run --target=linux-arm --tool=tool
	python3 -m scenario.exp.rq1_run --target=linux-arm --tool=kmax
	python3 -m scenario.exp.rq1_run --target=uboot --tool=tool
	python3 -m scenario.exp.rq1_run --target=uboot --tool=kmax
	python3 -m scenario.exp.rq1_run --target=barebox --tool=tool
	python3 -m scenario.exp.rq1_run --target=barebox --tool=kmax
	python3 -m scenario.exp.rq1_run --target=xen --tool=tool
	python3 -m scenario.exp.rq1_run --target=xen --tool=kmax
	python3 -m scenario.exp.rq1_plot
