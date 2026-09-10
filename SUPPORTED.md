# Supported Kbuild language

This matrix describes the native Lean parser and evaluator. "Parsed" means
syntax is retained but may not affect analysis. "Complete" means the construct
has symbolic semantics and participates in presence conditions. "Partial"
means supported forms are useful but deliberately narrower than GNU Make.

Unsupported constructs that can affect observed Kbuild targets must eventually
produce an incomplete analysis diagnostic. They must never be silently treated
as complete.

## Syntax and directives

| Construct | Parser | Evaluator | Notes |
| --- | --- | --- | --- |
| Blank lines and comments | Complete | N/A | Escaped `\#` retained |
| Backslash continuations | Complete | Complete | Joined before directive parsing |
| `=`, `:=`, `::=`, `+=`, `?=` | Complete | Complete | `+=` respects stored flavor |
| `define` / `endef` | Complete | Complete | Recursive multi-line variable definition |
| Computed variable names | Complete | Complete | Including nested references |
| `ifeq`, `ifneq` parenthesized form | Complete | Complete | Nested expressions supported |
| Quoted `ifeq`/`ifneq` | Complete | Complete | Single- and double-quoted forms |
| `ifdef`, `ifndef` | Complete | Complete | Symbolic values supported |
| `else`, `else if*`, `endif` | Complete | Complete | Arbitrary branch chains |
| Nested conditionals | Complete | Complete | |
| `include`, `-include`, `sinclude` | Complete | Complete | Relative paths and cycles handled |
| Rules | Parsed as opaque | Ignored | Recipes are not executed |
| Recipe lines | Parsed as opaque | Ignored | Recipes are not executed |
| `define`/`endef` | Safely retained as opaque | Unsupported | Body is never mis-executed; emits incomplete diagnostic |
| Assignment `override`, `export`, `private` modifiers | Complete | Complete | Command-line override policy is out of scope |
| Target-specific assignments | Parsed | Unsupported | Emits `SKB1001` |
| Bare `export`, `unexport` | Complete | Ignored safely | Subprocess environment does not affect presence state |
| Bare `vpath` | Parsed with diagnostic | Out of initial scope | |

## Expansions

| Expansion | Parser | Evaluator | Notes |
| --- | --- | --- | --- |
| Literal text | Complete | Complete | Ordered text preserved |
| `$(VAR)`, `${VAR}` | Complete | Complete | Undefined variables expand empty |
| Nested/computed references | Complete | Complete | Recursion cycles are rejected |
| Substitution references | Complete | Complete | Suffix and `%` forms lower to `patsubst` |
| `$$` | Complete | Complete | Produces literal `$` |
| `subst` | Complete | Complete | |
| `addprefix`, `addsuffix` | Complete | Complete | Word-oriented behavior |
| `strip`, `sort` | Complete | Complete | |
| `firstword`, `lastword`, `words` | Complete | Complete | |
| `patsubst` | Complete | Complete | Single-`%` Make patterns |
| `filter`, `filter-out` | Complete | Complete | Single-`%` Make patterns |
| `word`, `wordlist` | Complete | Complete | |
| Filename functions | Complete | Complete | `dir`, `notdir`, `suffix`, `basename` |
| `if`, `or`, `and` | Complete | Complete | Lazy argument selection preserved |
| `foreach` | Complete | Complete | Scoped loop variable and symbolic alternatives |
| `call` | Complete | Complete | User variables with positional arguments |
| `wildcard` | Complete | Partial | Captured filesystem; `*` and `?` patterns |
| `abspath` | Complete | Complete | Lexical normalization against captured source root |
| `realpath` | Complete | Partial | Existing paths from captured filesystem; symlink identity is lexical |
| `origin`, `flavor` | Complete | Complete | Reports analyzer environment state |
| `value` | Complete | Complete | Returns the stored expression without expanding it |
| `warning`, `info` | Complete | Complete | Arguments expand; message side effect is suppressed and value is empty |
| `error` | Complete | Unsupported | Build-stopping side effect emits incomplete `SKB1003` |
| `eval` | Complete | Planned | Only if corpus evidence requires it |
| `shell` | Complete | Disabled | Must never run implicitly |
| Unknown function names | Complete | Unsupported | Emits incomplete `SKB1003` |

## Symbolic analysis

| Capability | Status |
| --- | --- |
| Boolean `CONFIG_*` domains | Complete |
| Tristate `CONFIG_*` domains | Complete through `--tristate` |
| Additional finite domains | Complete through `skbuild.ini` `[COPTIONS]` |
| Standard `BITS` domain | Complete with inferred `32`/`64` values unless the Makefile assigns it; configuration may override |
| Symbolic left- and right-hand sides | Complete |
| Recursive and immediate expansion | Complete for supported expressions |
| Dependency-based statement reduction | Complete, conservative for dynamic names and side effects |
| Feasibility pruning | Complete, finite-domain CNF with native DPLL |
| Equivalent-state path merging | Complete |
| Semantic condition canonicalization | Complete, exhaustive decision-tree implementation |
| `obj-y`, `obj-m`, `lib-y`, `lib-m` extraction | Complete |
| Subdirectory traversal | Complete for `obj-*`/`lib-*` directory values |
| Include evaluation | Complete for supported expansions |
| Versioned result cache | Complete through `--cache=PATH` |
| JSON presence report | Complete, deterministic schema v1 |
| Concrete `.config` filtering | Complete through `--config=PATH` |
| Build-directory comparison | Complete through `--build-dir=PATH` |
| Unaccounted source reporting | Complete through `--src-dir=PATH` |
| Proofs of semantic optimizations | Planned |

The exhaustive solver and canonicalizer favor clarity during migration. They
will be replaced by the verified CNF/SAT pipeline before large-corpus cutover.
