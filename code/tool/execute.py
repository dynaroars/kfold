import z3

from pymake3 import parserdata, functions, parser, data

TRUE = z3.BoolVal(True)
FALSE = z3.BoolVal(False)

# an expansion is a list of tokens separated by whitespace; a token is a list of
# (string, path condition) alternatives, so `lib-$(CONFIG_TAR)` is one token
# [('lib-y', CONFIG_TAR), ('lib-', Not(CONFIG_TAR))]


def execute(statements):
    '''Return ({variable: {word: path condition}},
               [(target tokens, path condition, recipe lines)]).'''
    executor = Executor()
    executor.run(statements, TRUE)
    return executor.variables, executor.rules


def cross(left, right):
    # glue two tokens: every pair of alternatives that can hold together
    token = []
    for s1, g1 in left:
        for s2, g2 in right:
            path_condition = z3.simplify(z3.And(g1, g2))
            if not z3.is_false(path_condition):
                token.append((s1 + s2, path_condition))
    return token


def alternatives(tokens):
    '''Return [(string, path condition)] for every way the tokens can expand.'''
    result = [('', TRUE)]
    for token in tokens:
        result = [((s1 + ' ' + s2).strip(), path_condition)
                  for s1, g1 in result for s2, g2 in token
                  for path_condition in [z3.simplify(z3.And(g1, g2))]
                  if not z3.is_false(path_condition)]
    return result


def to_words(tokens):
    '''Return {word: path condition} for the words the tokens can contain.'''
    words = {}
    for token in tokens:
        for s, path_condition in token:
            for word in s.split():
                words[word] = z3.simplify(z3.Or(words.get(word, FALSE), path_condition))
    return words


def from_words(words):
    # one token per word; the empty alternative covers the configurations without it
    tokens = []
    for word, path_condition in words.items():
        token = [(word, path_condition)]
        if not z3.is_true(path_condition):
            token.append(('', z3.simplify(z3.Not(path_condition))))
        tokens.append(token)
    return tokens


def is_empty(tokens):
    '''Return the path condition under which the tokens expand to the empty string.'''
    return z3.simplify(z3.And([z3.Or([g for s, g in token if not s.strip()]) for token in tokens]))


def match(pattern, word):
    # Make pattern with at most one %; return the stem, or None when it does not match
    if '%' not in pattern:
        return '' if pattern == word else None
    prefix, suffix = pattern.split('%', 1)
    if len(word) >= len(prefix) + len(suffix) and word.startswith(prefix) and word.endswith(suffix):
        return word[len(prefix):len(word) - len(suffix)]
    return None


def concrete(tokens):
    # the single string a function argument expands to
    strings = alternatives(tokens)
    if len(strings) != 1:
        raise NotImplementedError(f'function argument with several values: {strings}')
    return strings[0][0]


def map_words(tokens, fn):
    # apply fn to every word of every alternative; fn returns the new word, or None to drop it
    return [[(' '.join(w for w in map(fn, s.split()) if w is not None), g) for s, g in token]
            for token in tokens]


class Executor:

    def __init__(self):
        self.variables = {}
        self.rules = []
        self.ignored = set()

    def run(self, statements, path_condition):
        rule = None
        for statement in statements:
            if isinstance(statement, parserdata.Command):
                if rule is not None:
                    rule[2].append(statement.exp.to_source())
                continue
            rule = None
            if isinstance(statement, parserdata.SetVariable):
                self.assign(statement, path_condition)
            elif isinstance(statement, parserdata.ConditionBlock):
                self.branch(statement, path_condition)
            elif isinstance(statement, parserdata.Rule):
                rule = (self.expand(statement.targetexp), path_condition, [])
                self.rules.append(rule)

    def branch(self, block, path_condition):
        # each branch runs under its condition and the negation of the earlier ones
        taken = FALSE
        for condition, statements in block._groups:
            holds = self.condition(condition)
            branch_condition = z3.simplify(z3.And(path_condition, holds, z3.Not(taken)))
            if not z3.is_false(branch_condition):
                self.run(statements, branch_condition)
            taken = z3.simplify(z3.Or(taken, holds))

    def condition(self, condition):
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
        if name in self.variables:
            return from_words(self.variables[name])
        if name.startswith('CONFIG_'):
            option = z3.Bool(name)
            return [[('y', option), ('', z3.Not(option))]]
        return []

    def expand(self, expansion):
        '''Return the tokens of a pymake3 expansion.'''
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
        if isinstance(function, functions.VariableRef):
            tokens = []
            for name, path_condition in alternatives(self.expand(function.vname)):
                tokens.extend([[(s, z3.simplify(z3.And(g, path_condition))) for s, g in token]
                               for token in self.reference(name)])
            return tokens
        args = [self.expand(arg) for arg in function._arguments]
        if isinstance(function, functions.PatSubstFunction):
            pattern, replacement = concrete(args[0]), concrete(args[1])

            def substitute(word):
                stem = match(pattern, word)
                return word if stem is None else replacement.replace('%', stem, 1)
            return map_words(args[2], substitute)
        if isinstance(function, (functions.FilterFunction, functions.FilteroutFunction)):
            patterns = concrete(args[0]).split()
            keep = isinstance(function, functions.FilterFunction)
            return map_words(args[1], lambda word: word if any(
                match(p, word) is not None for p in patterns) == keep else None)
        # other functions expand to nothing for now; their names are recorded
        self.ignored.add(getattr(function, 'name', type(function).__name__))
        return []
