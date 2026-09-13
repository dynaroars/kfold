import Lean.Data.Json
import Lean.Data.Json.Printer
import Skbuild.Analysis

namespace Skbuild

open Lean
open Logic

private def targetRank : TargetKind → Nat
  | .builtIn => 0
  | .module => 1
  | .library => 2

def sortFiles (files : Array FilePresence) : Array FilePresence :=
  files.toList.mergeSort (fun left right =>
    left.path < right.path ||
      (left.path == right.path && targetRank left.target < targetRank right.target))
  |>.toArray

partial def formulaJson : Formula → Json
  | .top => Json.mkObj [("kind", "true")]
  | .bottom => Json.mkObj [("kind", "false")]
  | .eq symbol value => Json.mkObj [
      ("kind", "equals"), ("symbol", symbol), ("value", value)]
  | .not body => Json.mkObj [("kind", "not"), ("body", formulaJson body)]
  | .and left right => Json.mkObj [
      ("kind", "and"), ("left", formulaJson left), ("right", formulaJson right)]
  | .or left right => Json.mkObj [
      ("kind", "or"), ("left", formulaJson left), ("right", formulaJson right)]

def diagnosticJson (diagnostic : Diagnostic) : Json := Json.mkObj [
  ("code", diagnostic.code),
  ("severity", match diagnostic.severity with
    | .info => "info" | .warning => "warning" | .error => "error"),
  ("message", diagnostic.message),
  ("file", diagnostic.span.file),
  ("line", toJson diagnostic.span.start.line),
  ("column", toJson diagnostic.span.start.column),
  ("makes_incomplete", diagnostic.makesIncomplete)
]

def filePresenceJson (file : FilePresence) : Json := Json.mkObj [
  ("path", file.path),
  ("target", file.target.render),
  ("condition", formulaJson file.condition),
  ("condition_text", file.condition.render)
]

inductive AnalysisScope
  | unspecified
  | singleMakefile
  | recursiveTree
  | jsonAst
  deriving Repr, BEq, DecidableEq, Inhabited

def AnalysisScope.render : AnalysisScope → String
  | .unspecified => "unspecified"
  | .singleMakefile => "single-makefile"
  | .recursiveTree => "recursive-tree"
  | .jsonAst => "json-ast"

inductive InputCoverage
  | complete
  | incomplete
  | unknown
  deriving Repr, BEq, DecidableEq, Inhabited

def InputCoverage.render : InputCoverage → String
  | .complete => "complete"
  | .incomplete => "incomplete"
  | .unknown => "unknown"

inductive KconfigValidity
  | notChecked
  | concreteFilter
  deriving Repr, BEq, DecidableEq, Inhabited

def KconfigValidity.render : KconfigValidity → String
  | .notChecked => "not-checked"
  | .concreteFilter => "concrete-filter-only"

inductive ValidationStatus
  | notRequested
  | requested
  deriving Repr, BEq, DecidableEq, Inhabited

def ValidationStatus.render : ValidationStatus → String
  | .notRequested => "not-requested"
  | .requested => "requested"

inductive Qualification
  | exactWithinModeledScope
  | overapproximation
  | underapproximation
  | unknown
  deriving Repr, BEq, DecidableEq, Inhabited

def Qualification.render : Qualification → String
  | .exactWithinModeledScope => "exact-within-modeled-scope"
  | .overapproximation => "overapproximation"
  | .underapproximation => "underapproximation"
  | .unknown => "unknown"

structure ReportContext where
  selectedScope : AnalysisScope := .unspecified
  inputCoverage : InputCoverage := .unknown
  unsupportedSemantics : Bool := false
  kconfigValidity : KconfigValidity := .notChecked
  validation : ValidationStatus := .notRequested
  qualification : Qualification := .unknown
  deriving Repr, BEq, Inhabited

private def missingInputDiagnostic (diagnostic : Diagnostic) : Bool :=
  diagnostic.makesIncomplete &&
    (diagnostic.code == "SKB2001" || diagnostic.code == "SKB2003" ||
      diagnostic.code == "SKB2004")

private def unsupportedDiagnostic (diagnostic : Diagnostic) : Bool :=
  diagnostic.makesIncomplete &&
    (diagnostic.code == "SKB1003" || diagnostic.code == "SKB1004")

