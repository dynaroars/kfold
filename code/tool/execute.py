import os

import z3

from pymake3 import parserdata, functions, parser, data
from tool import parse

TRUE = z3.BoolVal(True)
FALSE = z3.BoolVal(False)

# an expansion is a list of tokens separated by whitespace; a token is a list of
# (string, path condition) alternatives, so `lib-$(CONFIG_TAR)` is one token
# [('lib-y', CONFIG_TAR), ('lib-', Not(CONFIG_TAR))]


def execute(statements, root, variables, command_line=()):
    '''Execute a list of Makefile statements symbolically starting from an initial state.

    Parameters:
        statements: parsed AST statement objects from pymake3
        root:       source tree root path, used to resolve static include directives
        variables:  initial symbolic state, formatted as {variable: {word: path condition}}
        command_line: names of the variables set on Make's command line

    Returns:
        (variables, rules):
            variables: updated symbolic state {variable: {word: path condition}}
            rules:     recorded Make rules [(target tokens, prerequisite tokens, path condition,
                       [(recipe line expansion, path condition)])]
    '''
    executor = Executor(root, variables, command_line)
    executor.run(statements, TRUE)
    return executor.variables, executor.rules


def from_strings(values):
    '''Convert concrete string variables into the symbolic state representation.

    Each space-separated word in `value` is initialized under the constant True condition.
    Used for command-line variables such as ARCH=i386 passed into the build.
    '''
    return {name: {word: TRUE for word in value.split()} for name, value in values.items()}


def cross(left, right):
    '''Compute the lifted cross-product of two adjacent token fragments.

    Concatenates string alternatives from `left` and `right` while conjoining
    their path conditions, keeping only pairs whose combined condition is satisfiable.
    For example, gluing `[('verity', V), ('crypto', Not(V))]` with `[('.o', True)]`
    yields `[('verity.o', V), ('crypto.o', Not(V))]`.
    '''
    token = []
    for s1, g1 in left:
        for s2, g2 in right:
            path_condition = z3.simplify(z3.And(g1, g2))
            if not z3.is_false(path_condition):
                token.append((s1 + s2, path_condition))
    return token


# the number of strings alternatives() builds before giving up: each word that depends
# on options doubles them, so a long option-dependent list would never finish
MAX_ALTERNATIVES = 4096


def alternatives(tokens):
    '''Return [(string, path condition)] for every concrete expansion of `tokens`.

    Computes the Cartesian product across whitespace-separated tokens, conjoining
    path conditions and pruning combinations with unsatisfiable path conditions.
    '''
    result = [('', TRUE)]
    for token in tokens:
        result = [((s1 + ' ' + s2).strip(), path_condition)
                  for s1, g1 in result for s2, g2 in token
                  for path_condition in [z3.simplify(z3.And(g1, g2))]
                  if not z3.is_false(path_condition)]
        if len(result) > MAX_ALTERNATIVES:
            raise NotImplementedError(f'more than {MAX_ALTERNATIVES} alternatives while expanding '
                                      f'{len(tokens)} tokens, first {tokens[0][:3]}')
    return result


def to_words(tokens):
    '''Extract individual whitespace-separated words and their path conditions.

    Returns a mapping {word: path condition} representing a Boolean value summary
    over word membership. If a word appears across multiple alternatives, its
    effective path condition is the disjunction of their individual conditions.
    '''
    words = {}
    for token in tokens:
        for s, path_condition in token:
            for word in s.split():
                words[word] = z3.simplify(z3.Or(words.get(word, FALSE), path_condition))
    return words


# the most words from_words() checks for mutual exclusion, one solver call per pair
MAX_EXCLUSIVE = 16


def exclusive(words):
    '''Check whether the path conditions of all words are pairwise mutually exclusive.

    For example, architecture word size definitions such as `BITS := 32` under
    CONFIG_X86_32 and `64` otherwise have disjoint conditions (satisfying at most
    one word in any configuration).
    '''
    conditions = list(words.values())
    for i, c1 in enumerate(conditions):
        for c2 in conditions[i + 1:]:
            solver = z3.Solver()
            solver.add(c1, c2)
            if solver.check() == z3.sat:
                return False
    return True


