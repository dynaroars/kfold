# Paper example: computed names, a conditional overwrite, ifeq, and a composite
obj-$(CONFIG_NET) += net_core.o
obj-$(CONFIG_FAST) := fast_net.o
ifeq ($(CONFIG_WIDE),y)
  WIDTH := 64
else
  WIDTH := 32
endif
obj-y += driver_$(WIDTH).o
fast_net-y += accelerator.o
