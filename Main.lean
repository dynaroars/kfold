import Skbuild

def usage : String := "skbuild: Lean Kbuild analyzer\nusage: skbuild [--tristate] [--json] [--parse-only|--batch-check] [--no-recursive] [--config=PATH] [--build-dir=PATH] [--src-dir=PATH] [--cache=PATH] <Makefile|Kbuild|ast.json>..."

private def parseOnlyFiles (paths : List String) (jsonOutput : Bool) : IO UInt32 := do
  if paths.isEmpty then
    IO.eprintln usage
    return 2
  for path in paths do
    if path.endsWith ".json" then
      IO.eprintln s!"{path}: --parse-only expects Makefile/Kbuild source"
      return 2
    match ← Skbuild.Parser.parseFile (System.FilePath.mk path) with
    | .error message =>
        IO.eprintln message
        return 2
    | .ok makefile =>
        let diagnostics := Skbuild.validateMakefile makefile
        let reduced := Skbuild.reduceMakefile {} makefile
        if jsonOutput then
          IO.println <| Lean.Json.compress <| .mkObj [
            ("schema", 1),
            ("source", path),
            ("statements", makefile.statements.size),
            ("reduced_statements", reduced.statements.size),
            ("stream_targets", reduced.canStreamTargets {}),
            ("diagnostics", diagnostics.size),
            ("diagnostic_codes", Lean.Json.arr <| diagnostics.map fun item => item.code),
            ("diagnostic_details", Lean.Json.arr <| diagnostics.map Skbuild.diagnosticJson)
          ]
        else
          IO.println s!"{path}: parsed {makefile.statements.size} statements, {diagnostics.size} diagnostics"
  return 0

private def batchCheckFiles
    (paths : List String)
    (forceTristate jsonOutput : Bool) : IO UInt32 := do
  if paths.isEmpty then
    IO.eprintln usage
    return 2
  let mut snapshots : List (String × List String) := []
  for path in paths do
    if path.endsWith ".json" then
      IO.eprintln s!"{path}: --batch-check expects Makefile/Kbuild source"
      return 2
    let input := System.FilePath.mk path
    let some makefilePath ← Skbuild.findMakefile input
      | IO.eprintln s!"{path}: no Kbuild or Makefile found"
        return 2
    let resolved ← IO.FS.realPath makefilePath
    let base := resolved.parent.getD (System.FilePath.mk ".")
    let sourceRoot ← Skbuild.discoverSourceRoot base
    let rootName := sourceRoot.toString
    let filesystemPaths ← match snapshots.find? (·.1 == rootName) with
      | some (_, captured) => pure captured
      | none =>
          let captured ← Skbuild.captureFilesystem sourceRoot
          snapshots := (rootName, captured) :: snapshots
          pure captured
    let loaded ← Skbuild.Settings.loadForInput input
    let settings ← match loaded with
      | .error message =>
          IO.eprintln s!"{path}: invalid skbuild.ini: {message}"
          return 2
      | .ok value => pure <| {
          value with
          defaultConfigDomain := if forceTristate then .tristate else value.defaultConfigDomain
          filesystemPaths
          workingDirectory := rootName
        }
    match ← Skbuild.analyzeFile settings resolved .top none (some sourceRoot) with
    | .error message =>
        IO.eprintln s!"{path}: {message}"
        return 2
    | .ok execution =>
        let files := Skbuild.extractFiles settings execution
        if jsonOutput then
          IO.println <| Lean.Json.compress <| .mkObj [
            ("source", path),
            ("files", files.size),
            ("diagnostics", execution.diagnostics.size),
            ("diagnostic_codes", Lean.Json.arr <|
              execution.diagnostics.map fun item => item.code),
            ("diagnostic_details", Lean.Json.arr <|
              execution.diagnostics.map Skbuild.diagnosticJson)
          ]
        else
          IO.println s!"{path}: analyzed {files.size} files, {execution.diagnostics.size} diagnostics"
  return 0

