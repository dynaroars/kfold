import Skbuild.State
import Skbuild.Path

namespace Skbuild

open Logic

private def crossConcat
    (left right : Array GuardedString)
    (separator : String := "") : Array GuardedString := Id.run do
  let mut output := #[]
  for lhs in left do
    for rhs in right do
      let condition := lhs.condition.conj rhs.condition
      if condition != Formula.bottom then
        output := output.push {
          value := lhs.value ++ separator ++ rhs.value
          condition
        }
  return output

private def concatAll (parts : Array (Array GuardedString)) : Array GuardedString :=
  parts.foldl crossConcat #[{ value := "", condition := .top }]

private def words (value : String) : List String :=
  value.split Char.isWhitespace |>.map String.Slice.toString |>.toList |>.filter (not ∘ String.isEmpty)

private def joinWords (values : List String) : String :=
  String.intercalate " " values

private partial def globMatchesChars : List Char → List Char → Bool
  | [], [] => true
  | '*' :: pattern, input =>
      globMatchesChars pattern input ||
        match input with
        | character :: rest => character != '/' && globMatchesChars ('*' :: pattern) rest
        | [] => false
  | '?' :: pattern, character :: rest =>
      character != '/' && globMatchesChars pattern rest
  | expected :: pattern, actual :: rest =>
      expected == actual && globMatchesChars pattern rest
  | _, _ => false

private def globMatches (pattern input : String) : Bool :=
  globMatchesChars pattern.toList input.toList

private def wildcardPaths (candidates : List String) (patterns : String) : String :=
  joinWords <| (words patterns).flatMap fun pattern =>
    candidates.filter (globMatches pattern) |>.mergeSort |>.eraseDups

private def absolutePath (settings : Settings) (value : String) : String :=
  let path := System.FilePath.mk value
  if path.isAbsolute || settings.workingDirectory.isEmpty then normalizeFilePath path |>.toString
  else resolveFilePath (System.FilePath.mk settings.workingDirectory) value |>.toString

private def trimString (value : String) : String := value.trimAscii.toString

private def splitOnce (text token : String) : Option (String × String) :=
  match text.splitOn token with
  | [] | [_] => none
  | first :: rest => some (first, String.intercalate token rest)

private def dropString (text : String) (count : Nat) : String :=
  (text.drop count).toString

private def dropEndString (text : String) (count : Nat) : String :=
  (text.dropEnd count).toString

private def matchPattern (pattern word : String) : Option String :=
  match splitOnce pattern "%" with
  | none => if pattern == word then some "" else none
  | some (before, after) =>
      if word.startsWith before && word.endsWith after &&
          word.length >= before.length + after.length then
        some <| dropEndString (dropString word before.length) after.length
      else none

private def replacePattern (replacement stem : String) : String :=
  match splitOnce replacement "%" with
  | none => replacement
  | some (before, after) => before ++ stem ++ after

private def substWords (pattern replacement input : String) : String :=
  joinWords <| (words input).map fun word =>
    match matchPattern pattern word with
    | some stem => replacePattern replacement stem
    | none => word

private def filterWords (patterns input : String) (keepMatches : Bool) : String :=
  joinWords <| (words input).filter fun word =>
    ((words patterns).any fun pattern => (matchPattern pattern word).isSome) == keepMatches

private def directoryPart (path : String) : String :=
  match path.splitOn "/" with
  | [] | [_] => "./"
  | parts => String.intercalate "/" parts.dropLast ++ "/"

private def filePart (path : String) : String :=
  (path.splitOn "/").getLast?.getD ""

private def suffixPart (path : String) : String :=
  let file := filePart path
  match file.splitOn "." with
  | [] | [_] => ""
  | parts => "." ++ parts.getLast?.getD ""

private def basenamePart (path : String) : String :=
  let suffix := suffixPart path
  if suffix.isEmpty then path else dropEndString path suffix.length

