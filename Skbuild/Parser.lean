import Skbuild.Syntax

namespace Skbuild.Parser

open Skbuild

structure Line where
  number : Nat
  text : String
  deriving Repr, Inhabited

private def spanFor (file : String) (line : Nat) (column : Nat := 0) : SourceSpan :=
  { file
    start := { line, column }
    stop := { line, column := column } }

private def stripCommentChars : List Char → Bool → List Char
  | [], _ => []
  | '#' :: _, false => []
  | '\\' :: '#' :: rest, _ => '#' :: stripCommentChars rest false
  | '\\' :: rest, _ => '\\' :: stripCommentChars rest true
  | char :: rest, _ => char :: stripCommentChars rest false

private def stripComment (text : String) : String :=
  String.ofList <| stripCommentChars text.toList false

private def trimString (text : String) : String := text.trimAscii.toString

private def trimLeftString (text : String) : String := text.trimAsciiStart.toString

private def dropString (text : String) (count : Nat) : String := (text.drop count).toString

private def dropRightString (text : String) (count : Nat) : String :=
  text.dropEnd count |>.toString

private def splitOnce (text token : String) : Option (String × String) :=
  match text.splitOn token with
  | [] | [_] => none
  | first :: rest => some (first, String.intercalate token rest)

private def functionOfName : String → MakeFunction
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

private def knownFunction (name : String) : Bool :=
  match functionOfName name with
  | .unknown _ => false
  | _ => true

private def takeBalanced
    (closing : Char)
    (input : List Char)
    (depth : Nat := 1)
    (acc : List Char := []) : Except String (List Char × List Char) :=
  match input with
  | [] => .error "unterminated Make expansion"
  | char :: rest =>
      if char == closing then
        if depth == 1 then .ok (acc.reverse, rest)
        else takeBalanced closing rest (depth - 1) (char :: acc)
      else if (closing == ')' && char == '(') || (closing == '}' && char == '{') then
        takeBalanced closing rest (depth + 1) (char :: acc)
      else
        takeBalanced closing rest depth (char :: acc)

private def splitTopLevelChars
    (input : List Char)
    (separator : Char)
    (roundDepth squareDepth : Nat := 0)
    (current : List Char := [])
    (output : List String := []) : List String :=
  match input with
  | [] => (String.ofList current.reverse) :: output |>.reverse
  | char :: rest =>
      if char == separator && roundDepth == 0 && squareDepth == 0 then
        splitTopLevelChars rest separator 0 0 [] ((String.ofList current.reverse) :: output)
      else
        let nextRound :=
          if char == '(' then roundDepth + 1
          else if char == ')' && roundDepth > 0 then roundDepth - 1
          else roundDepth
        let nextSquare :=
          if char == '{' then squareDepth + 1
          else if char == '}' && squareDepth > 0 then squareDepth - 1
          else squareDepth
        splitTopLevelChars rest separator nextRound nextSquare (char :: current) output

private def splitTopLevel (text : String) (separator : Char) : List String :=
  splitTopLevelChars text.toList separator

mutual
  partial def parseExprChars
      (input : List Char)
      (literal : List Char := [])
      (parts : Array Expr := #[]) : Except String (Array Expr) :=
    match input with
    | [] =>
        let parts := if literal.isEmpty then parts else parts.push (.literal <| String.ofList literal.reverse)
        pure parts
    | '$' :: '(' :: rest => do
        let balanced ← takeBalanced ')' rest
        let inside := balanced.1
        let remaining := balanced.2
        let parts := if literal.isEmpty then parts else parts.push (.literal <| String.ofList literal.reverse)
        let expansion ← parseExpansionBody <| String.ofList inside
        parseExprChars remaining [] (parts.push expansion)
    | '$' :: '{' :: rest => do
        let balanced ← takeBalanced '}' rest
        let inside := balanced.1
        let remaining := balanced.2
        let parts := if literal.isEmpty then parts else parts.push (.literal <| String.ofList literal.reverse)
        let expansion ← parseExpansionBody <| String.ofList inside
        parseExprChars remaining [] (parts.push expansion)
    | '$' :: '$' :: rest => parseExprChars rest ('$' :: literal) parts
    | char :: rest => parseExprChars rest (char :: literal) parts

  partial def parseExpansionBody (body : String) : Except String Expr := do
    let trimmed := trimString body
    let nameAndRest := trimmed.toList.span (fun char => !char.isWhitespace)
    let functionName := String.ofList nameAndRest.1
    if functionName.isEmpty then
      pure <| .variable (.literal "")
    else
        if knownFunction functionName && !nameAndRest.2.isEmpty then
          let argumentsText := trimLeftString <| dropString trimmed functionName.length
          let arguments ← (splitTopLevel argumentsText ',').toArray.mapM parseExpr
          pure <| .function (functionOfName functionName) arguments
        else
          match splitTopLevel trimmed ':' with
          | [name, substitution] =>
              match splitTopLevel substitution '=' with
              | [fromValue, toValue] =>
                  let pattern := if fromValue.contains '%' then fromValue else "%" ++ fromValue
                  let replacement := if toValue.contains '%' then toValue else "%" ++ toValue
                  pure <| .function .patsubst #[
                    ← parseExpr pattern,
                    ← parseExpr replacement,
                    .variable (← parseExpr name)
                  ]
              | _ => pure <| .variable (← parseExpr trimmed)
          | _ => pure <| .variable (← parseExpr trimmed)

  partial def parseExpr (text : String) : Except String Expr := do
    let parts ← parseExprChars text.toList
    match parts.toList with
    | [] => pure <| .literal ""
    | [part] => pure part
    | _ => pure <| .concat parts
