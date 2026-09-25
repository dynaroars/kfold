# Linux drivers/xen: += on an undefined variable is deferred, so a later definition counts
dom0-$(CONFIG_PCI) += pci.o
dom0-$(CONFIG_XEN_ACPI) += acpi.o $(xen-pad-y)
xen-pad-$(CONFIG_X86) += xen-acpi-pad.o
dom0-$(CONFIG_X86) += pcpu.o
obj-$(CONFIG_XEN_DOM0) += $(dom0-y)
obj-$(CONFIG_XEN_BALLOON) += xen-balloon.o
