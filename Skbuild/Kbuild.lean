import Skbuild.Parser
import Skbuild.Dependency
import Skbuild.Semantics
import Skbuild.Path

namespace Skbuild

open Logic

private def words (value : String) : List String :=
  value.split Char.isWhitespace |>.map String.Slice.toString |>.toList |>.filter (not ∘ String.isEmpty)

private def appendExecution (left right : Execution) : Execution :=
  { paths := left.paths ++ right.paths
    targetContributions := left.targetContributions ++ right.targetContributions
    contributionMasks := left.contributionMasks ++ right.contributionMasks
    handledEvalSpans := left.handledEvalSpans ++ right.handledEvalSpans
    handledEvalExpressions := left.handledEvalExpressions ++ right.handledEvalExpressions
    diagnostics := left.diagnostics ++ right.diagnostics }

private def diagnostic
    (code message : String)
    (span : SourceSpan)
    (incomplete : Bool := true) : Diagnostic :=
  { code, severity := .warning, message, span, makesIncomplete := incomplete }

private partial def exprContainsEval : Expr → Bool
  | .literal _ => false
  | .variable name => exprContainsEval name
  | .function fn args => fn == .eval || args.any exprContainsEval
  | .concat parts => parts.any exprContainsEval

private def suppressHandledEvalDiagnostics
    (statements : Array Statement)
    (handled : Array SourceSpan)
    (handledExpressions : Array Expr)
    (diagnostics : Array Diagnostic) : Array Diagnostic :=
  let definitionSpans := statements.flatMap fun statement =>
    match statement with
    | .assignment _ _ value _ span =>
        if handledExpressions.any (· == value) then #[span] else #[]
    | .conditional branches _ => branches.flatMap fun branch =>
        branch.statements.flatMap fun nested =>
          match nested with
          | .assignment _ _ value _ span =>
              if handledExpressions.any (· == value) then #[span] else #[]
          | _ => #[]
    | _ => #[]
  let handled := handled ++ definitionSpans
  diagnostics.filter fun diagnostic =>
    !handled.any fun span =>
      diagnostic.span == span &&
        ((diagnostic.code == "SKB1003" &&
            diagnostic.message == "Make function 'eval' is parsed but not symbolically evaluated") ||
          (diagnostic.code == "SKB1004" &&
            diagnostic.message == "top-level expansion side effects are not evaluated"))

def automaticEnvironment
    (sourceRoot : System.FilePath)
    (sourceName : String := ".") : Environment :=
  let environment : Environment := []
  let environment := environment.set "srctree"
    ⟨.simple, .literal sourceRoot.normalize.toString⟩
  let environment := environment.set "src" ⟨.simple, .literal sourceName⟩
  environment.set "obj" ⟨.simple, .literal sourceName⟩

private def relativePath (root path : System.FilePath) : String :=
  let rootText := root.normalize.toString
  let pathText := path.normalize.toString
  let rootPrefix := if rootText.endsWith "/" then rootText else rootText ++ "/"
  if pathText.startsWith rootPrefix then (pathText.drop rootPrefix.length).toString else pathText

def captureFilesystem (root : System.FilePath) : IO (List String) := do
  let entries ← System.FilePath.walkDir root
  let mut paths := [root.normalize.toString, "."]
  for path in entries do
    paths := path.normalize.toString :: relativePath root path :: paths
  return paths.mergeSort.eraseDups

partial def discoverSourceRoot (start : System.FilePath) : IO System.FilePath := do
  let rec ascend (current candidate : System.FilePath) : IO System.FilePath := do
    let candidate ← if ← (current / "Kbuild").pathExists then pure current else pure candidate
    match current.parent with
    | some parent =>
        let parent := parent.normalize
        if parent == current then pure candidate else ascend parent candidate
    | none => pure candidate
  ascend start.normalize start.normalize

