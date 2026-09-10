import Skbuild.Config
import Skbuild.Expansion
import Skbuild.Syntax

namespace Skbuild

partial def Expr.staticText? : Expr → Option String
  | .literal value => some value
  | .concat parts =>
      parts.foldl (init := some "") fun result part => do
        let before ← result
        let value ← part.staticText?
        pure (before ++ value)
  | .variable _ | .function _ _ => none

private partial def Statement.assignsStaticName (wanted : String) : Statement → Bool
  | .assignment name _ _ _ _ => name.staticText? == some wanted
  | .conditional branches _ => branches.any fun branch =>
      branch.statements.any (Statement.assignsStaticName wanted)
  | _ => false

def Makefile.assignsStaticName (makefile : Makefile) (name : String) : Bool :=
  makefile.statements.any (Statement.assignsStaticName name)

partial def Expr.references : Expr → List String
  | .literal _ => []
  | .variable name =>
      let nested := name.references
      match name.staticText? with
      | some value => value :: nested
      | none => nested
  | .function fn args =>
      let nested := args.toList.flatMap Expr.references
      let named := if fn == .origin || fn == .flavor || fn == .value || fn == .call then
        args[0]?.bind Expr.staticText? |>.toList
      else []
      (named ++ nested).eraseDups
  | .concat args => args.toList.flatMap Expr.references |>.eraseDups

private def Condition.references : Condition → List String
  | .equals left right _ => (left.references ++ right.references).eraseDups
  | .defined name _ => name.references
  | .otherwise => []

def Expr.mayNameTarget (settings : Settings) (expression : Expr) : Bool :=
  match expression.staticText? with
  | some name => settings.isTarget name
  | none =>
      match expression with
      | .concat parts =>
          match parts[0]? with
          | some first =>
              match first with
              | .literal literalPrefix =>
                  settings.targetPrefixes.any fun targetPrefix => literalPrefix.startsWith targetPrefix
              | _ => false
          | _ => false
      | _ => false

def Expr.leadingLiteral? : Expr → Option String
  | .literal value => some value
  | .concat parts =>
      match parts[0]? with
      | some first =>
          match first with
          | .literal value => some value
          | _ => none
      | _ => none
  | _ => none

private partial def Statement.dynamicOverwritePrefixes : Statement → List String
  | .assignment name operator _ _ _ =>
      if operator != .append && name.staticText?.isNone then name.leadingLiteral?.toList else []
  | .conditional branches _ => branches.toList.flatMap fun branch =>
      branch.statements.toList.flatMap Statement.dynamicOverwritePrefixes
  | _ => []

private partial def Statement.allReferences : Statement → List String
  | .assignment name _ value target _ =>
      name.references ++ value.references ++ (target.map Expr.references).getD []
  | .conditional branches _ => branches.toList.flatMap fun branch =>
      branch.condition.references ++ branch.statements.toList.flatMap Statement.allReferences
  | .include paths _ _ => paths.references
  | .expression value _ => value.references
  | .rule _ _ | .command _ _ => []

def Settings.forMakefile (settings : Settings) (makefile : Makefile) : Settings :=
  let settings :=
    if makefile.assignsStaticName "BITS" || settings.extraDomains.any (·.1 == "BITS") then settings
    else { settings with
      extraDomains := ("BITS", { values := ["32", "64"] }) :: settings.extraDomains }
  let prefixes := makefile.statements.toList.flatMap Statement.dynamicOverwritePrefixes
  let references := makefile.statements.toList.flatMap Statement.allReferences |>.eraseDups
  let streamable := prefixes.filter fun pfx =>
    (prefixes.filter (· == pfx)).length > 1 ||
      !(references.contains (pfx ++ "y") && references.contains (pfx ++ "m"))
  { settings with streamedOverwritePrefixes := streamable.eraseDups }

def Expr.isBuildListName (settings : Settings) (expression : Expr) : Bool :=
  expression.mayNameTarget settings ||
    match expression.staticText? with
    | some name => name.endsWith "-y" || name.endsWith "-m" || name.endsWith "-objs"
    | none =>
        match expression.leadingLiteral? with
        | some value => value.contains '-'
        | none => false

private partial def Expr.objectDependencies : Expr → List String
  | .literal value =>
      value.split Char.isWhitespace |>.map String.Slice.toString |>.toList |>.flatMap fun word =>
        if word.endsWith ".o" then
          let stem := (word.dropEnd 2).toString
          [stem ++ "-y", stem ++ "-m", stem ++ "-objs"]
        else []
  | .variable _ => []
  | .function _ args | .concat args => args.toList.flatMap Expr.objectDependencies |>.eraseDups

