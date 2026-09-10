import Skbuild.Diagnostic
import Skbuild.Syntax

namespace Skbuild

def MakeFunction.name : MakeFunction → String
  | .subst => "subst"
  | .patsubst => "patsubst"
  | .strip => "strip"
  | .filter => "filter"
  | .filterOut => "filter-out"
  | .sort => "sort"
  | .word => "word"
  | .wordlist => "wordlist"
  | .words => "words"
  | .firstword => "firstword"
  | .lastword => "lastword"
  | .dir => "dir"
  | .notdir => "notdir"
  | .suffix => "suffix"
  | .basename => "basename"
  | .addsuffix => "addsuffix"
  | .addprefix => "addprefix"
  | .join => "join"
  | .wildcard => "wildcard"
  | .realpath => "realpath"
  | .abspath => "abspath"
  | .ifThenElse => "if"
  | .or => "or"
  | .and => "and"
  | .foreach => "foreach"
  | .call => "call"
  | .value => "value"
  | .eval => "eval"
  | .origin => "origin"
  | .flavor => "flavor"
  | .shell => "shell"
  | .error => "error"
  | .warning => "warning"
  | .info => "info"
  | .unknown name => name

def MakeFunction.isSupported : MakeFunction → Bool
  | .subst | .patsubst | .strip | .filter | .filterOut | .sort
  | .word | .wordlist | .words | .firstword | .lastword
  | .dir | .notdir | .suffix | .basename | .addsuffix | .addprefix | .join
  | .wildcard | .realpath | .abspath
  | .ifThenElse | .or | .and | .foreach | .call | .value | .origin | .flavor
  | .warning | .info => true
  | _ => false

partial def Expr.functions : Expr → List MakeFunction
  | .literal _ => []
  | .variable name => name.functions
  | .function fn args => fn :: args.toList.flatMap Expr.functions
  | .concat parts => parts.toList.flatMap Expr.functions

private def validateExpr (expression : Expr) (span : SourceSpan) : Array Diagnostic :=
  expression.functions.toArray.filterMap fun fn =>
    if fn.isSupported then none
    else some {
      code := "SKB1003"
      severity := .warning
      message := s!"Make function '{fn.name}' is parsed but not symbolically evaluated"
      span
      makesIncomplete := true
    }

private def validateCondition (condition : Condition) (span : SourceSpan) : Array Diagnostic :=
  match condition with
  | .equals left right _ => validateExpr left span ++ validateExpr right span
  | .defined name _ => validateExpr name span
  | .otherwise => #[]

private def Expr.isOutputOnlyMessage : Expr → Bool
  | .function fn _ => fn == .warning || fn == .info
  | _ => false

partial def validateStatements (statements : Array Statement) : Array Diagnostic :=
  statements.flatMap fun statement =>
    match statement with
    | .assignment name _ value target span =>
        validateExpr name span ++ validateExpr value span ++
          (target.map (validateExpr · span)).getD #[]
    | .conditional branches _ => branches.flatMap fun branch =>
        validateCondition branch.condition branch.span ++ validateStatements branch.statements
    | .include paths _ span => validateExpr paths span
    | .expression (.literal value) span =>
        let trimmed := value.trimAscii.toString
        if trimmed.isEmpty || trimmed == "export" || trimmed == "unexport" ||
            trimmed.startsWith "export " || trimmed.startsWith "export\t" ||
            trimmed.startsWith "unexport " || trimmed.startsWith "unexport\t" then #[]
        else #[{
          code := "SKB1004"
          severity := .warning
          message := s!"unhandled top-level directive or expression: {value}"
          span
          makesIncomplete := true
        }]
    | .expression value span =>
        let nested := validateExpr value span
        if value.isOutputOnlyMessage then nested else nested.push {
          code := "SKB1004"
          severity := .warning
          message := "top-level expansion side effects are not evaluated"
          span
          makesIncomplete := true
        }
    | .rule _ _ | .command _ _ => #[]

def validateMakefile (makefile : Makefile) : Array Diagnostic :=
  validateStatements makefile.statements

end Skbuild
