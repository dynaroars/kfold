obj-y := fork.o a.o

NOTUSED := unused1.o  #ignore, ....

ifeq ($(CONFIG_A),y)
  BITS := 32
else
  BITS := 64
endif
obj-y += probe$(BITS).o

#obj-y += scan.o   #safe, doesn't depend on any vars expansion  (topdir, hash(stmt)) -> Var(...)

# NOTUSED-$(CONFIG_A) := obj-y   #ignore ..



# obj-*   (e.g., obj-y,  obj-m)
# lib-*   (e.g., lib-y, lib-m)



