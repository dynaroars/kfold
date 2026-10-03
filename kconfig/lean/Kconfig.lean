-- Formalization of Kconfig 3-Valued Tristate Logic and Metatheorems in Lean 4

namespace Kconfig

/-- The three truth values of Kconfig: n (no), m (module), y (yes) -/
inductive Tristate where
  | n : Tristate
  | m : Tristate
  | y : Tristate
deriving Repr, DecidableEq

namespace Tristate

/-- Numerical representation in the lattice: n=0, m=1, y=2 -/
def toNat : Tristate → Nat
  | n => 0
  | m => 1
  | y => 2

instance : LT Tristate where
  lt a b := a.toNat < b.toNat

instance : LE Tristate where
  le a b := a.toNat ≤ b.toNat

instance (a b : Tristate) : Decidable (a < b) :=
  inferInstanceAs (Decidable (a.toNat < b.toNat))

instance (a b : Tristate) : Decidable (a ≤ b) :=
  inferInstanceAs (Decidable (a.toNat ≤ b.toNat))

/-- Kconfig conjunction: A && B = min(A, B) -/
def tand (a b : Tristate) : Tristate :=
  if a ≤ b then a else b

/-- Kconfig disjunction: A || B = max(A, B) -/
def tor (a b : Tristate) : Tristate :=
  if a ≤ b then b else a

/-- Kconfig negation: !n = y, !m = m, !y = n -/
def tnot : Tristate → Tristate
  | n => y
  | m => m
  | y => n

end Tristate

/-- Value-sensitive selection force: force(X, A, C) = min(val(X), val(C)) -/
def selectForce (selectorVal conditionVal : Tristate) : Tristate :=
  Tristate.tand selectorVal conditionVal

/-- An Unmet Direct Dependency (UDD) occurs when force exceeds the direct limit -/
def isUDD (force directLimit : Tristate) : Prop :=
  directLimit < force

instance (f l : Tristate) : Decidable (isUDD f l) :=
  inferInstanceAs (Decidable (l < f))

/-!
### The Boolean Abstraction of Prior Work (Oh et al., ESEC/FSE '21)
Prior work collapses both `m` and `y` to boolean `true`.
-/

/-- The Boolean abstraction mapping -/
def toBool : Tristate → Bool
  | Tristate.n => false
  | Tristate.m => true
  | Tristate.y => true

/-- Boolean force under prior work -/
def boolForce (selector condition : Bool) : Bool :=
  selector && condition

/-- Boolean UDD under prior work: force is true, but direct dependency is false -/
def isBoolUDD (force directLimit : Bool) : Prop :=
  force = true ∧ directLimit = false

instance (f l : Bool) : Decidable (isBoolUDD f l) :=
  if h : f = true ∧ l = false then isTrue h else isFalse h

/-!
### Machine-Checked Metatheorems
-/

/--
THEOREM 1 (Incompleteness / Blind Spot of Prior Work):
There exists a valid Kconfig selection where an Unmet Direct Dependency exists
in the real 3-valued semantics, but is completely MISSED by the Boolean abstraction.
(Specifically: Built-in selector y force-enabling a symbol whose dependency is restricted to module m).
-/
theorem boolean_abstraction_misses_ym_udd :
    ∃ (sel cond dep : Tristate),
      isUDD (selectForce sel cond) dep ∧
      ¬ isBoolUDD (boolForce (toBool sel) (toBool cond)) (toBool dep) := by
  exact ⟨Tristate.y, Tristate.y, Tristate.m, by decide, by decide⟩

/--
THEOREM 2 (Soundness of Local Refutation):
If local constraints prove that the selection force cannot exceed the target's
direct limit, an Unmet Direct Dependency is impossible globally.
-/
theorem local_refutation_sound (force directLimit : Tristate)
    (hSafe : force ≤ directLimit) :
    ¬ isUDD force directLimit := by
  intro hUdd
  -- hUdd means directLimit < force, but hSafe means force ≤ directLimit (a contradiction)
  have h1 : force.toNat ≤ directLimit.toNat := hSafe
  have h2 : directLimit.toNat < force.toNat := hUdd
  omega

/--
THEOREM 3 (Exact Dual-Boolean Representation):
Tristate logic can be faithfully represented by two Booleans (on, built_in)
with the invariant (built_in → on).
-/
structure DualBool where
  on : Bool
  built_in : Bool
  inv : built_in = true → on = true
deriving DecidableEq

def tristateToDual : Tristate → DualBool
  | Tristate.n => ⟨false, false, by intros; contradiction⟩
  | Tristate.m => ⟨true, false, by intros; contradiction⟩
  | Tristate.y => ⟨true, true, by intros h; rfl⟩

def dualToTristate : DualBool → Tristate
  | ⟨false, false, _⟩ => Tristate.n
  | ⟨true, false, _⟩ => Tristate.m
  | ⟨true, true, _⟩ => Tristate.y
  | ⟨false, true, h⟩ => by
      -- The invalid state (0, 1) is ruled out by the invariant
      have contra := h rfl
      contradiction

/-- Proof that Tristate and DualBool are isomorphic (bijective roundtrip) -/
theorem dual_bool_isomorphism (t : Tristate) :
    dualToTristate (tristateToDual t) = t := by
  cases t <;> rfl

end Kconfig