def from_words(words):
    '''Convert a word-condition map into token alternatives for variable references.

    If the words are mutually exclusive (e.g., BITS=32 vs 64), they form a single
    token with an empty fallback for configurations where none is selected.
    Otherwise, each word forms an independent token paired with an empty-string
    alternative under its negated condition, so adjacent text binds correctly.
    '''
    if 1 < len(words) <= MAX_EXCLUSIVE and exclusive(words):
        token = list(words.items())
        rest = z3.simplify(z3.Not(z3.Or(list(words.values()))))
        if not z3.is_false(rest):
            token.append(('', rest))
        return [token]
    tokens = []
    for word, path_condition in words.items():
        token = [(word, path_condition)]
        if not z3.is_true(path_condition):
            token.append(('', z3.simplify(z3.Not(path_condition))))
        tokens.append(token)
    return tokens


def implied(condition, by):
    '''Return whether every configuration satisfying `condition` satisfies `by`.'''
    solver = z3.Solver()
    solver.add(condition, z3.Not(by))
    return solver.check() == z3.unsat


def is_empty(tokens):
    '''Return the path condition under which the tokens expand to the empty string.'''
    return z3.simplify(z3.And([z3.Or([g for s, g in token if not s.strip()]) for token in tokens]))


def match(pattern, word):
    '''Match a Make pattern containing at most one '%'.

    Returns the extracted stem if `word` matches `pattern`, or None otherwise.
    '''
    if '%' not in pattern:
        return '' if pattern == word else None
    prefix, suffix = pattern.split('%', 1)
    if len(word) >= len(prefix) + len(suffix) and word.startswith(prefix) and word.endswith(suffix):
        return word[len(prefix):len(word) - len(suffix)]
    return None


def concrete(tokens):
    '''Extract the single constant string for an argument that must be deterministic.

    Raises NotImplementedError if the argument expands to multiple configuration-
    dependent alternatives.
    '''
    strings = alternatives(tokens)
    if len(strings) != 1:
        raise NotImplementedError(f'function argument with several values: {strings}')
    return strings[0][0]


def substitute(pattern, replacement, word):
    '''Apply Make pattern substitution ($(patsubst pattern,replacement,word)) to a word.'''
    stem = match(pattern, word)
    return word if stem is None else replacement.replace('%', stem, 1)


def filter_words(patterns, tokens, keep):
    '''Implement GNU Make's $(filter) and $(filter-out) functions.

    A word is kept if it matches any pattern word (for filter) or none (for filter-out).
    Because pattern words can themselves carry path conditions, a word matches under
    the disjunction of conditions of all matching patterns.
    '''
    pattern_words = [(s.split(), g) for token in patterns for s, g in token]
    result = []
    for token in tokens:
        new = []
        for s, g in token:
            if not s.split():
                new.append((s, g))
                continue
            if len(s.split()) > 1:
                raise NotImplementedError(f'filter on a multi-word alternative: {s!r}')
            matched = z3.Or([c for p, c in pattern_words if any(match(x, s) is not None for x in p)])
            kept = matched if keep else z3.Not(matched)
            for word, condition in ((s, z3.And(g, kept)), ('', z3.And(g, z3.Not(kept)))):
                condition = z3.simplify(condition)
                if not z3.is_false(condition):
                    new.append((word, condition))
        result.append(new)
    return result


def map_words(tokens, fn):
    '''Apply a transformation function `fn` to every word of every token alternative.

    `fn` takes a word string and returns the transformed word, or None to drop it.
    '''
    return [[(' '.join(w for w in map(fn, s.split()) if w is not None), g) for s, g in token]
            for token in tokens]


