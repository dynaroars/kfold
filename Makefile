.PHONY: build test corpus-check check clean

build:
	lake build skbuild skbuild_tests

test: build
	.lake/build/bin/skbuild_tests
	sh Tests/e2e.sh

corpus-check: build
	find tests -type f \( -name Makefile -o -name Kbuild \) -print0 | \
		xargs -0 .lake/build/bin/skbuild --tristate --batch-check --json > /dev/null

check: test corpus-check
	git diff --check

clean:
	lake clean