end

private def assignmentChars?
    (input : List Char)
    (roundDepth braceDepth : Nat := 0)
    (before : List Char := []) : Option (String × AssignOp × String) :=
  match input with
  | [] => none
  | '$' :: '(' :: rest => assignmentChars? rest (roundDepth + 1) braceDepth ('(' :: '$' :: before)
  | '$' :: '{' :: rest => assignmentChars? rest roundDepth (braceDepth + 1) ('{' :: '$' :: before)
  | ')' :: rest =>
      assignmentChars? rest (if roundDepth > 0 then roundDepth - 1 else 0) braceDepth (')' :: before)
  | '}' :: rest =>
      assignmentChars? rest roundDepth (if braceDepth > 0 then braceDepth - 1 else 0) ('}' :: before)
  | ':' :: ':' :: '=' :: rest =>
      if roundDepth == 0 && braceDepth == 0 then
        some (String.ofList before.reverse, .simplePosix, String.ofList rest)
      else assignmentChars? rest roundDepth braceDepth ('=' :: ':' :: ':' :: before)
  | ':' :: '=' :: rest =>
      if roundDepth == 0 && braceDepth == 0 then
        some (String.ofList before.reverse, .simple, String.ofList rest)
      else assignmentChars? rest roundDepth braceDepth ('=' :: ':' :: before)
  | '+' :: '=' :: rest =>
      if roundDepth == 0 && braceDepth == 0 then
        some (String.ofList before.reverse, .append, String.ofList rest)
      else assignmentChars? rest roundDepth braceDepth ('=' :: '+' :: before)
  | '?' :: '=' :: rest =>
      if roundDepth == 0 && braceDepth == 0 then
        some (String.ofList before.reverse, .conditional, String.ofList rest)
      else assignmentChars? rest roundDepth braceDepth ('=' :: '?' :: before)
  | '=' :: rest =>
      if roundDepth == 0 && braceDepth == 0 then
        some (String.ofList before.reverse, .recursive, String.ofList rest)
      else assignmentChars? rest roundDepth braceDepth ('=' :: before)
  | char :: rest => assignmentChars? rest roundDepth braceDepth (char :: before)

private partial def stripAssignmentModifiers (text : String) : String :=
  let trimmed := trimString text
  match ["export ", "override ", "private "].find? (fun modifier => trimmed.startsWith modifier) with
  | some modifier => stripAssignmentModifiers <| dropString trimmed modifier.length
  | none => trimmed

private def splitTargetChars?
    (input : List Char)
    (roundDepth braceDepth : Nat := 0)
    (before : List Char := []) : Option (String × String) :=
  match input with
  | [] => none
  | '$' :: '(' :: rest => splitTargetChars? rest (roundDepth + 1) braceDepth ('(' :: '$' :: before)
  | '$' :: '{' :: rest => splitTargetChars? rest roundDepth (braceDepth + 1) ('{' :: '$' :: before)
  | ')' :: rest =>
      splitTargetChars? rest (if roundDepth > 0 then roundDepth - 1 else 0) braceDepth (')' :: before)
  | '}' :: rest =>
      splitTargetChars? rest roundDepth (if braceDepth > 0 then braceDepth - 1 else 0) ('}' :: before)
  | ':' :: rest =>
      if roundDepth == 0 && braceDepth == 0 then
        some (String.ofList before.reverse, String.ofList rest)
      else splitTargetChars? rest roundDepth braceDepth (':' :: before)
  | char :: rest => splitTargetChars? rest roundDepth braceDepth (char :: before)

