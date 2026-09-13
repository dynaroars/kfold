import Skbuild.Config

namespace Skbuild.Settings

private def trimString (text : String) : String := text.trimAscii.toString

private def words (text : String) : List String :=
  text.splitOn " " |>.map trimString |>.filter (not ∘ String.isEmpty)

private def splitOnce (text token : String) : Option (String × String) :=
  match text.splitOn token with
  | [] | [_] => none
  | first :: rest => some (first, String.intercalate token rest)

private def parseBool (value : String) : Option Bool :=
  match value.toLower with
  | "1" | "yes" | "true" | "on" => some true
  | "0" | "no" | "false" | "off" => some false
  | _ => none

private def setExtraDomain
    (settings : Settings)
    (name : String)
    (domain : Domain) : Settings :=
  { settings with
    extraDomains := (name, domain) :: settings.extraDomains.filter (·.1 != name) }

def parse (contents : String) : Except String Settings := do
  let mut settings : Settings := {}
  let mut currentSection := ""
  let mut lineNumber := 0
  for rawLine in contents.splitOn "\n" |>.toArray do
    lineNumber := lineNumber + 1
    let line := trimString rawLine
    if line.isEmpty || line.startsWith "#" || line.startsWith ";" then continue
    if line.startsWith "[" && line.endsWith "]" then
      currentSection := (line.drop 1 |>.dropEnd 1).toString.toUpper
      continue
    let some (rawName, rawValue) := splitOnce line "="
      | throw s!"settings line {lineNumber}: expected key=value"
    let name := trimString rawName
    let value := trimString rawValue
    if currentSection == "COMMON" || currentSection == "DEFAULT" then
      match name with
      | "use_tristate" =>
          match parseBool value with
          | some true => settings := { settings with defaultConfigDomain := .tristate }
          | some false => settings := { settings with defaultConfigDomain := .boolean }
          | none => throw s!"settings line {lineNumber}: invalid boolean '{value}'"
      | "config_prefix" => settings := { settings with configPrefix := value }
      | "target_vars" => settings := { settings with targetPrefixes := words value }
      | "top_dirs" => settings := { settings with topDirectories := words value }
      | "ignore_dirs" => settings := { settings with ignoredDirectories := words value }
      | "ignore_files" => settings := { settings with ignoredFiles := words value }
      | _ => pure ()
    else if currentSection == "COPTIONS" then
      let values := words value |>.map fun item => if item == "None" then "" else item
      if values.isEmpty then
        throw s!"settings line {lineNumber}: domain for {name} is empty"
      settings := setExtraDomain settings name { values }
  return settings

def load (path : System.FilePath) : IO (Except String Settings) := do
  if !(← path.pathExists) then return .ok {}
  parse <$> IO.FS.readFile path

def loadForInput (input : System.FilePath) : IO (Except String Settings) := do
  let base := if ← input.isDir then input else input.parent.getD (System.FilePath.mk ".")
  let config := base / "skbuild.ini"
  if ← config.pathExists then load config else pure <| .ok {}

end Skbuild.Settings