private def functionName : MakeFunction → String
  | .subst => "subst" | .patsubst => "patsubst" | .strip => "strip"
  | .filter => "filter" | .filterOut => "filter-out" | .sort => "sort"
  | .word => "word" | .wordlist => "wordlist" | .words => "words"
  | .firstword => "firstword" | .lastword => "lastword" | .dir => "dir"
  | .notdir => "notdir" | .suffix => "suffix" | .basename => "basename"
  | .addsuffix => "addsuffix" | .addprefix => "addprefix" | .join => "join"
  | .wildcard => "wildcard" | .realpath => "realpath" | .abspath => "abspath"
  | .ifThenElse => "if" | .or => "or" | .and => "and" | .foreach => "foreach"
  | .call => "call" | .value => "value" | .eval => "eval" | .origin => "origin"
  | .flavor => "flavor" | .shell => "shell" | .error => "error"
  | .warning => "warning" | .info => "info" | .unknown name => name

private partial def Expr.raw : Expr → String
  | .literal value => value
  | .variable name => "$(" ++ name.raw ++ ")"
  | .function fn args =>
      "$(" ++ functionName fn ++ " " ++ String.intercalate "," (args.toList.map Expr.raw) ++ ")"
  | .concat parts => String.join (parts.toList.map Expr.raw)

mutual