private def assignment?
    (text : String) : Option (String × AssignOp × String × Option String) :=
  (assignmentChars? text.toList).map fun (rawName, operator, value) =>
    let lhs := stripAssignmentModifiers rawName
    match splitTargetChars? lhs.toList with
    | some (target, name) =>
        (stripAssignmentModifiers name, operator, trimLeftString value, some (trimString target))
    | none => (lhs, operator, trimLeftString value, none)

private def parseEqCondition
    (text keyword : String)
    (expected : Bool) : Except String Condition := do
  let body := trimString <| dropString text keyword.length
  if body.startsWith "(" && body.endsWith ")" then
    let inner := dropRightString (dropString body 1) 1
    match splitTopLevel inner ',' with
    | [left, right] =>
        let leftExpr ← parseExpr <| trimString left
        let rightExpr ← parseExpr <| trimString right
        pure <| .equals leftExpr rightExpr expected
    | _ => throw s!"{keyword} requires two comma-separated arguments"
  else
    let parseQuoted (quote : String) : Except String Condition :=
      match body.splitOn quote with
      | [before, left, gap, right, after] => do
          if !(trimString before).isEmpty || !(trimString after).isEmpty ||
              !(trimString gap).isEmpty then
            throw s!"unsupported {keyword} syntax"
          pure <| .equals (← parseExpr left) (← parseExpr right) expected
      | _ => throw s!"unsupported {keyword} syntax"
    if body.startsWith "\"" then parseQuoted "\""
    else if body.startsWith "'" then parseQuoted "'"
    else throw s!"unsupported {keyword} syntax"

private def parseCondition (text : String) : Except String Condition :=
  if text.startsWith "ifeq" then parseEqCondition text "ifeq" true
  else if text.startsWith "ifneq" then parseEqCondition text "ifneq" false
  else if text.startsWith "ifdef " then .defined <$> parseExpr (trimString <| dropString text 6) <*> pure true
  else if text.startsWith "ifndef " then .defined <$> parseExpr (trimString <| dropString text 7) <*> pure false
  else .error s!"unsupported condition: {text}"

private def physicalLines (contents : String) : Array Line :=
  contents.splitOn "\n" |>.toArray.mapIdx fun index text => { number := index + 1, text }

private def logicalLines (lines : Array Line) : Array Line := Id.run do
  let mut output := #[]
  let mut pending : Option Line := none
  for line in lines do
    let combined := match pending with
      | none => line
      | some prior => { prior with text := prior.text ++ trimLeftString line.text }
    if combined.text.endsWith "\\" then
      pending := some { combined with text := dropRightString combined.text 1 ++ " " }
    else
      output := output.push combined
      pending := none
  if let some line := pending then output := output.push line
  return output

private def isConditionalStart (text : String) : Bool :=
  ["ifeq", "ifneq", "ifdef", "ifndef"].any fun keyword =>
    text == keyword || text.startsWith (keyword ++ " ")

private def isStop (text : String) : Bool :=
  text == "else" || text == "endif" || text.startsWith "else "

