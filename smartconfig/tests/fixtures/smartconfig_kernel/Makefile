.PHONY: olddefconfig

# A tiny trusted native-config fixture.  It models the important semantic
# edge case for the checker: a disabled parent makes its child ineffective.
olddefconfig:
	@if grep -Eq '^(CONFIG_PARENT=n|# CONFIG_PARENT is not set)' $(O)/.config; then sed -i 's/^CONFIG_CHILD=y/CONFIG_CHILD=n/' $(O)/.config; fi
	@printf 'fixture olddefconfig: %s\n' "$$(pwd)"