partial def expandExpr
    (settings : Settings)
    (environment : Environment)
    (expression : Expr)
    (stack : List String := [])
    (contributions : Array TargetContribution := #[]) : Array GuardedString :=
  match expression with
  | .literal value => #[{ value, condition := .top }]
  | .concat parts => concatAll <| parts.map fun part =>
      expandExpr settings environment part stack contributions
  | .variable nameExpression =>
      let names := expandExpr settings environment nameExpression stack contributions
      names.flatMap fun guardedName =>
        let name := guardedName.value
        if stack.contains name then
          #[]
        else
          match environment.get? name with
          | some stored =>
              (expandExpr settings environment stored.value (name :: stack) contributions).map fun value =>
                { value with condition := guardedName.condition.conj value.condition }
          | none =>
              let matching := contributions.filter (·.name == name)
              let anyActive := matching.foldl (init := Formula.bottom) fun condition contribution =>
                condition.disj contribution.condition
              let contributed : Array GuardedString :=
                (matching.map fun contribution => ({
                  value := contribution.value
                  condition := guardedName.condition.conj contribution.condition
                } : GuardedString)).push ({
                  value := ""
                  condition := guardedName.condition.conj anyActive.neg
                } : GuardedString)
              if !matching.isEmpty then contributed
              else if settings.isSymbol name then
                (settings.domainFor name).values.toArray.map fun value => {
                  value
                  condition := guardedName.condition.conj (.eq name value)
                }
              else
                #[{ value := "", condition := guardedName.condition }]
  | .function fn args => expandFunction settings environment fn args stack contributions

partial def expandFunction
    (settings : Settings)
    (environment : Environment)
    (fn : MakeFunction)
    (args : Array Expr)
    (stack : List String)
    (contributions : Array TargetContribution) : Array GuardedString :=
  if fn == .or then
    let rec expandOr (guard : Formula) : List Expr → Array GuardedString
      | [] => #[{ value := "", condition := guard }]
      | argument :: rest =>
          let values := expandExpr settings environment argument stack contributions
          let selected := values.filterMap fun value =>
            if (trimString value.value).isEmpty then none
            else some { value with condition := guard.conj value.condition }
          let emptyGuard := values.foldl (init := Formula.bottom) fun condition value =>
            if (trimString value.value).isEmpty then condition.disj value.condition else condition
          selected ++ expandOr (guard.conj emptyGuard) rest
    expandOr .top args.toList
  else if fn == .and then
    let rec expandAnd (guard : Formula) : List Expr → Array GuardedString
      | [] => #[{ value := "", condition := guard }]
      | argument :: rest =>
          (expandExpr settings environment argument stack contributions).flatMap fun value =>
            let condition := guard.conj value.condition
            if (trimString value.value).isEmpty then #[{ value := "", condition }]
            else if rest.isEmpty then #[{ value with condition }]
            else expandAnd condition rest
    expandAnd .top args.toList
  else if fn == .foreach then
    match args[0]?, args[1]?, args[2]? with
    | some variableArg, some listArg, some bodyArg =>
        let names := expandExpr settings environment variableArg stack contributions
        let lists := expandExpr settings environment listArg stack contributions
        (crossConcat names lists "\u0000").flatMap fun item =>
          match item.value.splitOn "\u0000" with
          | [name, values] =>
              (words values).foldl (init := #[{ value := "", condition := item.condition }])
                fun accumulated word =>
                  let loopEnv := environment.set (trimString name) ⟨.simple, .literal word⟩
                  crossConcat accumulated (expandExpr settings loopEnv bodyArg stack contributions) " "
              |>.map fun result => { result with value := trimString result.value }
          | _ => #[]
    | _, _, _ => #[]
  else if fn == .call then
    match args[0]? with
    | none => #[]
    | some nameArg =>
        (expandExpr settings environment nameArg stack contributions).flatMap fun guardedName =>
          let name := trimString guardedName.value
          match environment.get? name with
          | none => #[]
          | some storedMacro =>
              let indexed := (args.toList.drop 1).zip (List.range (args.size - 1))
              let environments := indexed.foldl
                (init := #[(environment.set "0" ⟨.simple, .literal name⟩, guardedName.condition)])
                fun alternatives (argument, zeroIndex) =>
                  let values := expandExpr settings environment argument stack contributions
                  alternatives.flatMap fun (callEnv, condition) =>
                    values.map fun value =>
                      (callEnv.set (toString (zeroIndex + 1)) ⟨.simple, .literal value.value⟩,
                        condition.conj value.condition)
              environments.flatMap fun (callEnv, condition) =>
                (expandExpr settings callEnv storedMacro.value (name :: stack) contributions).map fun value =>
                  { value with condition := condition.conj value.condition }
  else if fn == .value then
    match args[0]? with
    | none => #[]
    | some argument =>
        (expandExpr settings environment argument stack contributions).map fun guardedName =>
          let value := (environment.get? (trimString guardedName.value)).map (·.value.raw) |>.getD ""
          { guardedName with value }
  else if fn == .origin || fn == .flavor then
    match args[0]? with
    | none => #[]
    | some argument =>
        (expandExpr settings environment argument stack contributions).map fun guardedName =>
          let name := trimString guardedName.value
          let value := match environment.get? name with
            | none => "undefined"
            | some stored =>
                if fn == .origin then "file"
                else match stored.flavor with
                  | .recursive => "recursive"
                  | .simple => "simple"
          { guardedName with value }
  else if fn == .ifThenElse then
    match args[0]?, args[1]? with
    | some conditionArg, some thenArg =>
      let conditions := expandExpr settings environment conditionArg stack contributions
      conditions.flatMap fun condition =>
        let chosen := if (trimString condition.value).isEmpty then
          args[2]?.getD (.literal "")
        else thenArg
        (expandExpr settings environment chosen stack contributions).map fun value =>
          { value with condition := condition.condition.conj value.condition }
    | _, _ => #[]
  else if fn == .warning || fn == .info then
    let expanded := args.map fun arg => expandExpr settings environment arg stack contributions
    (concatAll expanded).map fun value => { value with value := "" }
  else
  let expanded := args.map fun arg => expandExpr settings environment arg stack contributions
  match fn, expanded.toList with
  | .subst, [fromValues, toValues, inputValues] =>
      (crossConcat (crossConcat fromValues toValues "\u0000") inputValues "\u0000").map fun item =>
        match item.value.splitOn "\u0000" with
        | [fromValue, toValue, inputValue] =>
            { item with value := inputValue.replace fromValue toValue }
        | _ => item
  | .addprefix, [prefixes, names] =>
      (crossConcat prefixes names "\u0000").map fun item =>
        match item.value.splitOn "\u0000" with
        | [pfx, names] => { item with value := joinWords <| words names |>.map (pfx ++ ·) }
        | _ => item
  | .addsuffix, [suffixes, names] =>
      (crossConcat suffixes names "\u0000").map fun item =>
        match item.value.splitOn "\u0000" with
        | [suffix, names] => { item with value := joinWords <| words names |>.map (· ++ suffix) }
        | _ => item
  | .patsubst, [patterns, replacements, inputs] =>
      (crossConcat (crossConcat patterns replacements "\u0000") inputs "\u0000").map fun item =>
        match item.value.splitOn "\u0000" with
        | [pattern, replacement, input] =>
            { item with value := substWords pattern replacement input }
        | _ => item
  | .filter, [patterns, inputs] =>
      (crossConcat patterns inputs "\u0000").map fun item =>
        match item.value.splitOn "\u0000" with
        | [patterns, input] => { item with value := filterWords patterns input true }
        | _ => item
  | .filterOut, [patterns, inputs] =>
      (crossConcat patterns inputs "\u0000").map fun item =>
        match item.value.splitOn "\u0000" with
        | [patterns, input] => { item with value := filterWords patterns input false }
        | _ => item
  | .strip, [values] => values.map fun item =>
      { item with value := joinWords (words item.value) }
  | .sort, [values] => values.map fun item =>
      { item with value := joinWords <| (words item.value).mergeSort |>.eraseDups }
  | .firstword, [values] => values.map fun item =>
      { item with value := (words item.value).head?.getD "" }
  | .lastword, [values] => values.map fun item =>
      { item with value := (words item.value).getLast?.getD "" }
  | .words, [values] => values.map fun item =>
      { item with value := toString (words item.value).length }
  | .word, [indices, values] =>
      (crossConcat indices values "\u0000").map fun item =>
        match item.value.splitOn "\u0000" with
        | [index, value] =>
            let selected := index.toNat?.bind fun number =>
              if number == 0 then none else (words value)[number - 1]?
            { item with value := selected.getD "" }
        | _ => item
  | .wordlist, [starts, stops, values] =>
      (crossConcat (crossConcat starts stops "\u0000") values "\u0000").map fun item =>
        match item.value.splitOn "\u0000" with
        | [start, stop, value] =>
            let selected := match start.toNat?, stop.toNat? with
              | some first, some last =>
                  if first == 0 then []
                  else (words value).drop (first - 1) |>.take (last - first + 1)
              | _, _ => []
            { item with value := joinWords selected }
        | _ => item
  | .dir, [values] => values.map fun item =>
      { item with value := joinWords <| (words item.value).map directoryPart }
  | .notdir, [values] => values.map fun item =>
      { item with value := joinWords <| (words item.value).map filePart }
  | .suffix, [values] => values.map fun item =>
      { item with value := joinWords <| (words item.value).map suffixPart |>.filter (!·.isEmpty) }
  | .basename, [values] => values.map fun item =>
      { item with value := joinWords <| (words item.value).map basenamePart }
  | .join, [lefts, rights] =>
      (crossConcat lefts rights "\u0000").map fun item =>
        match item.value.splitOn "\u0000" with
        | [left, right] =>
            let lhs := words left
            let rhs := words right
            let count := max lhs.length rhs.length
            let joined := (List.range count).map fun index =>
              lhs[index]?.getD "" ++ rhs[index]?.getD ""
            { item with value := joinWords joined }
        | _ => item
  | .wildcard, [patterns] => patterns.map fun item =>
      { item with value := wildcardPaths settings.filesystemPaths item.value }
  | .abspath, [values] => values.map fun item =>
      { item with value := joinWords <| (words item.value).map (absolutePath settings) }
  | .realpath, [values] => values.map fun item =>
      { item with value := joinWords <| (words item.value).filterMap fun value =>
          let absolute := absolutePath settings value
          if settings.filesystemPaths.contains absolute then some absolute else none }
  | _, _ => #[]

end

def expandText
    (settings : Settings)
    (environment : Environment)
    (expression : Expr) : Array GuardedString :=
  expandExpr settings environment expression

def expandTextWithContributions
    (settings : Settings)
    (environment : Environment)
    (contributions : Array TargetContribution)
    (expression : Expr) : Array GuardedString :=
  expandExpr settings environment expression [] contributions

end Skbuild
