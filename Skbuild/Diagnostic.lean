import Skbuild.Source

namespace Skbuild

inductive Severity
  | info
  | warning
  | error
  deriving Repr, BEq, DecidableEq

structure Diagnostic where
  code : String
  severity : Severity
  message : String
  span : SourceSpan
  makesIncomplete : Bool := false
  deriving Repr, BEq, DecidableEq

inductive Completeness
  | complete
  | incomplete (reasons : Array Diagnostic)
  deriving Repr, BEq

end Skbuild
