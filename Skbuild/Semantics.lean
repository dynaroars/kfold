import Skbuild.Diagnostic
import Skbuild.Dependency
import Skbuild.Expansion
import Skbuild.Logic.CNF
import Skbuild.Validate

namespace Skbuild

open Logic

structure Execution where
  paths : Array SymPath
  targetContributions : Array TargetContribution := #[]
  contributionMasks : Array ContributionMask := #[]
  handledEvalSpans : Array SourceSpan := #[]
  handledEvalExpressions : Array Expr := #[]
  diagnostics : Array Diagnostic := #[]
  deriving Repr, Inhabited

private def domainFor (settings : Settings) (symbol : String) : List String :=
  (settings.domainFor symbol).values

def feasible (settings : Settings) (formula : Formula) : Bool :=
  formula.isSatisfiable (domainFor settings)

def applyContributionMasks
    (contributions : Array TargetContribution)
    (masks : Array ContributionMask) : Array TargetContribution :=
  masks.foldl (init := contributions) fun current mask =>
    current.filterMap fun contribution =>
      if contribution.name != mask.name then some contribution
      else
        let condition := contribution.condition.conj mask.condition.neg
        if condition == Formula.bottom then none else some { contribution with condition }

private def appendExpr (left right : Expr) : Expr :=
  .concat #[left, .literal " ", right]

private def setAssignment
    (settings : Settings)
    (path : SymPath)
    (name : String)
    (operator : AssignOp)
    (value : Expr) : Array SymPath :=
  match operator with
  | .recursive => #[{ path with environment := path.environment.set name ⟨.recursive, value⟩ }]
  | .simple | .simplePosix =>
      (expandText settings path.environment value).filterMap fun guarded =>
        let condition := path.condition.conj guarded.condition
        if feasible settings condition then
          some { condition, environment := path.environment.set name ⟨.simple, .literal guarded.value⟩ }
        else none
  | .conditional =>
      if path.environment.contains name then #[path]
      else #[{ path with environment := path.environment.set name ⟨.recursive, value⟩ }]
  | .append =>
      match path.environment.get? name with
      | none => #[{ path with environment := path.environment.set name ⟨.recursive, value⟩ }]
      | some stored =>
          match stored.flavor with
          | .recursive =>
              let combined := appendExpr stored.value value
              #[{ path with environment := path.environment.set name ⟨.recursive, combined⟩ }]
          | .simple =>
              (expandText settings path.environment value).filterMap fun guarded =>
                let condition := path.condition.conj guarded.condition
                if feasible settings condition then
                  let combined := appendExpr stored.value (.literal guarded.value)
                  some { condition, environment := path.environment.set name ⟨.simple, combined⟩ }
                else none

