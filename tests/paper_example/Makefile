obj-$(CONFIG_A) := fork.o a.o

NOTUSED := unused1.o  #ignore, ....
obj-y += probe$(CONFIG_B).o

ifeq ($(CONFIG_A),y)
	BITS := 32
	BITS_UNUSED := 1
	ifeq ($(CONFIG_B),y)
		BITS_UNUSED := 0
	endif
else
	BITS := 64
endif
mytest-$(CONFIG_C) += a.o b.o
obj-y += probe$(BITS).o
obj-y += mytest-$(TESTTEST)

obj-y += scan.o   #safe, doesn't depend on any vars expansion  (topdir, hash(stmt)) -> Var(...)

NOTUSED-$(CONFIG_A) := obj-y   #ignore ..



# obj-*   (e.g., obj-y,  obj-m)
# lib-*   (e.g., lib-y, lib-m)



