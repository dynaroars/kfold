import Lake
open Lake DSL

package «kconfig» where
  -- add package configuration options here

@[default_target]
lean_lib «Kconfig» where
  srcDir := "lean"
