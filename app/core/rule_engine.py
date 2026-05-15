import operator


OPS = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}


def get_metric(metrics: dict, name: str):
    return metrics.get(name)


def match_condition(metrics: dict, condition: dict) -> bool:
    metric_name = condition.get("metric")
    op = condition.get("op")
    expected = condition.get("value")

    if not metric_name or not op:
        return False

    actual = get_metric(metrics, metric_name)

    if actual is None:
        return False

    if op not in OPS:
        return False

    try:
        return OPS[op](float(actual), float(expected))
    except Exception:
        return False


def match_all(metrics: dict, conditions: list) -> bool:
    return all(match_condition(metrics, condition) for condition in conditions)


def match_any(metrics: dict, conditions: list) -> bool:
    return any(match_condition(metrics, condition) for condition in conditions)


def rule_matched(metrics: dict, rule: dict) -> bool:
    if "condition" in rule:
        return match_condition(metrics, rule["condition"])

    if "all" in rule:
        return match_all(metrics, rule["all"])

    if "any" in rule:
        return match_any(metrics, rule["any"])

    return False


def evaluate_rules(metrics: dict, rules: list) -> list:
    matched = []

    for rule in rules:
        if rule_matched(metrics, rule):
            matched.append(rule)

    return matched