mutual
  private partial def parseBlock
      (file : String)
      (lines : Array Line)
      (start : Nat)
      (initialRecipeAllowed : Bool) : Except String (Array Statement × Nat) := do
    let mut statements := #[]
    let mut index := start
    let mut recipeAllowed := initialRecipeAllowed
    while index < lines.size do
      let line := lines[index]!
      let trimmed := trimString <| stripComment line.text
      if isStop trimmed then return (statements, index)
      if trimmed.isEmpty then
        index := index + 1
        continue
      if trimmed == "define" || trimmed.startsWith "define " then
        let openingLine := line.number
        let nameText := trimString <| dropString trimmed 6
        if nameText.isEmpty then throw s!"{file}:{openingLine}: define has no variable name"
        let mut bodyLines : Array String := #[]
        index := index + 1
        let mut closed := false
        while index < lines.size && !closed do
          let nested := lines[index]!
          if trimString (stripComment nested.text) == "endef" then
            closed := true
          else
            bodyLines := bodyLines.push nested.text
          index := index + 1
        if !closed then throw s!"{file}:{openingLine}: define block has no endef"
        let nameExpr ← (parseExpr nameText).mapError fun error =>
          s!"{file}:{openingLine}: {error} in define name"
        let valueExpr ← (parseExpr <| String.intercalate "\n" bodyLines.toList).mapError fun error =>
          s!"{file}:{openingLine}: {error} in define body"
        statements := statements.push <|
          .assignment nameExpr .recursive valueExpr none (spanFor file openingLine)
        recipeAllowed := false
        continue
      if isConditionalStart trimmed then
        let (statement, next) ← parseConditional file lines index recipeAllowed
        statements := statements.push statement
        index := next
        continue
      let span := spanFor file line.number
      if line.text.startsWith "\t" && recipeAllowed then
        statements := statements.push <| .command line.text span
      else if let some (name, operator, value, target) := assignment? trimmed then
        let nameExpr ← (parseExpr name).mapError fun error =>
          s!"{file}:{line.number}: {error} in assignment name"
        let valueExpr ← (parseExpr value).mapError fun error =>
          s!"{file}:{line.number}: {error} in assignment value"
        let targetExpr ← target.mapM fun value => (parseExpr value).mapError fun error =>
          s!"{file}:{line.number}: {error} in assignment target"
        statements := statements.push <| .assignment nameExpr operator valueExpr targetExpr span
        recipeAllowed := false
      else if trimmed.startsWith "include " || trimmed.startsWith "-include " ||
          trimmed.startsWith "sinclude " then
        let required := trimmed.startsWith "include "
        let keywordLength := if required then 7 else if trimmed.startsWith "sinclude " then 8 else 8
        let pathExpr ← (parseExpr <| trimString <| dropString trimmed keywordLength).mapError
          fun error => s!"{file}:{line.number}: {error} in include"
        statements := statements.push <| .include pathExpr required span
        recipeAllowed := false
      else if trimmed.contains ':' then
        statements := statements.push <| .rule trimmed span
        recipeAllowed := true
      else
        let expression ← (parseExpr trimmed).mapError fun error =>
          s!"{file}:{line.number}: {error} in expression"
        statements := statements.push <| .expression expression span
        recipeAllowed := false
      index := index + 1
    return (statements, index)

  private partial def parseConditional
      (file : String)
      (lines : Array Line)
      (start : Nat)
      (recipeAllowed : Bool) : Except String (Statement × Nat) := do
    let opening := lines[start]!
    let openingText := trimString <| stripComment opening.text
    let firstCondition ← (parseCondition openingText).mapError fun error =>
      s!"{file}:{opening.number}: {error}"
    let (firstStatements, firstStop) ← parseBlock file lines (start + 1) recipeAllowed
    let mut branches : Array Branch := #[{
      condition := firstCondition
      statements := firstStatements
      span := spanFor file opening.number
    }]
    let mut index := firstStop
    let mut done := false
    while !done do
      if index >= lines.size then throw s!"{file}:{opening.number}: conditional has no endif"
      let marker := lines[index]!
      let markerText := trimString <| stripComment marker.text
      if markerText == "endif" then
        index := index + 1
        done := true
      else if markerText == "else" then
        let (body, stop) ← parseBlock file lines (index + 1) recipeAllowed
        branches := branches.push {
          condition := .otherwise, statements := body, span := spanFor file marker.number
        }
        index := stop
        if index >= lines.size || trimString (stripComment lines[index]!.text) != "endif" then
          throw s!"{file}:{marker.number}: else branch has no endif"
        index := index + 1
        done := true
      else if markerText.startsWith "else " then
        let nestedText := trimString <| dropString markerText 5
        let condition ← (parseCondition nestedText).mapError fun error =>
          s!"{file}:{marker.number}: {error}"
        let (body, stop) ← parseBlock file lines (index + 1) recipeAllowed
        branches := branches.push {
          condition, statements := body, span := spanFor file marker.number
        }
        index := stop
      else
        throw s!"{file}:{marker.number}: invalid conditional marker '{markerText}'"
    return (.conditional branches (spanFor file opening.number), index)
end

def parse (contents : String) (file : String := "<input>") : Except String Makefile := do
  let lines := logicalLines <| physicalLines contents
  let (statements, index) ← parseBlock file lines 0 false
  if index != lines.size then
    throw s!"{file}:{lines[index]!.number}: unexpected conditional terminator"
  pure { schema := 1, source := file, statements }

def parseFile (path : System.FilePath) : IO (Except String Makefile) := do
  let contents ← IO.FS.readFile path
  pure <| parse contents path.toString

end Skbuild.Parser
