import Skbuild.Logic.Formula

namespace Skbuild.Logic

structure Atom where
  symbol : String
  value : String
  deriving Repr, BEq, DecidableEq, Hashable, Inhabited

inductive Literal where
  | positive (atom : Atom)
  | negative (atom : Atom)
  deriving Repr, BEq, DecidableEq, Hashable, Inhabited

abbrev Clause := List Literal
abbrev CNF := List Clause

def Literal.atom : Literal → Atom
  | .positive atom | .negative atom => atom

def Literal.complement : Literal → Literal
  | .positive atom => .negative atom
  | .negative atom => .positive atom

def Literal.eval (model : Model) : Literal → Bool
  | .positive atom => model atom.symbol == atom.value
  | .negative atom => !(model atom.symbol == atom.value)

@[simp] theorem Literal.complement_complement (literal : Literal) :
    literal.complement.complement = literal := by
  cases literal <;> rfl

@[simp] theorem Literal.eval_complement (literal : Literal) (model : Model) :
    literal.complement.eval model = !(literal.eval model) := by
  cases literal <;> simp [Literal.complement, Literal.eval]

private def Formula.atoms : Formula → List Atom
  | .top | .bottom => []
  | .eq symbol value => [{ symbol, value }]
  | .not body => body.atoms
  | .and left right | .or left right => (left.atoms ++ right.atoms).eraseDups

private def distribute (left right : CNF) : CNF :=
  if left.isEmpty || right.isEmpty then []
  else left.flatMap fun lhs => right.map fun rhs => (lhs ++ rhs).eraseDups

private def Formula.toCNFRaw (formula : Formula) (positive : Bool := true) : CNF :=
  match formula, positive with
  | .top, true | .bottom, false => []
  | .bottom, true | .top, false => [[]]
  | .eq symbol value, true => [[.positive { symbol, value }]]
  | .eq symbol value, false => [[.negative { symbol, value }]]
  | .not body, polarity => body.toCNFRaw !polarity
  | .and left right, true => left.toCNFRaw true ++ right.toCNFRaw true
  | .and left right, false => distribute (left.toCNFRaw false) (right.toCNFRaw false)
  | .or left right, true => distribute (left.toCNFRaw true) (right.toCNFRaw true)
  | .or left right, false => left.toCNFRaw false ++ right.toCNFRaw false

private def atMostOne : List Atom → CNF
  | [] => []
  | atom :: rest =>
      rest.map (fun other => [.negative atom, .negative other]) ++ atMostOne rest

private def domainCNF
    (formula : Formula)
    (domainFor : String → List String) : CNF :=
  formula.symbols.flatMap fun symbol =>
    let values := (domainFor symbol).eraseDups
    let atoms := values.map fun value => ({ symbol, value } : Atom)
    let exactlyOne := [atoms.map Literal.positive] ++ atMostOne atoms
    let invalid := formula.atoms.filterMap fun atom =>
      if atom.symbol == symbol && !values.contains atom.value then
        some [.negative atom]
      else none
    exactlyOne ++ invalid

def Formula.toCNF
    (formula : Formula)
    (domainFor : String → List String) : CNF :=
  formula.toCNFRaw ++ domainCNF formula domainFor

private def simplify (selected : Literal) (cnf : CNF) : CNF :=
  cnf.filterMap fun clause =>
    if clause.contains selected then none
    else some <| clause.filter (· != selected.complement)

private partial def solve : CNF → Bool
  | [] => true
  | cnf =>
      if cnf.any List.isEmpty then false
      else
        let selected :=
          match cnf.find? (fun clause => clause.length == 1) with
          | some [literal] => literal
          | _ => cnf.head!.head!
        solve (simplify selected cnf) || solve (simplify selected.complement cnf)

def CNF.isSatisfiable (cnf : CNF) : Bool := solve cnf

def Formula.isSatisfiable
    (formula : Formula)
    (domainFor : String → List String) : Bool :=
  (formula.toCNF domainFor).isSatisfiable

def Formula.isUnsatisfiable
    (formula : Formula)
    (domainFor : String → List String) : Bool :=
  !formula.isSatisfiable domainFor

end Skbuild.Logic
