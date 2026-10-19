
all: prepare rq1


prepare:
	python3 -m scenario.prepare --target=busybox --n_build=2
	python3 -m scenario.prepare --target=linux-i386 --n_build=2
	python3 -m scenario.prepare --target=linux-x86_64 --n_build=2
	python3 -m scenario.prepare --target=linux-arm64 --n_build=2
	python3 -m scenario.prepare --target=linux-arm --n_build=2
	python3 -m scenario.prepare --target=uboot --n_build=2
	python3 -m scenario.prepare --target=barebox --n_build=2
	python3 -m scenario.prepare --target=xen --n_build=2


main:
	python3 -m scenario.main


rq1:
	python3 -m scenario.exp.rq1_run --tool=tool --n_build=2
	python3 -m scenario.exp.rq1_run --tool=kmax --n_build=2
	python3 -m scenario.exp.rq1_run --target=linux-i386 --tool=tool --n_build=2
	python3 -m scenario.exp.rq1_run --target=linux-i386 --tool=kmax --n_build=2
	python3 -m scenario.exp.rq1_run --target=linux-x86_64 --tool=tool --n_build=2
	python3 -m scenario.exp.rq1_run --target=linux-x86_64 --tool=kmax --n_build=2
	python3 -m scenario.exp.rq1_run --target=linux-arm64 --tool=tool --n_build=2
	python3 -m scenario.exp.rq1_run --target=linux-arm64 --tool=kmax --n_build=2
	python3 -m scenario.exp.rq1_run --target=linux-arm --tool=tool --n_build=2
	python3 -m scenario.exp.rq1_run --target=linux-arm --tool=kmax --n_build=2
	python3 -m scenario.exp.rq1_run --target=uboot --tool=tool --n_build=2
	python3 -m scenario.exp.rq1_run --target=uboot --tool=kmax --n_build=2
	python3 -m scenario.exp.rq1_run --target=barebox --tool=tool --n_build=2
	python3 -m scenario.exp.rq1_run --target=barebox --tool=kmax --n_build=2
	python3 -m scenario.exp.rq1_run --target=xen --tool=tool --n_build=2
	python3 -m scenario.exp.rq1_run --target=xen --tool=kmax --n_build=2
	python3 -m scenario.exp.rq1_plot
