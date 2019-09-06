obj-y := main.o
obj-$(CONFIG_A) += 1.o
ifeq ($(CONFIG_B),y)
	FILE = 2
else
	FILE = 3
endif
obj-$(CONFIG_C) += $(FILE).o 4.o
ifeq ($(CONFIG_E),y)
obj-y += 5.o
endif
obj-$(CONFIG_F) += 6.o
obj-$(CONFIG_G) += 6.o 7.o
