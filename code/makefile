
all: prepare rq2


prepare:
	python3 -m scenario.prepare --target=busybox --n_build=2
	python3 -m scenario.prepare --target=linux-i386 --n_build=2
	python3 -m scenario.prepare --target=linux-x86_64 --n_build=2
	python3 -m scenario.prepare --target=linux-arm64 --n_build=2
	python3 -m scenario.prepare --target=linux-arm --n_build=2
	python3 -m scenario.prepare --target=barebox --n_build=2
	python3 -m scenario.prepare --target=xen --n_build=2
	for k in $$(seq 20 20 200); do python3 -m scenario.prepare --target=length --n_ifeq=$$k; done
	for k in $$(seq 2 2 20); do python3 -m scenario.prepare --target=nested --n_ifeq=$$k; done
	for k in $$(seq 20 20 200); do python3 -m scenario.prepare --target=value --n_ifeq=$$k; done
	for k in $$(seq 20 20 200); do python3 -m scenario.prepare --target=directory --n_ifeq=$$k; done
	for k in $$(seq 20 20 200); do python3 -m scenario.prepare --target=depth --n_ifeq=$$k; done
	for k in $$(seq 20 20 200); do python3 -m scenario.prepare --target=composite --n_ifeq=$$k; done
	for k in $$(seq 20 20 200); do python3 -m scenario.prepare --target=exported --n_ifeq=$$k; done
	for k in $$(seq 20 20 200); do python3 -m scenario.prepare --target=computed --n_ifeq=$$k; done


main:
	python3 -m scenario.main


rq1:
	python3 -m scenario.exp.rq1_run --tool=tool --n_build=2 --clear
	python3 -m scenario.exp.rq1_run --tool=kmax --n_build=2 --clear
	python3 -m scenario.exp.rq1_run --target=linux-i386 --tool=tool --n_build=2
	python3 -m scenario.exp.rq1_run --target=linux-i386 --tool=kmax --n_build=2
	python3 -m scenario.exp.rq1_run --target=linux-x86_64 --tool=tool --n_build=2
	python3 -m scenario.exp.rq1_run --target=linux-x86_64 --tool=kmax --n_build=2
	python3 -m scenario.exp.rq1_run --target=linux-arm64 --tool=tool --n_build=2
	python3 -m scenario.exp.rq1_run --target=linux-arm64 --tool=kmax --n_build=2
	python3 -m scenario.exp.rq1_run --target=linux-arm --tool=tool --n_build=2 --clear
	python3 -m scenario.exp.rq1_run --target=linux-arm --tool=kmax --n_build=2 --clear
	python3 -m scenario.exp.rq1_run --target=barebox --tool=tool --n_build=2
	python3 -m scenario.exp.rq1_run --target=barebox --tool=kmax --n_build=2
	python3 -m scenario.exp.rq1_run --target=xen --tool=tool --n_build=2 --clear
	python3 -m scenario.exp.rq1_run --target=xen --tool=kmax --n_build=2 --clear
	python3 -m scenario.exp.rq1_plot


rq2:
	python3 -m scenario.exp.rq2_run --target=length --tool=tool --n_ifeq=200 --timeout=60
	python3 -m scenario.exp.rq2_run --target=length --tool=kmax --n_ifeq=200 --timeout=60
	python3 -m scenario.exp.rq2_run --target=nested --tool=tool --n_ifeq=20 --timeout=60
	python3 -m scenario.exp.rq2_run --target=nested --tool=kmax --n_ifeq=20 --timeout=60
	python3 -m scenario.exp.rq2_run --target=value --tool=tool --n_ifeq=200 --timeout=60
	python3 -m scenario.exp.rq2_run --target=value --tool=kmax --n_ifeq=200 --timeout=60
	python3 -m scenario.exp.rq2_run --target=directory --tool=tool --n_ifeq=200 --timeout=60
	python3 -m scenario.exp.rq2_run --target=directory --tool=kmax --n_ifeq=200 --timeout=60
	python3 -m scenario.exp.rq2_run --target=depth --tool=tool --n_ifeq=200 --timeout=60
	python3 -m scenario.exp.rq2_run --target=depth --tool=kmax --n_ifeq=200 --timeout=60
	python3 -m scenario.exp.rq2_run --target=composite --tool=tool --n_ifeq=200 --timeout=60
	python3 -m scenario.exp.rq2_run --target=composite --tool=kmax --n_ifeq=200 --timeout=60
	python3 -m scenario.exp.rq2_run --target=exported --tool=tool --n_ifeq=200 --timeout=60
	python3 -m scenario.exp.rq2_run --target=exported --tool=kmax --n_ifeq=200 --timeout=60
	python3 -m scenario.exp.rq2_run --target=computed --tool=tool --n_ifeq=200 --timeout=60
	python3 -m scenario.exp.rq2_run --target=computed --tool=kmax --n_ifeq=200 --timeout=60
	python3 -m scenario.exp.rq2_plot


rq3:
	# python3 -m scenario.exp.rq3_run --target=linux-i386 --tool=tool --n_build=2
	# python3 -m scenario.exp.rq3_run --target=linux-i386 --tool=kmax --n_build=2
	# python3 -m scenario.exp.rq3_run --target=linux-x86_64 --tool=tool --n_build=2
	python3 -m scenario.exp.rq3_run --target=linux-x86_64 --tool=kmax --n_build=2
	# python3 -m scenario.exp.rq3_run --target=linux-arm64 --tool=tool --n_build=2
	python3 -m scenario.exp.rq3_run --target=linux-arm64 --tool=kmax --n_build=2
	# python3 -m scenario.exp.rq3_run --target=linux-arm --tool=tool --n_build=2
	python3 -m scenario.exp.rq3_run --target=linux-arm --tool=kmax --n_build=2
	python3 -m scenario.exp.rq3_plot
