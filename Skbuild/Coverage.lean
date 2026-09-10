import Skbuild.Analysis

namespace Skbuild

private def relativePath (root path : System.FilePath) : String :=
  let rootText := root.normalize.toString
  let pathText := path.normalize.toString
  let rootPrefix := if rootText.endsWith "/" then rootText else rootText ++ "/"
  if pathText.startsWith rootPrefix then (pathText.drop rootPrefix.length).toString else pathText

private def filesWithSuffixes
    (root : System.FilePath)
    (suffixes : List String) : IO (Except String (List String)) := do
  if !(← root.pathExists) then return .error s!"coverage directory does not exist: {root}"
  if !(← root.isDir) then return .error s!"coverage path is not a directory: {root}"
  let entries ← System.FilePath.walkDir root
  let mut files := []
  for path in entries do
    if !(← path.isDir) && suffixes.any (fun suffix => path.toString.endsWith suffix) then
      files := relativePath root path :: files
  return .ok files.mergeSort.eraseDups

private def coverageDiagnostic (code message path : String) (incomplete : Bool) : Diagnostic :=
  { code
    severity := if incomplete then .warning else .info
    message
    span := SourceSpan.unknown path
    makesIncomplete := incomplete }

def compareBuildDirectory
    (files : Array FilePresence)
    (buildRoot : System.FilePath) : IO (Except String (Array Diagnostic)) := do
  let scanned ← filesWithSuffixes buildRoot [".o"]
  let actual ← match scanned with
    | .ok files => pure files
    | .error message => return .error message
  let predicted := files.toList.map (·.path) |>.mergeSort |>.eraseDups
  let missing := predicted.filter fun path => !actual.contains path
  let unexpected := actual.filter fun path => !predicted.contains path
  return .ok <|
    (missing.map fun path => coverageDiagnostic "SKB4001"
      s!"predicted object was not found in build directory: {path}" path false).toArray ++
    (unexpected.map fun path => coverageDiagnostic "SKB4002"
      s!"built object was not predicted by Kbuild analysis: {path}" path true).toArray

private def objectPathForSource (source : String) : String :=
  match source.splitOn "." with
  | [] | [_] => source ++ ".o"
  | parts => String.intercalate "." parts.dropLast ++ ".o"

def findUnaccountedSources
    (files : Array FilePresence)
    (sourceRoot : System.FilePath) : IO (Except String (Array Diagnostic)) := do
  let scanned ← filesWithSuffixes sourceRoot [".c", ".cc", ".cpp", ".cxx", ".S", ".s"]
  let sources ← match scanned with
    | .ok files => pure files
    | .error message => return .error message
  let predicted := files.toList.map (·.path) |>.eraseDups
  let unaccounted := sources.filter fun source => !predicted.contains (objectPathForSource source)
  return .ok <| unaccounted.toArray.map fun source => coverageDiagnostic "SKB4003"
    s!"source has no predicted object: {source}" source true

end Skbuild
