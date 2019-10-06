obj-y := fork.o a.o

ifeq ($(CONFIG_A),y)
  ifeq ($(CONFIG_C),y)
    ABITS := 128
  endif
  BITS := 32
else
  BITS := 64
endif
obj-$(CONFIG_B) += probe_$(BITS).o


# obj-*   (e.g., obj-y,  obj-m)
# lib-*   (e.g., lib-y, lib-m)



