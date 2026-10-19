.PHONY: all check test busybox-check clean

all: check

check: test busybox-check

test:
	KFOLD_CACHE=work/kfold-cache python3 -m pytest -q

busybox-check:
	PYTHONPATH=src python3 src/skbuild.py tests/busybox/Makfiles_only/busybox_orig --rmtmp

clean:
	find src -name '__pycache__' -type d -exec rm -rf {} +
