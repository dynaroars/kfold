# Linux arch/x86/entry/vdso: objects built only as rule prerequisites of a selected object
VDSO64-$(CONFIG_X86_64) := y
vobjs-y := vdso-note.o vclock_gettime.o vgetcpu.o
vobjs-$(CONFIG_X86_SGX) += vsgx.o
vobjs := $(foreach F,$(vobjs-y),$(obj)/$F)
vdso_img-$(VDSO64-y) += 64
obj-y += $(vdso_img-y:%=vdso-image-%.o)
$(obj)/vdso64.so.dbg: $(obj)/vdso.lds $(vobjs) FORCE
$(obj)/vdso-image-%.c: $(obj)/vdso%.so.dbg FORCE
