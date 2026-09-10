namespace Skbuild

structure SourcePos where
  offset : Nat := 0
  line : Nat := 1
  column : Nat := 0
  deriving Repr, BEq, DecidableEq

structure SourceSpan where
  file : String
  start : SourcePos
  stop : SourcePos
  deriving Repr, BEq, DecidableEq

def SourceSpan.unknown (file : String := "<unknown>") : SourceSpan :=
  { file := file, start := {}, stop := {} }

end Skbuild
