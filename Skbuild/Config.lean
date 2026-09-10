namespace Skbuild

structure Domain where
  values : List String
  deriving Repr, BEq

namespace Domain

def boolean : Domain := { values := ["y", ""] }

def tristate : Domain := { values := ["y", "m", ""] }

end Domain

structure Settings where
  configPrefix : String := "CONFIG_"
  defaultConfigDomain : Domain := Domain.boolean
  extraDomains : List (String × Domain) := []
  targetPrefixes : List String := ["obj-", "lib-"]
  topDirectories : List String := []
  ignoredDirectories : List String := []
  ignoredFiles : List String := []
  streamedOverwritePrefixes : List String := []
  filesystemPaths : List String := []
  workingDirectory : String := ""
  deriving Repr, BEq

def Settings.isSymbol (settings : Settings) (name : String) : Bool :=
  name.startsWith settings.configPrefix || settings.extraDomains.any (·.1 == name)

def Settings.domainFor (settings : Settings) (name : String) : Domain :=
  match settings.extraDomains.find? (·.1 == name) with
  | some (_, domain) => domain
  | none => settings.defaultConfigDomain

def Settings.isTarget (settings : Settings) (name : String) : Bool :=
  settings.targetPrefixes.any fun pfx => name.startsWith pfx

end Skbuild
