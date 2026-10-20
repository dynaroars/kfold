from z3 import z3util
import z3


def repair(conditions, on, obj):
    '''Find the fewest option changes to a configuration that build one more object.

    Formulates the repair as MaxSAT: the build condition of `obj` must hold, and each
    option it mentions keeps its value in the configuration where it can. Options the
    condition does not mention cannot affect it and keep their values.

    Parameters:
        conditions: {object_path: build_condition}, as analyze returns or load reads
        on:         options set to y in the configuration, as evaluate.read_config returns
        obj:        object path to build, a key of `conditions`

    Returns:
        {option: value} or None:
            the options to change, each with its new value (True for y, False for not
            set), or None when no configuration satisfies the build condition
    '''
    # the evaluated configurations have no modules, so every option is Boolean
    condition = conditions[obj]
    options = z3util.get_vars(condition)
    optimize = z3.Optimize()
    optimize.add(condition)
    for option in options:
        optimize.add_soft(option if str(option) in on else z3.Not(option))
    if optimize.check() != z3.sat:
        return None
    model = optimize.model()
    values = {str(option): z3.is_true(model.eval(option, model_completion=True)) for option in options}
    return {option: value for option, value in values.items() if value != (option in on)}