private def executeAssignment
    (settings : Settings)
    (paths : Array SymPath)
    (name : Expr)
    (operator : AssignOp)
    (value : Expr)
    (target : Option Expr)
    (span : SourceSpan)
    (streamTargets : Bool)
    (knownContributions : Array TargetContribution) : Execution :=
  if target.isSome then
    { paths, diagnostics := #[{
        code := "SKB1001"
        severity := .warning
        message := "target-specific assignment is not implemented"
        span
        makesIncomplete := true
      }] }
  else
    let inputsAvailable := value.references.all fun reference =>
      paths.all (fun path => path.environment.contains reference) ||
        knownContributions.any (·.name == reference) || settings.isSymbol reference
    let expandedNames := paths.flatMap fun path =>
      expandTextWithContributions settings path.environment knownContributions name
    let freshNames := expandedNames.all fun guardedName =>
      !knownContributions.any (·.name == guardedName.value) &&
        paths.all fun path => !path.environment.contains guardedName.value
    let supportedFirstWrite := operator == .recursive || operator == .simple ||
      operator == .simplePosix || operator == .conditional
    let directTarget := expandedNames.all fun guardedName => settings.isTarget guardedName.value
    let regularStream := streamTargets && name.isBuildListName settings && inputsAvailable &&
        (operator == .append || (supportedFirstWrite && freshNames && directTarget))
    let guardedOverwrite := streamTargets && name.isBuildListName settings && inputsAvailable &&
      name.staticText?.isNone &&
        (name.leadingLiteral?.any settings.streamedOverwritePrefixes.contains || name.references.length > 1) &&
        supportedFirstWrite && operator != .conditional
    let streamAssignment := regularStream || guardedOverwrite
    let masks : Array ContributionMask := if guardedOverwrite then
      paths.flatMap fun path =>
        (expandTextWithContributions settings path.environment knownContributions name).filterMap
          fun guardedName =>
            if guardedName.value.isEmpty then none
            else some {
              name := guardedName.value
              condition := path.condition.conj guardedName.condition
            }
    else #[]
    let contributions := if streamAssignment then
      paths.flatMap fun path =>
        (expandTextWithContributions settings path.environment knownContributions name).flatMap fun guardedName =>
          if guardedName.value.isEmpty then #[]
          else
            (expandTextWithContributions settings path.environment knownContributions value).map fun guardedValue => {
              name := guardedName.value
              value := guardedValue.value
              condition := path.condition.conj guardedName.condition |>.conj guardedValue.condition
            }
    else #[]
    if streamAssignment then
      { paths, targetContributions := contributions, contributionMasks := masks }
    else { paths := paths.flatMap fun path =>
        (expandText settings path.environment name).flatMap fun guardedName =>
          let condition := path.condition.conj guardedName.condition
          if feasible settings condition then
            setAssignment settings { path with condition } guardedName.value operator value
          else #[] }

private def equalCondition
    (settings : Settings)
    (path : SymPath)
    (left right : Expr)
    (contributions : Array TargetContribution := #[]) : Formula :=
  let leftValues := expandTextWithContributions settings path.environment contributions left
  let rightValues := expandTextWithContributions settings path.environment contributions right
  let equalities := leftValues.flatMap fun lhs =>
    rightValues.filterMap fun rhs =>
      if lhs.value == rhs.value then some (lhs.condition.conj rhs.condition) else none
  equalities.foldl Formula.disj .bottom

def conditionFormula
    (settings : Settings)
    (path : SymPath)
    (contributions : Array TargetContribution := #[]) : Condition → Formula
  | .equals left right expected =>
      let formula := equalCondition settings path left right contributions
      if expected then formula else formula.neg
  | .defined nameExpression expected =>
      let names := expandTextWithContributions settings path.environment contributions nameExpression
      let defined := names.foldl (init := Formula.bottom) fun formula guarded =>
        let name := guarded.value
        let valueCondition :=
          match path.environment.get? name with
          | some stored =>
              (expandTextWithContributions settings path.environment contributions stored.value).foldl
                (init := Formula.bottom) fun result value =>
                  if value.value.isEmpty then result else result.disj value.condition
          | none =>
              if settings.isSymbol name then
                (settings.domainFor name).values.foldl (init := Formula.bottom) fun result value =>
                  if value.isEmpty then result else result.disj (.eq name value)
              else .bottom
        formula.disj (guarded.condition.conj valueCondition)
      if expected then defined else defined.neg
  | .otherwise => .top

def mergePaths (paths : Array SymPath) : Array SymPath := Id.run do
  let mut output : Array SymPath := #[]
  for path in paths do
    match output.findIdx? (·.environment == path.environment) with
    | some index =>
        let existing := output[index]!
        output := output.set! index { existing with
          condition := existing.condition.disj path.condition
        }
    | none => output := output.push path
  return output

def mergeTargetContributions
    (contributions : Array TargetContribution) : Array TargetContribution := Id.run do
  let mut output : Array TargetContribution := #[]
  for contribution in contributions do
    match output.findIdx? fun prior =>
        prior.name == contribution.name && prior.value == contribution.value with
    | some index =>
        let prior := output[index]!
        output := output.set! index { prior with
          condition := prior.condition.disj contribution.condition
        }
    | none => output := output.push contribution
  return output

mutual
  partial def executeStatements
      (settings : Settings)
      (statements : Array Statement)
      (initialPaths : Array SymPath)
      (streamTargets : Bool := false)
      (knownContributions : Array TargetContribution := #[]) : Execution :=
    let (_, result) := statements.foldl
        (init := (knownContributions, ({ paths := initialPaths } : Execution)))
        fun (maskedKnown, execution) statement =>
      let next := executeStatement settings statement execution.paths streamTargets
        (maskedKnown ++ execution.targetContributions)
      (applyContributionMasks maskedKnown next.contributionMasks, {
        paths := mergePaths next.paths
        targetContributions := applyContributionMasks execution.targetContributions
            next.contributionMasks ++ next.targetContributions
        contributionMasks := execution.contributionMasks ++ next.contributionMasks
        diagnostics := execution.diagnostics ++ next.diagnostics })
    result

  partial def executeStatement
      (settings : Settings)
      (statement : Statement)
      (paths : Array SymPath)
      (streamTargets : Bool := false)
      (knownContributions : Array TargetContribution := #[]) : Execution :=
    match statement with
    | .assignment name operator value target span =>
        executeAssignment settings paths name operator value target span streamTargets knownContributions
    | .conditional branches _ =>
        let result := paths.foldl (init := ({ paths := #[] } : Execution)) fun total path =>
          let (remaining, branchResult) := branches.foldl
            (init := (Formula.top, ({ paths := #[] } : Execution))) fun (remaining, accumulated) branch =>
              let branchFormula := match branch.condition with
                | .otherwise => remaining
                | condition => remaining.conj (conditionFormula settings path knownContributions condition)
              let condition := path.condition.conj branchFormula
              let branchExecution :=
                if feasible settings condition then
                  executeStatements settings branch.statements #[{ path with condition }] streamTargets
                    knownContributions
                else ({ paths := #[] } : Execution)
              let nextRemaining := match branch.condition with
                | .otherwise => Formula.bottom
                | condition => remaining.conj (conditionFormula settings path knownContributions condition).neg
              (nextRemaining, ({
                paths := accumulated.paths ++ branchExecution.paths
                targetContributions := accumulated.targetContributions ++ branchExecution.targetContributions
                contributionMasks := accumulated.contributionMasks ++ branchExecution.contributionMasks
                diagnostics := accumulated.diagnostics ++ branchExecution.diagnostics
              } : Execution))
          let residualCondition := path.condition.conj remaining
          let residualPaths :=
            if feasible settings residualCondition then #[{ path with condition := residualCondition }]
            else #[]
          ({ paths := total.paths ++ branchResult.paths ++ residualPaths
             targetContributions := total.targetContributions ++ branchResult.targetContributions
             contributionMasks := total.contributionMasks ++ branchResult.contributionMasks
             diagnostics := total.diagnostics ++ branchResult.diagnostics } : Execution)
        { result with paths := mergePaths result.paths }
    | .include _ _ span =>
        { paths, diagnostics := #[{
            code := "SKB1002"
            severity := .warning
            message := "include execution is not implemented in the JSON bootstrap"
            span
            makesIncomplete := true
          }] }
    | .rule _ _ | .command _ _ | .expression _ _ => { paths }
end

def executeMakefile (settings : Settings) (makefile : Makefile) : Execution :=
  let settings := settings.forMakefile makefile
  let reduced := reduceMakefile settings makefile
  let execution := executeStatements settings reduced.statements #[{}]
    (reduced.canStreamTargets settings)
  { execution with
    targetContributions := mergeTargetContributions execution.targetContributions
    diagnostics := validateMakefile reduced ++ execution.diagnostics }

end Skbuild