class Executor:

    def __init__(self, root, variables, command_line=()):
        self.root = root
        self.variables = {name: dict(words) for name, words in variables.items()}
        self.command_line = set(command_line)
        self.rules = []
        # the rule whose recipe the next command lines belong to; a conditional inside
        # a recipe keeps it, so its command lines join the recipe under their condition
        self.rule = None
        self.ignored = set()

    def run(self, statements, path_condition):
        '''Execute AST statements sequentially under the ambient path condition.'''
        for statement in statements:
            if isinstance(statement, parserdata.Command):
                if self.rule is not None:
                    self.rule[3].append((statement.exp, path_condition))
            elif isinstance(statement, parserdata.ConditionBlock):
                self.branch(statement, path_condition)
            elif isinstance(statement, parserdata.Rule):
                self.rule = (self.expand(statement.targetexp), self.expand(statement.depexp),
                             path_condition, [])
                self.rules.append(self.rule)
            elif isinstance(statement, parserdata.StaticPatternRule):
                # `targets: pattern: prerequisites` is a rule for each target, with the
                # stem the pattern matches in place of % in its prerequisites
                pattern = concrete(self.expand(statement.patternexp))
                prerequisites = self.expand(statement.depexp)
                recipe = []
                for target, target_condition in to_words(self.expand(statement.targetexp)).items():
                    stem = match(pattern, target)
                    self.rules.append(([[(target, target_condition)]],
                                       map_words(prerequisites, lambda w: w.replace('%', stem, 1)),
                                       path_condition, recipe))
                self.rule = (None, None, path_condition, recipe)
            else:
                self.rule = None
                if isinstance(statement, parserdata.SetVariable):
                    self.assign(statement, path_condition)
                elif isinstance(statement, parserdata.Include):
                    self.include(statement, path_condition)

    def include(self, statement, path_condition):
        '''Execute an included Makefile under the current path condition.

        Kbuild invokes Make from the source tree root, so include paths are
        relative to `self.root`. Generated build artifacts (e.g., include/config/auto.conf)
        do not exist statically and are skipped.
        '''
        for name, word_condition in to_words(self.expand(statement.exp)).items():
            path = os.path.join(self.root, name)
            if os.path.isfile(path):
                self.run(parse.parse(path), z3.simplify(z3.And(path_condition, word_condition)))

    def branch(self, block, path_condition):
        '''Evaluate a conditional block (ifeq, ifneq, ifdef, ifndef) without path forking.

        Evaluates each branch under the conjunction of the ambient path condition,
        the branch's condition, and the negation of all preceding branch conditions
        in the chain.
        '''
        taken = FALSE
        for condition, statements in block._groups:
            holds = self.condition(condition)
            branch_condition = z3.simplify(z3.And(path_condition, holds, z3.Not(taken)))
            if not z3.is_false(branch_condition):
                self.run(statements, branch_condition)
            taken = z3.simplify(z3.Or(taken, holds))

    def condition(self, condition):
        '''Compute the Boolean path condition under which a Make conditional test holds.'''
        if isinstance(condition, parserdata.ElseCondition):
            return TRUE
        if isinstance(condition, parserdata.EqCondition):
            left, right = self.expand(condition.exp1), self.expand(condition.exp2)
            if not right:
                holds = is_empty(left)
            elif not left:
                holds = is_empty(right)
            else:
                holds = z3.Or([z3.And(g1, g2) for s1, g1 in alternatives(left)
                               for s2, g2 in alternatives(right) if s1 == s2])
        else:
            name = concrete(self.expand(condition.exp))
            holds = z3.Not(is_empty(self.reference(name)))
        return z3.simplify(holds if condition.expected else z3.Not(holds))

    def assign(self, statement, path_condition):
        '''Symbolically execute a variable assignment statement.

        Supports runtime variable name construction by expanding the left-hand side.
        For append assignments (+=), new words are unioned into the variable.
        For overwrite assignments (:= or =), a conditional update narrows pre-existing
        words with the negation of the assignment condition (Not(when)), preserving
        earlier definitions on configurations where the overwrite does not take effect.
        '''
        if statement.targetexp is not None:
            return
        value = parser.parsemakesyntax(parser.Data.fromstring(statement.value, None),
                                       0, (), parser.iterdata)[0]
        words = to_words(self.expand(value))
        for name, name_condition in alternatives(self.expand(statement.vnameexp)):
            when = z3.simplify(z3.And(path_condition, name_condition))
            if z3.is_false(when):
                continue
            if statement.token == '?=' and name in self.variables:
                continue
            # a variable set on the command line keeps its value against the Makefile's
            # = and := assignments, as in Make
            if statement.token != '+=' and name in self.command_line:
                continue
            old = self.variables.get(name, {})
            if statement.token == '+=':
                new = dict(old)
            else:
                # an overwrite removes the old words only where it applies
                new = {w: z3.simplify(z3.And(g, z3.Not(when))) for w, g in old.items()}
            for word, word_condition in words.items():
                new[word] = z3.simplify(z3.Or(new.get(word, FALSE), z3.And(when, word_condition)))
            self.variables[name] = {w: g for w, g in new.items() if not z3.is_false(g)}

    def reference(self, name):
        '''Look up a variable reference $(NAME) in the symbolic state.

        If the variable is undefined in the state and begins with 'CONFIG_', it is
        treated as an unbound symbolic configuration option ranging over Boolean values.
        '''
        if name in self.variables:
            return from_words(self.variables[name])
        if name.startswith('CONFIG_'):
            option = z3.Bool(name)
            return [[('y', option), ('', z3.Not(option))]]
        return []

    def expand(self, expansion):
        '''Expand a pymake3 AST expression into whitespace-separated token alternatives.'''
        if isinstance(expansion, data.StringExpansion):
            return [[(word, TRUE)] for word in expansion.s.split()]
        tokens = []
        open_end = False
        for item, isfunc in expansion:
            if isfunc:
                piece = self.call(item)
                glue_left = glue_right = True
            else:
                piece = [[(word, TRUE)] for word in item.split()]
                glue_left = not item[0].isspace()
                glue_right = not item[-1].isspace()
                if not piece:
                    open_end = False
                    continue
            if not piece:
                continue
            if tokens and open_end and glue_left:
                tokens[-1] = cross(tokens[-1], piece[0])
                tokens.extend(piece[1:])
            else:
                tokens.extend(piece)
            open_end = glue_right
        return tokens

    def call(self, function):
        '''Symbolically evaluate a Make function call or variable reference.'''
        if isinstance(function, functions.VariableRef):
            tokens = []
            for name, path_condition in alternatives(self.expand(function.vname)):
                tokens.extend([[(s, z3.simplify(z3.And(g, path_condition))) for s, g in token]
                               for token in self.reference(name)])
            return tokens
        if isinstance(function, functions.SubstitutionRef):
            # $(VAR:a=b) is $(patsubst %a,%b,$(VAR)) when a has no %
            source, target = concrete(self.expand(function.substfrom)), concrete(self.expand(function.substto))
            if '%' not in source:
                source, target = '%' + source, '%' + target
            tokens = self.call(functions.VariableRef(function.loc, function.vname))
            return map_words(tokens, lambda word: substitute(source, target, word))
        if isinstance(function, functions.ForEachFunction):
            return self.foreach(*function._arguments)
        args = [self.expand(arg) for arg in function._arguments]
        if isinstance(function, functions.PatSubstFunction):
            pattern, replacement = concrete(args[0]), concrete(args[1])
            return map_words(args[2], lambda word: substitute(pattern, replacement, word))
        if isinstance(function, functions.IfFunction):
            # $(if c,then,else): then where c expands to a non-empty string, else elsewhere
            # each token has the empty alternative where its branch does not apply
            empty = is_empty(args[0])
            branches = [(args[1], z3.Not(empty))] + ([(args[2], empty)] if len(args) > 2 else [])
            result = []
            for tokens, when in branches:
                for token in tokens:
                    token = [(s, z3.simplify(z3.And(g, when))) for s, g in token]
                    token.append(('', z3.simplify(z3.Not(when))))
                    token = [(s, g) for s, g in token if not z3.is_false(g)]
                    if any(s for s, g in token):
                        result.append(token)
            return result
        if isinstance(function, functions.AddPrefixFunction):
            prefix = concrete(args[0])
            return map_words(args[1], lambda word: prefix + word)
        if isinstance(function, functions.SortFunction):
            # word order carries no meaning here, so $(sort) only merges duplicates
            return from_words(to_words(args[0]))
        if isinstance(function, (functions.FilterFunction, functions.FilteroutFunction)):
            return filter_words(args[0], args[1], isinstance(function, functions.FilterFunction))
        # other functions expand to nothing for now; their names are recorded
        self.ignored.add(getattr(function, 'name', type(function).__name__))
        return []

    def foreach(self, name, words, body):
        '''Expand $(foreach var,list,text) under the path condition of each word.'''
        # body expands with x bound to each word, under the word's path condition
        name = concrete(self.expand(name))
        saved = self.variables.get(name)
        tokens = []
        for word, condition in to_words(self.expand(words)).items():
            self.variables[name] = {word: TRUE}
            for token in self.expand(body):
                token = [(s, z3.simplify(z3.And(g, condition))) for s, g in token]
                if not z3.is_true(condition):
                    token.append(('', z3.simplify(z3.Not(condition))))
                tokens.append([(s, g) for s, g in token if not z3.is_false(g)])
        if saved is None:
            self.variables.pop(name, None)
        else:
            self.variables[name] = saved
        return tokens
