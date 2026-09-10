import Skbuild.Report
import Skbuild.Kbuild

namespace Skbuild

open Lean

def cacheSchema : Nat := 2

private def isAnalysisInput (path : System.FilePath) : Bool :=
  let name := path.fileName.getD ""
  name == "Makefile" || name == "Kbuild" || name == "skbuild.ini" ||
    name.endsWith ".mk" || name.endsWith ".mak"

def inputFingerprint (input : System.FilePath) (settings : Settings) : IO (Except String String) := do
  if !(← input.pathExists) then return .error s!"input does not exist: {input}"
  let analysisPaths ← if ← input.isDir then
      pure <| (← System.FilePath.walkDir input).toList.filter isAnalysisInput |>.mergeSort
        (fun left right => left.toString < right.toString)
    else pure [input]
  let inputBase := if ← input.isDir then input else input.parent.getD (System.FilePath.mk ".")
  let sourceRoot ← discoverSourceRoot (← IO.FS.realPath inputBase)
  let filesystemPaths := (← System.FilePath.walkDir sourceRoot).toList.map (·.normalize.toString)
    |>.mergeSort |>.eraseDups
  let fingerprintSettings := { settings with filesystemPaths := [] }
  let mut digest := hash (reprStr fingerprintSettings)
  for path in filesystemPaths do
    digest := mixHash digest <| hash path
  for path in analysisPaths do
    let contents ← IO.FS.readFile path
    digest := mixHash digest <| hash (path.normalize.toString, contents)
  return .ok (toString digest)

def loadCache
    (path : System.FilePath)
    (fingerprint : String) : IO (Option (Array FilePresence × Array Diagnostic)) := do
  if !(← path.pathExists) then return none
  let contents ← IO.FS.readFile path
  let .ok json := Json.parse contents | return none
  let .ok schemaJson := json.getObjVal? "cache_schema" | return none
  let .ok schema := schemaJson.getNat? | return none
  if schema != cacheSchema then return none
  let .ok fingerprintJson := json.getObjVal? "fingerprint" | return none
  let .ok storedFingerprint := fingerprintJson.getStr? | return none
  if storedFingerprint != fingerprint then return none
  let .ok report := json.getObjVal? "report" | return none
  match decodeReport report with
  | .ok result => return some result
  | .error _ => return none

def saveCache
    (path : System.FilePath)
    (fingerprint : String)
    (files : Array FilePresence)
    (diagnostics : Array Diagnostic) : IO Unit := do
  if let some parent := path.parent then IO.FS.createDirAll parent
  let value := Json.mkObj [
    ("cache_schema", toJson cacheSchema),
    ("fingerprint", fingerprint),
    ("report", reportJson files diagnostics)
  ]
  IO.FS.writeFile path value.pretty

end Skbuild
