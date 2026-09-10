import Skbuild.Analysis

namespace Skbuild

structure ConcreteConfig where
  assignments : List (String × String) := []
  deriving Repr, Inhabited

private def trimString (value : String) : String := value.trimAscii.toString

private def unquote (value : String) : String :=
  if value.length >= 2 &&
      ((value.startsWith "\"" && value.endsWith "\"") ||
       (value.startsWith "'" && value.endsWith "'")) then
    (value.drop 1 |>.dropEnd 1).toString
  else value

private def splitAssignment (line : String) : Option (String × String) :=
  match line.splitOn "=" with
  | [] | [_] => none
  | name :: values => some (trimString name, unquote <| trimString <| String.intercalate "=" values)

def ConcreteConfig.parse (contents : String) : Except String ConcreteConfig := do
  let mut assignments : List (String × String) := []
  for rawLine in contents.splitOn "\n" do
    let line := trimString rawLine
    if line.isEmpty then continue
    if line.startsWith "# CONFIG_" && line.endsWith " is not set" then
      let name := (line.drop 2 |>.dropEnd 11).toString
      assignments := (name, "") :: assignments
    else if line.startsWith "#" then
      continue
    else if let some (name, value) := splitAssignment line then
      if name.isEmpty then throw s!"invalid empty configuration name in '{line}'"
      assignments := (name, value) :: assignments
  return { assignments := assignments.reverse }

def ConcreteConfig.load (path : System.FilePath) : IO (Except String ConcreteConfig) := do
  if !(← path.pathExists) then return .error s!"configuration does not exist: {path}"
  return ConcreteConfig.parse (← IO.FS.readFile path)

def ConcreteConfig.value (config : ConcreteConfig) (symbol : String) : String :=
  match config.assignments.find? (·.1 == symbol) with
  | some (_, value) => value
  | none => ""

def ConcreteConfig.selectFiles
    (config : ConcreteConfig)
    (files : Array FilePresence) : Array FilePresence :=
  files.filter fun file => file.condition.eval config.value

end Skbuild
