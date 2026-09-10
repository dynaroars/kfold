import Skbuild.Config
import Skbuild.Logic.Formula
import Skbuild.Syntax

namespace Skbuild

open Logic

inductive Flavor
  | recursive
  | simple
  deriving Repr, BEq, DecidableEq

structure Variable where
  flavor : Flavor
  value : Expr
  deriving Repr, BEq

abbrev Environment := List (String × Variable)

def Environment.get? (environment : Environment) (name : String) : Option Variable :=
  (environment.find? (·.1 == name)).map (·.2)

def Environment.contains (environment : Environment) (name : String) : Bool :=
  environment.any (·.1 == name)

def Environment.set (environment : Environment) (name : String) (value : Variable) : Environment :=
  (name, value) :: environment.filter (·.1 != name)

structure SymPath where
  condition : Formula := .top
  environment : Environment := []
  deriving Repr, BEq, Inhabited

structure Guarded (α : Type) where
  value : α
  condition : Formula
  deriving Repr, BEq

abbrev GuardedString := Guarded String

structure TargetContribution where
  name : String
  value : String
  condition : Formula
  deriving Repr, BEq, Inhabited

structure ContributionMask where
  name : String
  condition : Formula
  deriving Repr, BEq, Inhabited

end Skbuild
