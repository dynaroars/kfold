import Skbuild.Analysis
import Skbuild.Kbuild

namespace Skbuild

open Logic

structure AnalyzedMakefile where
  path : System.FilePath
  condition : Formula
  execution : Execution
  deriving Repr

structure TreeAnalysis where
  makefiles : Array AnalyzedMakefile := #[]
  files : Array FilePresence := #[]
  diagnostics : Array Diagnostic := #[]
  deriving Repr, Inhabited

private structure WorkItem where
  path : System.FilePath
  condition : Formula
  deriving Repr, Inhabited

private def relativeDirectory (root current : System.FilePath) : String :=
  let rootText := root.normalize.toString
  let currentText := current.normalize.toString
  if currentText == rootText then ""
  else
    let rootPrefix := if rootText.endsWith "/" then rootText else rootText ++ "/"
    if currentText.startsWith rootPrefix then
      let relative := (currentText.drop rootPrefix.length).toString
      if relative.isEmpty then ""
      else if relative.endsWith "/" then relative else relative ++ "/"
    else ""

private def prefixFiles (directory : String) (files : Array FilePresence) : Array FilePresence :=
  if directory.isEmpty then files
  else files.map fun file => { file with path := directory ++ file.path }

def findMakefile (path : System.FilePath) : IO (Option System.FilePath) := do
  if !(← path.pathExists) then return none
  if !(← path.isDir) then return some path.normalize
  let kbuild := path / "Kbuild"
  if ← kbuild.pathExists then return some kbuild.normalize
  let makefile := path / "Makefile"
  if ← makefile.pathExists then return some makefile.normalize
  return none

def analyzeTree (settings : Settings) (root : System.FilePath) : IO (Except String TreeAnalysis) := do
  let some first ← findMakefile root
    | return .error s!"no Kbuild or Makefile found at {root}"
  let first ← IO.FS.realPath first
  let rootBase := first.parent.getD (System.FilePath.mk ".") |>.normalize
  let sourceRoot ← discoverSourceRoot rootBase
  let filesystemPaths ← captureFilesystem sourceRoot
  let settings := { settings with
    filesystemPaths
    workingDirectory := sourceRoot.toString
  }
  let mut result : TreeAnalysis := {}
  let mut queue : Array WorkItem := #[{ path := first, condition := .top }]
  for directory in settings.topDirectories do
    let childDirectory := resolveFilePath rootBase directory
    match ← findMakefile childDirectory with
    | some makefile => queue := queue.push { path := makefile, condition := .top }
    | none =>
        result := { result with diagnostics := result.diagnostics.push {
          code := "SKB3001"
          severity := .warning
          message := s!"configured Kbuild directory has no Kbuild or Makefile: {childDirectory}"
          span := SourceSpan.unknown first.toString
          makesIncomplete := true
        } }
  let mut cursor := 0
  let mut visited : List String := []
  while cursor < queue.size do
    let item := queue[cursor]!
    cursor := cursor + 1
    let canonicalCondition := item.condition.canonicalize fun symbol =>
      (settings.domainFor symbol).values
    let key := item.path.toString ++ "\u0000" ++ canonicalCondition.render
    if visited.contains key then continue
    visited := key :: visited
    let base := item.path.parent.getD (System.FilePath.mk ".")
    let sourceRelative := relativeDirectory sourceRoot base
    let sourceName := if sourceRelative.isEmpty then "." else (sourceRelative.dropEnd 1).toString
    let environment := automaticEnvironment sourceRoot sourceName
    match ← analyzeFile settings item.path canonicalCondition (some environment) (some sourceRoot) with
    | .error message =>
        -- A single unsupported or malformed child Makefile must not discard
        -- the valid portion of a recursive report. Preserve the analyzed
        -- prefix and make the skipped input explicit in the report.
        result := { result with diagnostics := result.diagnostics.push {
          code := "SKB2005"
          severity := .warning
          message := s!"cannot analyze {item.path}: {message}"
          span := SourceSpan.unknown item.path.toString
          makesIncomplete := true
        } }
    | .ok execution =>
        let localFiles := prefixFiles (relativeDirectory rootBase base) <|
          extractFiles settings execution
        result := {
          makefiles := result.makefiles.push {
            path := item.path, condition := canonicalCondition, execution
          }
          files := result.files ++ localFiles
          diagnostics := result.diagnostics ++ execution.diagnostics
        }
        for directory in extractDirectories settings execution do
          let childDirectory := resolveFilePath base directory.path
          match ← findMakefile childDirectory with
          | some makefile =>
              let childCondition := canonicalCondition.conj directory.condition
              match (queue.extract cursor queue.size).findIdx? (·.path == makefile) with
              | some pendingIndex =>
                  let index := cursor + pendingIndex
                  let pending := queue[index]!
                  queue := queue.set! index { pending with
                    condition := pending.condition.disj childCondition
                  }
              | none => queue := queue.push { path := makefile, condition := childCondition }
          | none =>
              result := { result with diagnostics := result.diagnostics.push {
                code := "SKB3001"
                severity := .warning
                message := s!"referenced Kbuild directory has no Kbuild or Makefile: {childDirectory}"
                span := SourceSpan.unknown item.path.toString
                makesIncomplete := true
              } }
  let files := mergeFilePresence result.files |>.map fun item => { item with
    condition := item.condition.canonicalize fun symbol => (settings.domainFor symbol).values
  }
  return .ok { result with files }

end Skbuild
