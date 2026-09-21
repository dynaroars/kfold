.PHONY: test busybox-check clean

test:
	PYTHONPATH=src python3 src/skbuild.py tests/paper_example/Makefile --rmtmp

busybox-check:
	PYTHONPATH=src python3 src/skbuild.py tests/busybox/Makfiles_only/busybox_orig --rmtmp

clean:
	find src -name '__pycache__' -type d -exec rm -rf {} +