def main (args : List String) : IO UInt32 := do
  let forceTristate := args.contains "--tristate"
  let jsonOutput := args.contains "--json"
  let parseOnly := args.contains "--parse-only"
  let batchCheck := args.contains "--batch-check"
  let noRecursive := args.contains "--no-recursive"
  let configPath := args.find? (fun arg => arg.startsWith "--config=") |>.map fun arg =>
    (arg.drop 9).toString
  let buildPath := args.find? (fun arg => arg.startsWith "--build-dir=") |>.map fun arg =>
    (arg.drop 12).toString
  let sourcePath := args.find? (fun arg => arg.startsWith "--src-dir=") |>.map fun arg =>
    (arg.drop 10).toString
  let cachePath := args.find? (fun arg => arg.startsWith "--cache=") |>.map fun arg =>
    (arg.drop 8).toString
  let remaining := args.filter fun arg =>
    arg != "--tristate" && arg != "--json" && arg != "--parse-only" && arg != "--batch-check" &&
      arg != "--no-recursive" &&
      !arg.startsWith "--config="
      && !arg.startsWith "--build-dir=" && !arg.startsWith "--src-dir=" &&
      !arg.startsWith "--cache="
  if parseOnly then
    return ← parseOnlyFiles remaining jsonOutput
  if batchCheck then
    return ← batchCheckFiles remaining forceTristate jsonOutput
  match remaining with
  | [path] =>
      let inputPath := System.FilePath.mk path
      let loadedSettings ← Skbuild.Settings.loadForInput inputPath
      let settings ← match loadedSettings with
        | .error message =>
            IO.eprintln s!"{path}: invalid skbuild.ini: {message}"
            return 2
        | .ok value => pure <| if forceTristate then
            { value with defaultConfigDomain := .tristate }
          else value
      let fingerprint ← match cachePath with
        | none => pure none
        | some _ =>
            match ← Skbuild.inputFingerprint inputPath settings with
            | .error message =>
                IO.eprintln message
                return 2
            | .ok value => pure (some value)
      let cached ← match cachePath, fingerprint with
        | some cacheName, some value =>
            Skbuild.loadCache (System.FilePath.mk cacheName) value
        | _, _ => pure none
      let analyzed : Except String (Array Skbuild.FilePresence × Array Skbuild.Diagnostic) ←
        if let some result := cached then pure <| .ok result
        else if path.endsWith ".json" then do
          let contents ← IO.FS.readFile path
          let decoded : Except String Skbuild.Makefile :=
          match Lean.Json.parse contents with
          | .error error => .error s!"invalid JSON: {error}"
          | .ok json => Skbuild.decodeMakefile json
          pure <| decoded.map fun makefile =>
            let execution := Skbuild.executeMakefile settings makefile
            (Skbuild.extractFiles settings execution, execution.diagnostics)
        else if noRecursive then
          match ← Skbuild.findMakefile inputPath with
          | none => pure <| .error s!"no Kbuild or Makefile found at {inputPath}"
          | some makefilePath =>
              match ← Skbuild.analyzeFile settings makefilePath with
              | .error message => pure <| Except.error message
              | .ok execution =>
                  let result := (Skbuild.extractFiles settings execution, execution.diagnostics)
                  pure (Except.ok result)
        else
          match ← Skbuild.analyzeTree settings inputPath with
          | .error message => pure <| .error message
          | .ok tree => pure <| .ok (tree.files, tree.diagnostics)
      match analyzed with
          | .error error =>
              IO.eprintln s!"{path}: {error}"
              return 2
          | .ok (files, diagnostics) =>
              if cached.isNone then
                match cachePath, fingerprint with
                | some cacheName, some value =>
                    Skbuild.saveCache (System.FilePath.mk cacheName) value files diagnostics
                | _, _ => pure ()
              let files ← match configPath with
                | none => pure files
                | some configName =>
                    match ← Skbuild.ConcreteConfig.load (System.FilePath.mk configName) with
                    | .error message =>
                        IO.eprintln message
                        return 2
                    | .ok config => pure <| config.selectFiles files
              let diagnostics ← match buildPath with
                | none => pure diagnostics
                | some directory =>
                    match ← Skbuild.compareBuildDirectory files (System.FilePath.mk directory) with
                    | .error message =>
                        IO.eprintln message
                        return 2
                    | .ok coverage => pure <| diagnostics ++ coverage
              let diagnostics ← match sourcePath with
                | none => pure diagnostics
                | some directory =>
                    match ← Skbuild.findUnaccountedSources files (System.FilePath.mk directory) with
                    | .error message =>
                        IO.eprintln message
                        return 2
                    | .ok coverage => pure <| diagnostics ++ coverage
              if jsonOutput then
                IO.println <| Skbuild.renderJsonReport files diagnostics
              else
                IO.println <| Skbuild.renderReport files
              for diagnostic in diagnostics do
                IO.eprintln s!"{diagnostic.code}: {diagnostic.message}"
              return 0
  | _ =>
      IO.eprintln usage
      return 2
