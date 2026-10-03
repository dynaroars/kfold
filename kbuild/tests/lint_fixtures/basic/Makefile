obj-$(CONFIG_FOO) += foo.o
obj-$(CONFIG_BAR_ZOMBIE) += bar.o
obj-y += baz.o

# Nested contradiction: CONFIG_FOO == y AND CONFIG_FOO == undef -> UNSAT
# under Kbuild alone (a "kbuild"-class dead object).
ifeq ($(CONFIG_FOO),y)
ifeq ($(CONFIG_FOO),)
obj-y += kbdead.o
endif
endif

# Satisfiable under Kbuild alone, but Kconfig forces CONFIG_DEAD off (a
# "kconfig"-class dead object).
obj-$(CONFIG_DEAD) += dead.o
