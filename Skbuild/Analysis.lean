import Skbuild.Semantics
import Skbuild.Logic.Canonical

namespace Skbuild

open Logic

inductive TargetKind
  | builtIn
  | module
  | library
  deriving Repr, BEq, DecidableEq, Inhabited

def TargetKind.render : TargetKind → String
  | .builtIn => "built-in"
  | .module => "module"
  | .library => "library"

structure FilePresence where
  path : String
  target : TargetKind
  condition : Formula
  deriving Repr, BEq, Inhabited

def targetKind? (name : String) : Option TargetKind :=
  if name == "obj-y" then some .builtIn
  else if name == "obj-m" then some .module
  else if name == "lib-y" || name == "lib-m" then some .library
  else none

def mergeFilePresence (items : Array FilePresence) : Array FilePresence := Id.run do
  let mut output := #[]
  for item in items do
    match output.findIdx? fun prior => prior.path == item.path && prior.target == item.target with
    | some index =>
        let prior := output[index]!
        output := output.set! index { prior with
          condition := prior.condition.disj item.condition
        }
    | none => output := output.push item
  return output

private partial def expandComposite
    (contributions : Array TargetContribution)
    (target : TargetKind)
    (word : String)
    (condition : Formula)
    (stack : List String := []) : Array FilePresence :=
  if !word.endsWith ".o" then #[]
  else
    let direct : Array FilePresence := #[{ path := word, target, condition }]
    let stem := (word.dropEnd 2).toString
    if stack.contains stem then direct
    else
      let members := contributions.flatMap fun contribution =>
        if contribution.name == stem ++ "-y" || contribution.name == stem ++ "-m" ||
            contribution.name == stem ++ "-objs" then
          let memberWords : Array String :=
            (contribution.value.split Char.isWhitespace).map String.Slice.toString |>.toArray |>.filter
              (not ∘ String.isEmpty)
          memberWords.flatMap fun member =>
            expandComposite contributions target member
              (condition.conj contribution.condition) (stem :: stack)
        else #[]
      direct ++ members

def extractFiles (settings : Settings) (execution : Execution) : Array FilePresence :=
  let storedContributions := execution.paths.flatMap fun path =>
    path.environment.toArray.flatMap fun (name, stored) =>
      if !(name.endsWith "-y" || name.endsWith "-m" || name.endsWith "-objs") then #[]
      else (expandTextWithContributions settings path.environment
          execution.targetContributions stored.value).map fun expanded => {
        name
        value := expanded.value
        condition := path.condition.conj expanded.condition
      }
  let allContributions := execution.targetContributions ++ storedContributions
  let streamed := allContributions.flatMap fun contribution =>
    match targetKind? contribution.name with
    | none => #[]
    | some target =>
        (contribution.value.splitOn " ").toArray.flatMap fun file =>
          expandComposite allContributions target file contribution.condition
  let merged := mergeFilePresence <| streamed ++ execution.paths.flatMap fun path =>
    path.environment.toArray.flatMap fun (name, stored) =>
      match targetKind? name with
      | none => #[]
      | some target =>
          (expandText settings path.environment stored.value).flatMap fun expanded =>
            let condition := path.condition.conj expanded.condition
            if condition.isSatisfiable fun symbol => (settings.domainFor symbol).values then
              (expanded.value.splitOn " ").toArray.filterMap fun file =>
                if file.endsWith ".o" then some { path := file, target, condition }
                else none
            else #[]
  merged.map fun item => { item with
    condition := item.condition.canonicalize fun symbol => (settings.domainFor symbol).values
  }

structure DirectoryPresence where
  path : String
  condition : Formula
  deriving Repr, BEq, Inhabited

def mergeDirectoryPresence (items : Array DirectoryPresence) : Array DirectoryPresence := Id.run do
  let mut output := #[]
  for item in items do
    match output.findIdx? fun prior => prior.path == item.path with
    | some index =>
        let prior := output[index]!
        output := output.set! index { prior with
          condition := prior.condition.disj item.condition
        }
    | none => output := output.push item
  return output

def extractDirectories (settings : Settings) (execution : Execution) : Array DirectoryPresence :=
  let streamed := execution.targetContributions.flatMap fun contribution =>
    if !(targetKind? contribution.name).isSome then #[]
    else (contribution.value.splitOn " ").toArray.filterMap fun directory =>
      if directory.endsWith "/" then some { path := directory, condition := contribution.condition }
      else none
  let merged := mergeDirectoryPresence <| streamed ++ execution.paths.flatMap fun path =>
    path.environment.toArray.flatMap fun (name, stored) =>
      if !(targetKind? name).isSome then #[]
      else
        (expandText settings path.environment stored.value).flatMap fun expanded =>
          let condition := path.condition.conj expanded.condition
          if feasible settings condition then
            (expanded.value.splitOn " ").toArray.filterMap fun directory =>
              if directory.endsWith "/" then some { path := directory, condition }
              else none
          else #[]
  merged.map fun item => { item with
    condition := item.condition.canonicalize fun symbol => (settings.domainFor symbol).values
  }

def renderReport (files : Array FilePresence) : String :=
  String.intercalate "\n" <| files.toList.mergeSort (fun left right =>
    left.path < right.path || (left.path == right.path && left.target.render < right.target.render)) |>.map fun file =>
    s!"{file.path}\t{file.target.render}\t{file.condition.render}"

end Skbuild
