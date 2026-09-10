import Lean.Data.Json
import Skbuild.Syntax

namespace Skbuild

open Lean

private def failAt (context message : String) : Except String α :=
  .error s!"{context}: {message}"

private def field (json : Json) (name context : String) : Except String Json :=
  match json.getObjVal? name with
  | .ok value => .ok value
  | .error error => failAt context s!"missing or invalid field '{name}': {error}"

private def stringField (json : Json) (name context : String) : Except String String := do
  let value ← field json name context
  match value.getStr? with
  | .ok text => pure text
  | .error error => failAt context s!"field '{name}' is not a string: {error}"

private def boolField (json : Json) (name context : String) : Except String Bool := do
  let value ← field json name context
  match value.getBool? with
  | .ok flag => pure flag
  | .error error => failAt context s!"field '{name}' is not a boolean: {error}"

private def natField (json : Json) (name context : String) : Except String Nat := do
  let value ← field json name context
  match value.getNat? with
  | .ok number => pure number
  | .error error => failAt context s!"field '{name}' is not a natural number: {error}"

private def arrayField (json : Json) (name context : String) : Except String (Array Json) := do
  let value ← field json name context
  match value.getArr? with
  | .ok values => pure values
  | .error error => failAt context s!"field '{name}' is not an array: {error}"

private def decodePos (json : Json) (context : String) : Except String SourcePos := do
  pure {
    offset := ← natField json "offset" context
    line := ← natField json "line" context
    column := ← natField json "column" context
  }

private def decodeSpan (json : Json) (context : String) : Except String SourceSpan := do
  pure {
    file := ← stringField json "file" context
    start := ← decodePos (← field json "start" context) s!"{context}.start"
    stop := ← decodePos (← field json "stop" context) s!"{context}.stop"
  }

private def decodeFunction : String → MakeFunction
  | "subst" => .subst
  | "patsubst" => .patsubst
  | "strip" => .strip
  | "filter" => .filter
  | "filter-out" => .filterOut
  | "sort" => .sort
  | "word" => .word
  | "wordlist" => .wordlist
  | "words" => .words
  | "firstword" => .firstword
  | "lastword" => .lastword
  | "dir" => .dir
  | "notdir" => .notdir
  | "suffix" => .suffix
  | "basename" => .basename
  | "addsuffix" => .addsuffix
  | "addprefix" => .addprefix
  | "join" => .join
  | "wildcard" => .wildcard
  | "realpath" => .realpath
  | "abspath" => .abspath
  | "if" => .ifThenElse
  | "or" => .or
  | "and" => .and
  | "foreach" => .foreach
  | "call" => .call
  | "value" => .value
  | "eval" => .eval
  | "origin" => .origin
  | "flavor" => .flavor
  | "shell" => .shell
  | "error" => .error
  | "warning" => .warning
  | "info" => .info
  | name => .unknown name

partial def decodeExpr (json : Json) (context : String := "expression") : Except String Expr := do
  let kind ← stringField json "kind" context
  match kind with
  | "literal" => pure <| .literal (← stringField json "value" context)
  | "variable" => pure <| .variable (← decodeExpr (← field json "name" context) s!"{context}.name")
  | "function" =>
      let name ← stringField json "name" context
      let args ← arrayField json "args" context
      pure <| .function (decodeFunction name) (← args.mapIdxM fun index arg =>
        decodeExpr arg s!"{context}.args[{index}]")
  | "concat" =>
      let parts ← arrayField json "parts" context
      pure <| .concat (← parts.mapIdxM fun index part =>
        decodeExpr part s!"{context}.parts[{index}]")
  | other => failAt context s!"unknown expression kind '{other}'"

private def decodeAssignOp (token context : String) : Except String AssignOp :=
  match token with
  | "=" => pure .recursive
  | ":=" => pure .simple
  | "::=" => pure .simplePosix
  | "+=" => pure .append
  | "?=" => pure .conditional
  | other => failAt context s!"unknown assignment operator '{other}'"

private def decodeCondition (json : Json) (context : String) : Except String Condition := do
  let kind ← stringField json "kind" context
  match kind with
  | "equals" =>
      let left ← decodeExpr (← field json "left" context) s!"{context}.left"
      let right ← decodeExpr (← field json "right" context) s!"{context}.right"
      let expected ← boolField json "expected" context
      pure <| .equals left right expected
  | "defined" =>
      let name ← decodeExpr (← field json "name" context) s!"{context}.name"
      let expected ← boolField json "expected" context
      pure <| .defined name expected
  | "otherwise" => pure .otherwise
  | other => failAt context s!"unknown condition kind '{other}'"

mutual
  partial def decodeStatement (json : Json) (context : String := "statement") : Except String Statement := do
    let kind ← stringField json "kind" context
    let span ← decodeSpan (← field json "span" context) s!"{context}.span"
    match kind with
    | "assignment" =>
        let targetJson ← field json "target" context
        let target ← match targetJson with
          | .null => pure none
          | value => some <$> decodeExpr value s!"{context}.target"
        let name ← decodeExpr (← field json "name" context) s!"{context}.name"
        let operator ← decodeAssignOp (← stringField json "operator" context) context
        let value ← decodeExpr (← field json "value" context) s!"{context}.value"
        pure <| .assignment name operator value target span
    | "conditional" =>
        let branches ← arrayField json "branches" context
        let decoded ← branches.mapIdxM fun index branch =>
          decodeBranch branch s!"{context}.branches[{index}]"
        pure <| .conditional decoded span
    | "include" =>
        let paths ← decodeExpr (← field json "paths" context) s!"{context}.paths"
        let required ← boolField json "required" context
        pure <| .include paths required span
    | "rule" => pure <| .rule (← stringField json "source" context) span
    | "command" => pure <| .command (← stringField json "source" context) span
    | "expression" =>
        let value ← decodeExpr (← field json "value" context) s!"{context}.value"
        pure <| .expression value span
    | other => failAt context s!"unknown statement kind '{other}'"

  partial def decodeBranch (json : Json) (context : String := "branch") : Except String Branch := do
    let statements ← arrayField json "statements" context
    pure {
      condition := ← decodeCondition (← field json "condition" context) s!"{context}.condition"
      statements := ← statements.mapIdxM fun index statement =>
        decodeStatement statement s!"{context}.statements[{index}]"
      span := ← decodeSpan (← field json "span" context) s!"{context}.span"
    }
end

def decodeMakefile (json : Json) : Except String Makefile := do
  let schema ← natField json "schema" "makefile"
  if schema != 1 then
    throw s!"makefile: unsupported schema {schema}; expected 1"
  let statements ← arrayField json "statements" "makefile"
  pure {
    schema
    source := ← stringField json "source" "makefile"
    statements := ← statements.mapIdxM fun index statement =>
      decodeStatement statement s!"makefile.statements[{index}]"
  }

end Skbuild
