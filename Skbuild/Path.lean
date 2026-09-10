namespace Skbuild

/--
Normalize a POSIX-style path lexically.  `System.FilePath.normalize` preserves
repeated separators on Unix, while generated Kbuild paths commonly contain
them (for example when an optional prefix expands to the empty string).

This operation is deliberately filesystem-independent: it removes empty and
`.` components and resolves `..` without following symbolic links.
-/
def normalizePathText (value : String) : String :=
  let absolute := value.startsWith "/"
  let components := value.splitOn "/"
  let reversed := components.foldl (init := []) fun stack component =>
    if component.isEmpty || component == "." then stack
    else if component == ".." then
      match stack with
      | head :: tail => if head == ".." then component :: stack else tail
      | [] => if absolute then [] else [component]
    else component :: stack
  let body := String.intercalate "/" reversed.reverse
  if absolute then
    if body.isEmpty then "/" else "/" ++ body
  else if body.isEmpty then "." else body

def normalizeFilePath (path : System.FilePath) : System.FilePath :=
  System.FilePath.mk (normalizePathText path.toString)

def resolveFilePath (base : System.FilePath) (name : String) : System.FilePath :=
  let path := System.FilePath.mk name
  normalizeFilePath <| if path.isAbsolute then path else base / path

end Skbuild
