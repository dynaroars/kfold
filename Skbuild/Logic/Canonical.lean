import Skbuild.Logic.Formula

namespace Skbuild.Logic

inductive Decision where
  | leaf (value : Bool)
  | choice (symbol : String) (branches : List (String × Decision))
  deriving Repr, BEq, Inhabited

private def lookupAssignment
    (assignments : List (String × String))
    (symbol : String) : String :=
  match assignments.find? (·.1 == symbol) with
  | some (_, value) => value
  | none => ""

private def collapse (symbol : String) (branches : List (String × Decision)) : Decision :=
  match branches with
  | [] => .leaf false
  | (_, first) :: rest =>
      if rest.all fun (_, decision) => decision == first then first
      else .choice symbol branches

private def buildDecision
    (formula : Formula)
    (domainFor : String → List String)
    (symbols : List String)
    (assignments : List (String × String)) : Decision :=
  match symbols with
  | [] => .leaf <| formula.eval (lookupAssignment assignments)
  | symbol :: rest =>
      collapse symbol <| (domainFor symbol).map fun value =>
        (value, buildDecision formula domainFor rest ((symbol, value) :: assignments))

partial def Decision.toFormula : Decision → Formula
  | .leaf true => .top
  | .leaf false => .bottom
  | .choice symbol branches =>
      branches.foldl (init := Formula.bottom) fun result (value, decision) =>
        let branch := (Formula.eq symbol value).conj decision.toFormula
        result.disj branch

private partial def normalize : Formula → Formula
  | .top => .top
  | .bottom => .bottom
  | .eq symbol value => .eq symbol value
  | .not body => (normalize body).neg
  | .and left right =>
      let lhs := normalize left
      let rhs := normalize right
      match lhs, rhs with
      | .eq leftSymbol leftValue, .eq rightSymbol rightValue =>
          if leftSymbol == rightSymbol && leftValue != rightValue then .bottom
          else if lhs.render <= rhs.render then lhs.conj rhs else rhs.conj lhs
      | _, _ => if lhs.render <= rhs.render then lhs.conj rhs else rhs.conj lhs
  | .or left right =>
      let lhs := normalize left
      let rhs := normalize right
      if lhs.render <= rhs.render then lhs.disj rhs else rhs.disj lhs

def Formula.canonicalize
    (formula : Formula)
    (domainFor : String → List String) : Formula :=
  let symbols := formula.symbols.mergeSort
  let valuations := symbols.foldl (fun count symbol => count * (domainFor symbol).length) 1
  let budget := if symbols.all fun symbol => (domainFor symbol).length <= 2 then 64 else 1
  if valuations <= budget then (buildDecision formula domainFor symbols []).toFormula
  else normalize formula

end Skbuild.Logic
