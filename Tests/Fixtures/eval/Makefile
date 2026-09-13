# Generated assignments execute at the point where eval appears.
parts-y := first.o
$(eval parts-y += second.o)
obj-y += $(parts-y)

ifeq ($(CONFIG_EXTRA),y)
  $(eval parts-y += guarded.o)
endif
obj-y += $(parts-y)

define add_macro
$(eval obj-y += macro.o)
endef
$(if $(CONFIG_EXTRA),$(eval obj-y += if.o))
prefix$(eval obj-y += concat.o)
$(call add_macro)
