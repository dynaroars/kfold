namespace Skbuild.Logic

inductive Formula where
  | top
  | bottom
  | eq (symbol value : String)
  | not (body : Formula)
  | and (left right : Formula)
  | or (left right : Formula)
  deriving Repr, BEq, DecidableEq, Hashable, Inhabited

abbrev Model := String → String

def Formula.eval (model : Model) : Formula → Bool
  | .top => true
  | .bottom => false
  | .eq symbol value => model symbol == value
  | .not body => !(body.eval model)
  | .and left right => left.eval model && right.eval model
  | .or left right => left.eval model || right.eval model

def Formula.neg : Formula → Formula
  | .top => .bottom
  | .bottom => .top
  | .not body => body
  | body => .not body

private partial def Formula.hasConjunct (formula needle : Formula) : Bool :=
  if formula == needle then true
  else match formula with
    | .and left right => left.hasConjunct needle || right.hasConjunct needle
    | _ => false

def Formula.conj : Formula → Formula → Formula
  | .bottom, _ | _, .bottom => .bottom
  | .top, right => right
  | left, .top => left
  | left, right =>
      if left.hasConjunct right then left
      else if right.hasConjunct left then right
      else if left.hasConjunct right.neg || right.hasConjunct left.neg then .bottom
      else .and left right

partial def Formula.disj : Formula → Formula → Formula
  | .top, _ | _, .top => .top
  | .bottom, right => right
  | left, .bottom => left
  | left, right =>
      if left == right then left
      else if left == right.neg || left.neg == right then .top
      else
        match left, right with
        | common, .and first second | .and first second, common =>
            if common == first || common == second then common
            else
              match left, right with
              | .and leftFirst leftSecond, .and rightFirst rightSecond =>
                  if leftFirst == rightFirst then
                    leftFirst.conj (leftSecond.disj rightSecond)
                  else if leftFirst == rightSecond then
                    leftFirst.conj (leftSecond.disj rightFirst)
                  else if leftSecond == rightFirst then
                    leftSecond.conj (leftFirst.disj rightSecond)
                  else if leftSecond == rightSecond then
                    leftSecond.conj (leftFirst.disj rightFirst)
                  else .or left right
              | _, _ => .or left right
        | _, _ => .or left right

def Formula.symbols : Formula → List String
  | .top | .bottom => []
  | .eq symbol _ => [symbol]
  | .not body => body.symbols
  | .and left right | .or left right => (left.symbols ++ right.symbols).eraseDups

def Formula.render : Formula → String
  | .top => "true"
  | .bottom => "false"
  | .eq symbol value => s!"{symbol}={if value.isEmpty then "n" else value}"
  | .not body => s!"!({body.render})"
  | .and left right => s!"({left.render} && {right.render})"
  | .or left right => s!"({left.render} || {right.render})"

private def lookupModel (assignments : List (String × String)) (symbol : String) : String :=
  match assignments.find? (·.1 == symbol) with
  | some (_, value) => value
  | none => ""

private def Formula.search
    (formula : Formula)
    (domainFor : String → List String)
    (symbols : List String)
    (assignments : List (String × String)) : Bool :=
  match symbols with
  | [] => formula.eval (lookupModel assignments)
  | symbol :: rest =>
      (domainFor symbol).any fun value =>
        formula.search domainFor rest ((symbol, value) :: assignments)

def Formula.isSatisfiableExhaustive
    (formula : Formula)
    (domainFor : String → List String) : Bool :=
  formula.search domainFor formula.symbols []

def Formula.isUnsatisfiableExhaustive
    (formula : Formula)
    (domainFor : String → List String) : Bool :=
  !formula.isSatisfiableExhaustive domainFor

def Formula.toNNF (formula : Formula) (positive : Bool := true) : Formula :=
  match formula, positive with
  | .top, true | .bottom, false => .top
  | .bottom, true | .top, false => .bottom
  | .eq symbol value, true => .eq symbol value
  | .eq symbol value, false => .not (.eq symbol value)
  | .not body, polarity => body.toNNF !polarity
  | .and left right, true => .and (left.toNNF true) (right.toNNF true)
  | .and left right, false => .or (left.toNNF false) (right.toNNF false)
  | .or left right, true => .or (left.toNNF true) (right.toNNF true)
  | .or left right, false => .and (left.toNNF false) (right.toNNF false)

@[simp] theorem Formula.eval_toNNF
    (formula : Formula) (model : Model) (positive : Bool) :
    (formula.toNNF positive).eval model =
      if positive then formula.eval model else !(formula.eval model) := by
  induction formula generalizing positive <;> cases positive <;>
    simp_all [Formula.toNNF, Formula.eval]

@[simp] theorem Formula.eval_neg (formula : Formula) (model : Model) :
    formula.neg.eval model = !(formula.eval model) := by
  cases formula <;> simp [Formula.neg, Formula.eval]

end Skbuild.Logic