def ReportContext.fromDiagnostics
    (scope : AnalysisScope)
    (hasConcreteConfig : Bool)
    (hasValidation : Bool)
    (diagnostics : Array Diagnostic) : ReportContext :=
  let incomplete := diagnostics.any (·.makesIncomplete)
  {
    selectedScope := scope
    inputCoverage := if diagnostics.any missingInputDiagnostic then .incomplete
      else if incomplete then .unknown else .complete
    unsupportedSemantics := diagnostics.any unsupportedDiagnostic
    kconfigValidity := if hasConcreteConfig then .concreteFilter else .notChecked
    validation := if hasValidation then .requested else .notRequested
    qualification := if incomplete then .unknown else .exactWithinModeledScope
  }

/-
  These fields deliberately describe what the analyzer can establish from the
  current invocation.  In particular, an incomplete run is `unknown`, rather
  than an over- or under-approximation: the direction of an error depends on
  the unsupported Make/Kbuild feature.
-/
def reportCoverageJson (context : ReportContext) : Json :=
  Json.mkObj [
    ("selected_scope", context.selectedScope.render),
    ("input_coverage", context.inputCoverage.render),
    ("unsupported_semantics", context.unsupportedSemantics),
    ("kconfig_validity", context.kconfigValidity.render),
    ("build_validation", context.validation.render),
    ("qualification", context.qualification.render)
  ]

def reportJson
    (files : Array FilePresence)
    (diagnostics : Array Diagnostic)
    (context : ReportContext := {}) : Json :=
  let incomplete := diagnostics.any (·.makesIncomplete)
  Json.mkObj [
    ("schema", toJson (1 : Nat)),
    ("complete", !incomplete),
    ("coverage", reportCoverageJson context),
    ("files", Json.arr <| (sortFiles files).map filePresenceJson),
    ("diagnostics", Json.arr <| diagnostics.map diagnosticJson)
  ]

def renderJsonReport
    (files : Array FilePresence)
    (diagnostics : Array Diagnostic)
    (context : ReportContext := {}) : String :=
  (reportJson files diagnostics context).pretty

private def reportField (json : Json) (name : String) : Except String Json :=
  json.getObjVal? name |>.mapError fun error => s!"report field '{name}': {error}"

private partial def decodeFormula (json : Json) : Except String Formula := do
  let kind ← (← reportField json "kind").getStr?
  match kind with
  | "true" => pure Formula.top
  | "false" => pure Formula.bottom
  | "equals" =>
      let symbolJson ← reportField json "symbol"
      let valueJson ← reportField json "value"
      pure <| Formula.eq (← symbolJson.getStr?) (← valueJson.getStr?)
  | "not" =>
      let bodyJson ← reportField json "body"
      pure <| Formula.not (← decodeFormula bodyJson)
  | "and" =>
      let leftJson ← reportField json "left"
      let rightJson ← reportField json "right"
      pure <| Formula.and (← decodeFormula leftJson) (← decodeFormula rightJson)
  | "or" =>
      let leftJson ← reportField json "left"
      let rightJson ← reportField json "right"
      pure <| Formula.or (← decodeFormula leftJson) (← decodeFormula rightJson)
  | other => throw s!"unknown report formula kind '{other}'"

private def decodeTarget (value : String) : Except String TargetKind :=
  match value with
  | "built-in" => pure .builtIn
  | "module" => pure .module
  | "library" => pure .library
  | other => throw s!"unknown report target '{other}'"

private def decodeSeverity (value : String) : Except String Severity :=
  match value with
  | "info" => pure .info
  | "warning" => pure .warning
  | "error" => pure .error
  | other => throw s!"unknown diagnostic severity '{other}'"

def decodeReport (json : Json) : Except String (Array FilePresence × Array Diagnostic) := do
  let schema ← (← reportField json "schema").getNat?
  if schema != 1 then throw s!"unsupported report schema {schema}"
  let fileValues ← (← reportField json "files").getArr?
  let diagnosticValues ← (← reportField json "diagnostics").getArr?
  let files ← fileValues.mapM fun value => do
    pure {
      path := ← (← reportField value "path").getStr?
      target := ← decodeTarget (← (← reportField value "target").getStr?)
      condition := ← decodeFormula (← reportField value "condition")
    }
  let diagnostics ← diagnosticValues.mapM fun value => do
    let file ← (← reportField value "file").getStr?
    let line ← (← reportField value "line").getNat?
    let column ← (← reportField value "column").getNat?
    pure {
      code := ← (← reportField value "code").getStr?
      severity := ← decodeSeverity (← (← reportField value "severity").getStr?)
      message := ← (← reportField value "message").getStr?
      span := { file, start := { line, column }, stop := { line, column } }
      makesIncomplete := ← (← reportField value "makes_incomplete").getBool?
    }
  pure (files, diagnostics)

end Skbuild
