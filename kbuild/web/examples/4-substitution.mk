# Linux drivers/net/ipa: substitution references build object names from a version list
IPA_VERSIONS := 3.1 3.5.1 4.2 4.5 4.7 4.9 4.11 5.0
obj-$(CONFIG_QCOM_IPA) += ipa.o
ipa-y := ipa_main.o ipa_power.o ipa_reg.o ipa_mem.o
ipa-y += $(IPA_VERSIONS:%=data/ipa_data-v%.o)
ipa-$(CONFIG_FCOE:m=y) += ipa_fcoe_glue.o
