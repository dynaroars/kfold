.PHONY: all check test busybox-check clean

all: check

check: test busybox-check

test:
	PYTHONPATH=src python3 src/skbuild.py tests/paper_example/Makefile --rmtmp

busybox-check:
	PYTHONPATH=src python3 src/skbuild.py tests/busybox/Makfiles_only/busybox_orig --rmtmp

clean:
	find src -name '__pycache__' -type d -exec rm -rf {} +
