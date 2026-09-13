import Skbuild

open Skbuild
open Skbuild.Logic

private def assertTrue (message : String) (condition : Bool) : IO Unit :=
  unless condition do throw <| IO.userError message

def main : IO UInt32 := do
  assertTrue "path normalization collapses separators and dot components" <|
    normalizePathText "/tree/drivers/gpu//drm/amd/../display/" ==
      "/tree/drivers/gpu/drm/display"
  assertTrue "relative path normalization preserves leading parent components" <|
    normalizePathText "../../drivers//net/./" == "../../drivers/net"
  assertTrue "top must evaluate true" <| Formula.top.eval fun _ => ""
  assertTrue "equality must evaluate" <| (Formula.eq "CONFIG_A" "y").eval fun _ => "y"
  assertTrue "negation must evaluate" <| (Formula.eq "CONFIG_A" "m").neg.eval fun _ => "y"
  assertTrue "top conjunction must simplify" <| Formula.top.conj (.eq "A" "y") == .eq "A" "y"
  assertTrue "complementary disjunction must simplify" <|
    (Formula.eq "A" "y").disj (Formula.eq "A" "y").neg == .top
  assertTrue "contradictory conjunction must simplify" <|
    (Formula.eq "A" "y").conj (Formula.eq "A" "y").neg == .bottom
  let shared := Formula.eq "PARENT" "y"
  let choice := Formula.eq "CHILD" "y"
  assertTrue "complementary guarded paths factor to their shared condition" <|
    (shared.conj choice).disj (shared.conj choice.neg) == shared
  assertTrue "disjunction factors common guards" <|
    (shared.conj (Formula.eq "MODE" "y")).disj (shared.conj (Formula.eq "MODE" "m")) ==
      shared.conj ((Formula.eq "MODE" "y").disj (Formula.eq "MODE" "m"))
  assertTrue "nested conjunction removes repeated literals" <|
    (shared.conj choice).conj shared == shared.conj choice
  assertTrue "nested conjunction detects contradictory literals" <|
    (shared.conj choice).conj shared.neg == .bottom
  assertTrue "satisfiable equality" <|
    (Formula.eq "A" "y").isSatisfiable fun _ => ["", "y"]
  assertTrue "impossible conjunction" <| !(Formula.and (.eq "A" "y") (.eq "A" "")).isSatisfiable
    fun _ => ["", "y"]
  let solverCases := [
    Formula.top,
    Formula.bottom,
    Formula.eq "A" "y",
    Formula.not (.eq "A" "y"),
    Formula.and (.eq "A" "y") (.eq "A" ""),
    Formula.or (.eq "A" "y") (.eq "B" "m"),
    Formula.not <| Formula.and (.eq "A" "y") (.eq "B" "m")
  ]
  let solverDomain := fun symbol => if symbol == "B" then ["", "m", "y"] else ["", "y"]
  let solverModel := fun symbol => if symbol == "B" then "m" else "y"
  for formula in solverCases do
    assertTrue s!"NNF changes semantics for {formula.render}" <|
      (formula.toNNF true).eval solverModel == formula.eval solverModel
    assertTrue s!"CNF solver disagrees with exhaustive semantics for {formula.render}" <|
      formula.isSatisfiable solverDomain == formula.isSatisfiableExhaustive solverDomain
  let redundant := Formula.or
    (Formula.and (.eq "A" "y") (.eq "B" "y"))
    (Formula.and (.eq "A" "y") (.eq "B" ""))
  assertTrue "canonicalization removes irrelevant symbols" <|
    redundant.canonicalize (fun _ => ["y", ""]) == .eq "A" "y"
  let span := SourceSpan.unknown "test"
  let configA : Expr := .variable (.literal "CONFIG_A")
  let statements : Array Statement := #[
    .conditional #[{
      condition := .equals configA (.literal "y") true
      statements := #[.assignment (.literal "BITS") .simple (.literal "32") none span]
      span
    }] span,
    .assignment (.literal "obj-y") .append (.literal "scan.o") none span
  ]
  let result := extractFiles {} <| executeMakefile {} { schema := 1, source := "test", statements }
  assertTrue "a conditional without else preserves the unmatched path" <|
    result.any fun file => file.path == "scan.o" && file.condition == .top
  let parserSample := "obj-$(CONFIG_A) += first.o \\\n+    second.o # trailing comment\nifeq ($(CONFIG_B),y)\nobj-y += yes.o\nelse\nobj-y += no.o\nendif\n"
  let parsed ← match Parser.parse parserSample "parser-test" with
    | .ok value => pure value
    | .error message => throw <| IO.userError message
  let parsedFiles := extractFiles {} <| executeMakefile {} parsed
  assertTrue "native parser handles continuations" <|
    parsedFiles.any fun file => file.path == "second.o" && file.condition == .eq "CONFIG_A" "y"
  assertTrue "native parser handles conditional then branch" <|
    parsedFiles.any fun file => file.path == "yes.o" && file.condition == .eq "CONFIG_B" "y"
  assertTrue "native parser handles conditional else branch" <|
    parsedFiles.any fun file => file.path == "no.o" && file.condition == .eq "CONFIG_B" ""
  let recipeConditionalAst ← match Parser.parse
      "install: artifact\nifeq ($(CONFIG_A),y)\n\tcp artifact output\nelse\n\tcp fallback output\nendif\n"
      "conditional-recipe-test" with
    | .ok value => pure value
    | .error message => throw <| IO.userError message
  assertTrue "conditionals preserve the surrounding recipe context" <|
    !(validateMakefile recipeConditionalAst).any (·.makesIncomplete)
  let functionSample := "sources := src/a.c src/b.c README\nobj-y += $(patsubst src/%.c,%.o,$(filter %.c,$(sources)))\n"
  let functionAst ← match Parser.parse functionSample "functions-test" with
    | .ok value => pure value
    | .error message => throw <| IO.userError message
  let functionFiles := extractFiles {} <| executeMakefile {} functionAst
  assertTrue "native expansion supports filter and patsubst" <|
    functionFiles.any (·.path == "a.o") && functionFiles.any (·.path == "b.o")
  let wildcardAst ← match Parser.parse
      "sources := $(wildcard src/*.c)\nobj-y += $(patsubst src/%.c,%.o,$(sources))\n"
      "wildcard-test" with
    | .ok value => pure value
    | .error message => throw <| IO.userError message
  let wildcardSettings : Settings := { filesystemPaths := ["src/a.c", "src/b.c", "src/readme"] }
  let wildcardFiles := extractFiles (wildcardSettings.forMakefile wildcardAst) <|
    executeMakefile wildcardSettings wildcardAst
  assertTrue "captured wildcard expansion selects matching filesystem paths" <|
    wildcardFiles.any (·.path == "a.o") && wildcardFiles.any (·.path == "b.o") &&
      !wildcardFiles.any (·.path == "readme.o")
  let pathFunctionAst ← match Parser.parse
      "obj-y += $(patsubst %.c,%.o,$(notdir $(realpath src/a.c missing.c)))\nobj-y += $(patsubst %.c,%.o,$(notdir $(abspath generated.c)))\n"
      "path-functions-test" with
    | .ok value => pure value
    | .error message => throw <| IO.userError message
  let pathFunctionSettings : Settings := {
    filesystemPaths := ["/work/src/a.c"]
    workingDirectory := "/work"
  }
  let pathFunctionFiles := extractFiles (pathFunctionSettings.forMakefile pathFunctionAst) <|
    executeMakefile pathFunctionSettings pathFunctionAst
  assertTrue "captured realpath omits missing paths" <|
    pathFunctionFiles.any (·.path == "a.o") && !pathFunctionFiles.any (·.path == "missing.o")
  assertTrue "abspath normalizes relative paths without requiring existence" <|
    pathFunctionFiles.any (·.path == "generated.o")
  let substitutionAst ← match Parser.parse
      "sources := one.c two.c\nobj-y += $(sources:.c=.o)\n" "substitution-test" with
    | .ok value => pure value
    | .error message => throw <| IO.userError message
  let substitutionFiles := extractFiles {} <| executeMakefile {} substitutionAst
  assertTrue "native expansion supports substitution references" <|
    substitutionFiles.any (·.path == "one.o") && substitutionFiles.any (·.path == "two.o")
  let lazyFunctionSample :=
    "REC = recursive\nSIM := simple\nobj-y += $(or ,first.o,ignored.o)\nobj-y += $(and yes,second.o)\nifeq ($(origin MISSING),undefined)\nobj-y += origin.o\nendif\nifeq ($(flavor REC),recursive)\nobj-y += recursive.o\nendif\nifeq ($(flavor SIM),simple)\nobj-y += simple.o\nendif\n"
  let lazyFunctionAst ← match Parser.parse lazyFunctionSample "lazy-functions-test" with
    | .ok value => pure value
    | .error message => throw <| IO.userError message
  let lazyFunctionFiles := extractFiles {} <| executeMakefile {} lazyFunctionAst
  for expected in ["first.o", "second.o", "origin.o", "recursive.o", "simple.o"] do
    assertTrue s!"native expansion supports lazy/status function result {expected}" <|
      lazyFunctionFiles.any (·.path == expected)
  let messageFunctionAst ← match Parser.parse
      "obj-y += before$(warning diagnostic $(CONFIG_A))after.o\nobj-y += $(info note)kept.o\n"
      "message-functions-test" with
    | .ok value => pure value
    | .error message => throw <| IO.userError message
  let messageFunctionResult := executeMakefile {} messageFunctionAst
  let messageFunctionFiles := extractFiles {} messageFunctionResult
  assertTrue "warning and info expand to empty values" <|
    messageFunctionFiles.any (·.path == "beforeafter.o") &&
      messageFunctionFiles.any (·.path == "kept.o")
  assertTrue "warning and info do not make presence analysis incomplete" <|
    !messageFunctionResult.diagnostics.any (·.makesIncomplete)
  let iterationSample :=
    "pair = $(1)-$(2).o\nraw = $(UNEXPANDED)\nobj-y += $(foreach f,one two,$(f).o)\nobj-y += $(call pair,left,right)\nRAW_RESULT := $(value raw)\n"
  let iterationAst ← match Parser.parse iterationSample "iteration-test" with
    | .ok value => pure value
    | .error message => throw <| IO.userError message
  let iterationExecution := executeStatements {} iterationAst.statements #[{}]
  let iterationFiles := extractFiles {} iterationExecution
  for expected in ["one.o", "two.o", "left-right.o"] do
    assertTrue s!"native foreach/call expansion produces {expected}" <|
      iterationFiles.any (·.path == expected)
  assertTrue "value returns an unexpanded variable body" <|
    iterationExecution.paths.any fun path =>
      match path.environment.get? "RAW_RESULT" with
      | some stored => stored.value == .literal "$(UNEXPANDED)"
      | none => false
  let configText := "[COMMON]\nuse_tristate = yes\ntarget_vars = obj- lib- host-\n[COPTIONS]\nBITS = 32 64 None\n"
  let config ← match Settings.parse configText with
    | .ok value => pure value
    | .error message => throw <| IO.userError message
  assertTrue "settings parser supports tristate" <|
    config.defaultConfigDomain == .tristate
  assertTrue "settings parser supports target prefixes" <|
    config.targetPrefixes.contains "host-"
  assertTrue "settings parser supports finite domains" <|
    (config.domainFor "BITS").values == ["32", "64", ""]
  let legacyConfig ← match Settings.parse "[DEFAULT]\ntop_dirs = applets\ntarget_vars = obj- core-\n" with
    | .ok value => pure value
    | .error message => throw <| IO.userError message
  assertTrue "settings parser accepts legacy DEFAULT settings sections" <|
    legacyConfig.topDirectories == ["applets"] && legacyConfig.targetPrefixes.contains "core-"
  let busyboxTargetAst ← match Parser.parse "core-y += applets/\n" "busybox-target-test" with
    | .ok value => pure value
    | .error message => throw <| IO.userError message
  let busyboxSettings : Settings := { targetPrefixes := ["obj-", "lib-", "core-"] }
  let busyboxDirectories := extractDirectories busyboxSettings <|
    executeMakefile busyboxSettings busyboxTargetAst
  assertTrue "custom target prefixes participate in directory traversal" <|
    busyboxDirectories.any (·.path == "applets/")
  let automaticBitsAst ← match Parser.parse "obj-y += unit_$(BITS).o\n" "bits-test" with
    | .ok value => pure value
    | .error message => throw <| IO.userError message
  let automaticBitsFiles := extractFiles (({} : Settings).forMakefile automaticBitsAst) <|
    executeMakefile {} automaticBitsAst
  assertTrue "Kbuild supplies 32/64 BITS when the Makefile does not assign it" <|
    automaticBitsFiles.any (·.path == "unit_32.o") && automaticBitsFiles.any (·.path == "unit_64.o")
  let overwriteAst ← match Parser.parse
      "parts-$(CONFIG_A) := first.o\nparts-$(CONFIG_B) := second.o\nobj-y += $(parts-y)\n"
      "guarded-overwrite-test" with
    | .ok value => pure value
    | .error message => throw <| IO.userError message
  let overwriteSettings := (({} : Settings).forMakefile overwriteAst)
  let overwriteFiles := extractFiles overwriteSettings <| executeMakefile {} overwriteAst
  let firstFile ← match overwriteFiles.find? (·.path == "first.o") with
    | some file => pure file
    | none => throw <| IO.userError "guarded overwrite omitted first.o"
  let secondFile ← match overwriteFiles.find? (·.path == "second.o") with
    | some file => pure file
    | none => throw <| IO.userError "guarded overwrite omitted second.o"
  assertTrue "later guarded writes override earlier helper values" <|
    !firstFile.condition.eval (fun _ => "y") && secondFile.condition.eval (fun _ => "y")
  assertTrue "earlier guarded helper values survive when later writes are inactive" <|
    firstFile.condition.eval (fun symbol => if symbol == "CONFIG_A" then "y" else "")
  let concrete ← match ConcreteConfig.parse
      "CONFIG_A=y\nCONFIG_TEXT=\"hello\"\n# CONFIG_B is not set\n" with
    | .ok value => pure value
    | .error message => throw <| IO.userError message
  assertTrue "Kconfig parser reads enabled values" <| concrete.value "CONFIG_A" == "y"
  assertTrue "Kconfig parser unquotes string values" <| concrete.value "CONFIG_TEXT" == "hello"
  assertTrue "Kconfig parser reads not-set values" <| concrete.value "CONFIG_B" == ""
  let unsupportedAst ← match Parser.parse "obj-y += $(shell echo unsafe).o\n" "unsafe-test" with
    | .ok value => pure value
    | .error message => throw <| IO.userError message
  let unsupportedResult := executeMakefile {} unsupportedAst
  assertTrue "unsupported functions mark analysis incomplete" <|
    unsupportedResult.diagnostics.any (·.makesIncomplete)
  let defineAst ← match Parser.parse
      "SELECTED := selected.o\ndefine generated\n$(SELECTED)\nendef\ndefine unused\nignored.o\nendef\nobj-y += $(call generated)\n"
      "define-test" with
    | .ok value => pure value
    | .error message => throw <| IO.userError message
  let defineExecution := executeMakefile {} defineAst
  let defineFiles := extractFiles {} defineExecution
  assertTrue "define creates a recursive variable usable through call" <|
    defineFiles.any (·.path == "selected.o") && !defineFiles.any (·.path == "ignored.o")
  assertTrue "ordinary define bodies are complete Make variable definitions" <|
    !defineExecution.diagnostics.any (·.makesIncomplete)
  let exportAst ← match Parser.parse
      "export ARCH CROSS_COMPILE\nunexport LEGACY_FLAGS\nobj-y += exported.o\n" "export-test" with
    | .ok value => pure value
    | .error message => throw <| IO.userError message
  assertTrue "bare export declarations do not make presence analysis incomplete" <|
    !(validateMakefile exportAst).any (·.makesIncomplete)
  let reductionAst ← match Parser.parse
      "UNUSED := $(CONFIG_NOISE)\nHELPER := selected.o\nobj-y += $(HELPER)\n" "reduction-test" with
    | .ok value => pure value
    | .error message => throw <| IO.userError message
  let reduced := reduceMakefile {} reductionAst
  assertTrue "dependency reduction drops irrelevant assignments" <|
    reduced.statements.size == 2
  assertTrue "dependency reduction retains transitive target dependencies" <|
    (extractFiles {} <| executeMakefile {} reduced).any (·.path == "selected.o")
  let compositeAst ← match Parser.parse
      "pieces-yy := first.o second.o\nbundle-objs := $(pieces-yy)\nobj-y += bundle.o\n"
      "composite-objs-test" with
    | .ok value => pure value
    | .error message => throw <| IO.userError message
  let compositeReduced := reduceMakefile {} compositeAst
  let compositeFiles := extractFiles {} <| executeMakefile {} compositeReduced
  for expected in ["bundle.o", "first.o", "second.o"] do
    assertTrue s!"composite -objs expansion produces {expected}" <|
      compositeFiles.any (·.path == expected)
  let duplicateTree ← analyzeTree {} (System.FilePath.mk "Tests/Fixtures/tree-duplicate")
  let duplicateFiles ← match duplicateTree with
    | .error message => throw <| IO.userError message
    | .ok tree => pure tree.files
  let sharedFile ← match duplicateFiles.find? (·.path == "child/shared.o") with
    | none => throw <| IO.userError "duplicate directory traversal omitted child/shared.o"
    | some file => pure file
  assertTrue "duplicate directory guards include the first reference" <|
    sharedFile.condition.eval fun symbol => if symbol == "CONFIG_FIRST" then "y" else ""
  assertTrue "duplicate directory guards include the second reference" <|
    sharedFile.condition.eval fun symbol => if symbol == "CONFIG_SECOND" then "y" else ""
  assertTrue "duplicate directory guards exclude the unreachable configuration" <|
    !sharedFile.condition.eval fun _ => ""
  let corpus := [
    "tests/example1/Makefile",
    "tests/linux/linux_orig/Kbuild",
    "tests/paper_example/Makefile",
    "tests/test/kbuild/Kbuild",
    "tests/test/kbuild/Makefile",
    "tests/test1/kbuild/Kbuild",
    "tests/test1/kbuild/Makefile",
    "tests/tmp/1/Makefile",
    "tests/tmp/2/Makefile"
  ]
  for path in corpus do
    match ← Parser.parseFile (System.FilePath.mk path) with
    | .ok _ => pure ()
    | .error message => throw <| IO.userError s!"corpus parse failed for {path}: {message}"
  IO.println "skbuild Lean unit tests passed"
  return 0