private def assignmentRelevant
    (settings : Settings)
    (needed : List String)
    (name : Expr) : Bool :=
  name.mayNameTarget settings ||
    match name.staticText? with
    | some value => needed.contains value
    | none =>
        match name.leadingLiteral? with
        | some namePrefix => needed.any fun value => value.startsWith namePrefix
        | none => true

mutual
  private partial def Statement.contributes
      (settings : Settings) (needed : List String) : Statement → Bool
    | .assignment name _ _ _ _ => assignmentRelevant settings needed name
    | .conditional branches _ => branches.any fun branch =>
        branch.statements.any (Statement.contributes settings needed)
    | .include _ _ _ | .expression _ _ => true
    | .rule _ _ | .command _ _ => false

  private partial def discoverStatement
      (settings : Settings) (needed : List String) : Statement → List String
    | .assignment name _ value target _ =>
        if assignmentRelevant settings needed name then
          needed ++ name.references ++ value.references ++
            value.objectDependencies ++ (target.map Expr.references).getD []
        else needed
    | .conditional branches _ =>
        if branches.any fun branch => branch.statements.any (Statement.contributes settings needed) then
          branches.foldl (init := needed) fun result branch =>
            branch.statements.foldl (discoverStatement settings) <|
              result ++ branch.condition.references
        else needed
    | .include paths _ _ => needed ++ paths.references
    | .expression value _ => needed ++ value.references
    | .rule _ _ | .command _ _ => needed
end

private def discoverPass
    (settings : Settings)
    (statements : Array Statement)
    (needed : List String) : List String :=
  statements.foldl (discoverStatement settings) needed |>.eraseDups

private partial def dependencyClosure
    (settings : Settings)
    (statements : Array Statement)
    (needed : List String := []) : List String :=
  let next := discoverPass settings statements needed
  if next.length == needed.length then next else dependencyClosure settings statements next

mutual
  private partial def reduceStatement
      (settings : Settings) (needed : List String) : Statement → Option Statement
    | statement@(.assignment name _ _ _ _) =>
        if assignmentRelevant settings needed name then some statement else none
    | .conditional branches span =>
        let reduced := branches.map fun branch =>
          { branch with statements := reduceStatementsWith settings needed branch.statements }
        if reduced.any fun branch => !branch.statements.isEmpty then
          some (.conditional reduced span)
        else none
    | statement@(.include _ _ _) | statement@(.expression _ _) => some statement
    | .rule _ _ | .command _ _ => none

  private partial def reduceStatementsWith
      (settings : Settings)
      (needed : List String)
      (statements : Array Statement) : Array Statement :=
    statements.filterMap (reduceStatement settings needed)
end

def reduceMakefile (settings : Settings) (makefile : Makefile) : Makefile :=
  let needed := dependencyClosure settings makefile.statements
  { makefile with statements := reduceStatementsWith settings needed makefile.statements }

mutual
  private partial def buildListAssignments : Statement → List (Expr × AssignOp × Expr)
    | .assignment name operator value _ _ => [(name, operator, value)]
    | .conditional branches _ => branches.toList.flatMap fun branch =>
        branch.statements.toList.flatMap buildListAssignments
    | _ => []
end

def Makefile.canStreamTargets (settings : Settings) (makefile : Makefile) : Bool :=
  let assignments := makefile.statements.toList.flatMap buildListAssignments
  let possibleNames (expression : Expr) : Option (Array String) :=
    match expression.staticText? with
    | some name => some #[name]
    | none =>
        let names := (expandText settings [] expression).map (·.value) |>.filter (not ∘ String.isEmpty)
          |>.toList.eraseDups.toArray
        if names.isEmpty then none else some names
  let overlaps (left right : Expr) : Bool :=
    match possibleNames left, possibleNames right with
    | some lhs, some rhs => lhs.any fun leftName => rhs.contains leftName
    | _, _ =>
      match left.leadingLiteral?, right.leadingLiteral? with
      | some lhs, some rhs => lhs.startsWith rhs || rhs.startsWith lhs
      | _, _ => true
  let rec safe : List (Expr × AssignOp × Expr) → Bool
    | [] => true
    | (name, operator, _) :: rest =>
        if name.mayNameTarget settings && operator == .append then
          !rest.any (fun (laterName, laterOperator, _) =>
              laterName.mayNameTarget settings && laterOperator != .append && overlaps name laterName) &&
            safe rest
        else safe rest
  safe assignments

end Skbuild
