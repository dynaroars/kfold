import Skbuild.Source

namespace Skbuild

inductive AssignOp
  | recursive
  | simple
  | simplePosix
  | append
  | conditional
  deriving Repr, BEq, DecidableEq

inductive MakeFunction
  | subst
  | patsubst
  | strip
  | filter
  | filterOut
  | sort
  | word
  | wordlist
  | words
  | firstword
  | lastword
  | dir
  | notdir
  | suffix
  | basename
  | addsuffix
  | addprefix
  | join
  | wildcard
  | realpath
  | abspath
  | ifThenElse
  | or
  | and
  | foreach
  | call
  | value
  | eval
  | origin
  | flavor
  | shell
  | error
  | warning
  | info
  | unknown (name : String)
  deriving Repr, BEq, DecidableEq

inductive Expr where
  | literal (value : String)
  | variable (name : Expr)
  | function (fn : MakeFunction) (args : Array Expr)
  | concat (parts : Array Expr)
  deriving Repr, BEq

inductive Condition where
  | equals (left right : Expr) (expected : Bool)
  | defined (name : Expr) (expected : Bool)
  | otherwise
  deriving Repr, BEq

mutual
  inductive Statement where
    | assignment
        (name : Expr)
        (op : AssignOp)
        (value : Expr)
        (target : Option Expr)
        (span : SourceSpan)
    | conditional (branches : Array Branch) (span : SourceSpan)
    | include (paths : Expr) (required : Bool) (span : SourceSpan)
    | rule (source : String) (span : SourceSpan)
    | command (source : String) (span : SourceSpan)
    | expression (value : Expr) (span : SourceSpan)
    deriving Repr

  structure Branch where
    condition : Condition
    statements : Array Statement
    span : SourceSpan
    deriving Repr
end

structure Makefile where
  schema : Nat
  source : String
  statements : Array Statement
  deriving Repr

end Skbuild