mutual
  partial def executeExpressionIO
      (settings : Settings)
      (base : System.FilePath)
      (expression : Expr)
      (span : SourceSpan)
      (paths : Array SymPath)
      (includeStack : List String)
      (knownContributions : Array TargetContribution) : IO Execution := do
    match expression with
    | .function .eval args =>
        match args[0]? with
        | none =>
            return {
              paths := paths
              diagnostics := #[diagnostic "SKB1003" "eval requires one argument" span]
            }
        | some argument =>
            let mut result : Execution := { paths := #[] }
            for path in paths do
              let alternatives := expandText settings path.environment argument
              if alternatives.isEmpty then
                result := appendExecution result {
                  paths := #[path]
                  diagnostics := #[diagnostic "SKB1003"
                    "eval argument could not be expanded" span]
                }
              for alternative in alternatives do
                let condition := path.condition.conj alternative.condition
                if !feasible settings condition then continue
                match Parser.parse alternative.value (span.file ++ ":eval") with
                | .error message =>
                    result := appendExecution result {
                      paths := #[{ path with condition }]
                      diagnostics := #[diagnostic "SKB1003"
                        s!"cannot parse generated eval text: {message}" span]
                    }
                | .ok generated =>
                    -- Do not reduce generated text independently: an eval can
                    -- define a helper consumed by a later outer statement.
                    let generatedExecution ← executeStatementsIO settings base generated.statements
                      #[{ path with condition }] includeStack false knownContributions
                    result := appendExecution result {
                      generatedExecution with
                      handledEvalSpans := #[span] ++ generatedExecution.handledEvalSpans
                      diagnostics := validateMakefile generated ++ generatedExecution.diagnostics
                    }
            return { result with paths := mergePaths result.paths }
    | .function .ifThenElse args =>
        match args[0]?, args[1]? with
        | some conditionExpression, some thenExpression =>
            let mut result : Execution := { paths := #[] }
            for path in paths do
              let conditions := expandText settings path.environment conditionExpression
              for condition in conditions do
                let pathCondition := path.condition.conj condition.condition
                if !feasible settings pathCondition then continue
                let chosen := if condition.value.trimAscii.toString.isEmpty then
                  args[2]?.getD (.literal "")
                else thenExpression
                let branch ← executeExpressionIO settings base chosen span
                  #[{ path with condition := pathCondition }] includeStack knownContributions
                result := appendExecution result branch
            return { result with paths := mergePaths result.paths }
        | _, _ => return { paths }
    | .concat parts =>
        let mut current : Execution := { paths }
        for part in parts do
          let next ← executeExpressionIO settings base part span current.paths includeStack
            (knownContributions ++ current.targetContributions)
          current := {
            paths := mergePaths next.paths
            targetContributions := current.targetContributions ++ next.targetContributions
            contributionMasks := current.contributionMasks ++ next.contributionMasks
            handledEvalSpans := current.handledEvalSpans ++ next.handledEvalSpans
            handledEvalExpressions := current.handledEvalExpressions ++ next.handledEvalExpressions
            diagnostics := current.diagnostics ++ next.diagnostics
          }
        return current
    | .variable name =>
        let mut result : Execution := { paths := #[] }
        for path in paths do
          let names := expandText settings path.environment name
          for named in names do
            let condition := path.condition.conj named.condition
            match path.environment.get? named.value with
            | none => result := appendExecution result { paths := #[{ path with condition }] }
                | some stored =>
                    let expanded ← executeExpressionIO settings base stored.value span
                      #[{ path with condition }] includeStack knownContributions
                    result := appendExecution result {
                      expanded with
                      handledEvalExpressions := if exprContainsEval stored.value then
                        #[stored.value] ++ expanded.handledEvalExpressions
                      else expanded.handledEvalExpressions
                    }
        return { result with paths := mergePaths result.paths }
    | .function .call args =>
        match args[0]? with
        | none => return { paths }
        | some nameExpression =>
            let mut result : Execution := { paths := #[] }
            for path in paths do
              let names := expandText settings path.environment nameExpression
              for named in names do
                let condition := path.condition.conj named.condition
                match path.environment.get? named.value with
                | none => result := appendExecution result { paths := #[{ path with condition }] }
                | some storedMacro =>
                    let mut callPaths : Array (Environment × Formula) :=
                      #[(path.environment.set "0" ⟨.simple, .literal named.value⟩, condition)]
                    for (argument, index) in (args.toList.drop 1).zip (List.range (args.size - 1)) do
                      let values := expandText settings path.environment argument
                      callPaths := callPaths.flatMap fun (environment, guard) =>
                        values.map fun value =>
                          (environment.set (toString (index + 1))
                            ⟨.simple, .literal value.value⟩,
                            guard.conj value.condition)
                    for (environment, guard) in callPaths do
                      let called ← executeExpressionIO settings base storedMacro.value span
                        #[{ path with condition := guard, environment }] includeStack knownContributions
                      result := appendExecution result {
                        called with
                        handledEvalExpressions := if exprContainsEval storedMacro.value then
                          #[storedMacro.value] ++ called.handledEvalExpressions
                        else called.handledEvalExpressions
                      }
            return { result with paths := mergePaths result.paths }
    | _ => return { paths }

  partial def executeStatementsIO
      (settings : Settings)
      (base : System.FilePath)
      (statements : Array Statement)
      (initialPaths : Array SymPath)
      (includeStack : List String)
      (streamTargets : Bool)
    (knownContributions : Array TargetContribution := #[]) : IO Execution := do
    let mut execution : Execution := { paths := initialPaths }
    let mut maskedKnown := knownContributions
    for statement in statements do
      let next ← executeStatementIO settings base statement execution.paths includeStack streamTargets
        (maskedKnown ++ execution.targetContributions)
      maskedKnown := applyContributionMasks maskedKnown next.contributionMasks
      execution := {
        paths := mergePaths next.paths
        targetContributions := applyContributionMasks execution.targetContributions
            next.contributionMasks ++ next.targetContributions
        contributionMasks := execution.contributionMasks ++ next.contributionMasks
        diagnostics := execution.diagnostics ++ next.diagnostics
        handledEvalExpressions := execution.handledEvalExpressions ++ next.handledEvalExpressions
        handledEvalSpans := execution.handledEvalSpans ++ next.handledEvalSpans
      }
    return execution

  partial def executeStatementIO
      (settings : Settings)
      (base : System.FilePath)
      (statement : Statement)
      (paths : Array SymPath)
      (includeStack : List String)
      (streamTargets : Bool)
      (knownContributions : Array TargetContribution) : IO Execution := do
    match statement with
    | .include pathExpression required span =>
        let mut result : Execution := { paths := #[] }
        for path in paths do
          let alternatives := expandText settings path.environment pathExpression
          if alternatives.isEmpty && required then
            result := appendExecution result {
              paths := #[path]
              diagnostics := #[diagnostic "SKB2001" "required include expanded to no paths" span]
            }
          for alternative in alternatives do
            let condition := path.condition.conj alternative.condition
            if !feasible settings condition then continue
            let names := words alternative.value
            if names.isEmpty && required then
              result := appendExecution result {
                paths := #[{ path with condition }]
                diagnostics := #[diagnostic "SKB2001" "required include expanded to an empty path" span]
              }
            for name in names do
              let includePath := resolveFilePath base name
              let includeName := includePath.toString
              if includeStack.contains includeName then
                result := appendExecution result {
                  paths := #[{ path with condition }]
                  diagnostics := #[diagnostic "SKB2002" s!"include cycle at {includeName}" span]
                }
                continue
              if !(← includePath.pathExists) then
                if required then
                  result := appendExecution result {
                    paths := #[{ path with condition }]
                    diagnostics := #[diagnostic "SKB2003" s!"required include not found: {includeName}" span]
                  }
                else
                  result := appendExecution result { paths := #[{ path with condition }] }
                continue
              match ← Parser.parseFile includePath with
              | .error message =>
                  result := appendExecution result {
                    paths := #[{ path with condition }]
                    diagnostics := #[diagnostic "SKB2004" s!"cannot parse include {includeName}: {message}" span]
                  }
              | .ok makefile =>
                  let reduced := reduceMakefile settings makefile
                  let included ← executeStatementsIO settings base reduced.statements
                    #[{ path with condition }] (includeName :: includeStack)
                    (reduced.canStreamTargets settings) knownContributions
                  result := appendExecution result {
                    included with
                    diagnostics := validateMakefile reduced ++ included.diagnostics
                  }
        return { result with paths := mergePaths result.paths }
    | .conditional branches _ =>
        let mut total : Execution := { paths := #[] }
        for path in paths do
          let mut remaining := Formula.top
          let mut branchResult : Execution := { paths := #[] }
          for branch in branches do
            let branchFormula := match branch.condition with
              | .otherwise => remaining
              | condition => remaining.conj (conditionFormula settings path knownContributions condition)
            let pathCondition := path.condition.conj branchFormula
            if feasible settings pathCondition then
              let selected ← executeStatementsIO settings base branch.statements
                #[{ path with condition := pathCondition }] includeStack streamTargets knownContributions
              branchResult := appendExecution branchResult selected
            remaining := match branch.condition with
              | .otherwise => .bottom
              | condition => remaining.conj (conditionFormula settings path knownContributions condition).neg
          let residualCondition := path.condition.conj remaining
          if feasible settings residualCondition then
            branchResult := appendExecution branchResult {
              paths := #[{ path with condition := residualCondition }]
            }
          total := appendExecution total branchResult
        return { total with paths := mergePaths total.paths }
    | .expression expression span =>
        return ← executeExpressionIO settings base expression span paths includeStack knownContributions
    | other => return executeStatement settings other paths streamTargets knownContributions
end

def analyzeFile
    (settings : Settings)
    (path : System.FilePath)
    (initialCondition : Formula := .top)
    (initialEnvironment : Option Environment := none)
    (sourceRootOverride : Option System.FilePath := none) : IO (Except String Execution) := do
  if !(← path.pathExists) then
    return .error s!"input does not exist: {path}"
  let resolvedPath ← IO.FS.realPath path
  match ← Parser.parseFile resolvedPath with
  | .error message => return .error message
  | .ok makefile =>
      let currentDirectory := resolvedPath.parent.getD (System.FilePath.mk ".")
      let sourceRoot ← match sourceRootOverride with
        | some root => pure root.normalize
        | none => discoverSourceRoot currentDirectory
      let sourceName := relativePath sourceRoot currentDirectory
      let sourceName := if sourceName.isEmpty then "." else sourceName
      let filesystemPaths ← if settings.filesystemPaths.isEmpty then captureFilesystem sourceRoot
        else pure settings.filesystemPaths
      let settings := { settings with
        filesystemPaths
        workingDirectory := sourceRoot.toString
      } |>.forMakefile makefile
      let environment := initialEnvironment.getD <| automaticEnvironment sourceRoot sourceName
      let reduced := reduceMakefile settings makefile
      let execution ← executeStatementsIO settings sourceRoot reduced.statements
        #[{ condition := initialCondition, environment }] [resolvedPath.toString]
        (reduced.canStreamTargets settings)
      return .ok { execution with
        targetContributions := mergeTargetContributions execution.targetContributions
        diagnostics := suppressHandledEvalDiagnostics reduced.statements execution.handledEvalSpans
          execution.handledEvalExpressions
          (validateMakefile reduced ++ execution.diagnostics) }

end Skbuild
