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
    """Get metric value, supporting dot-notation for nested access."""
    if "." in name:
        parts = name.split(".")
        current = metrics
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current
    return metrics.get(name)


def _resolve_condition(condition: dict, workload_type: str = "") -> dict:
    """Resolve workload-specific thresholds if present."""
    wt = condition.get("workload_thresholds")
    if wt and workload_type:
        # Try exact match, then Mixed as fallback
        threshold = wt.get(workload_type) or wt.get("Mixed")
        if threshold:
            return {
                "metric": condition.get("metric"),
                "op": threshold.get("op", condition.get("op")),
                "value": threshold.get("value", condition.get("value")),
            }
    return condition


def match_condition(metrics: dict, condition: dict, workload_type: str = "") -> bool:
    # Support nested all/any within a condition
    if "all" in condition:
        return match_all(metrics, condition["all"], workload_type)
    if "any" in condition:
        return match_any(metrics, condition["any"], workload_type)

    resolved = _resolve_condition(condition, workload_type)
    metric_name = resolved.get("metric")
    op = resolved.get("op")
    expected = resolved.get("value")

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


def match_all(metrics: dict, conditions: list, workload_type: str = "") -> bool:
    return all(match_condition(metrics, condition, workload_type) for condition in conditions)


def match_any(metrics: dict, conditions: list, workload_type: str = "") -> bool:
    return any(match_condition(metrics, condition, workload_type) for condition in conditions)


def rule_matched(metrics: dict, rule: dict, workload_type: str = "") -> bool:
    if "condition" in rule:
        return match_condition(metrics, rule["condition"], workload_type)

    if "all" in rule:
        return match_all(metrics, rule["all"], workload_type)

    if "any" in rule:
        return match_any(metrics, rule["any"], workload_type)

    return False


SEVERITY_SCORE = {"HIGH": 300, "WARNING": 200, "OBSERVE": 100}


def evaluate_rules(metrics: dict, rules: list, workload_type: str = "") -> list:
    matched = []
    for rule in rules:
        if rule_matched(metrics, rule, workload_type):
            matched.append(rule)
    return matched


def evaluate_rules_grouped(metrics: dict, rules: list, workload_type: str = "") -> dict:
    """Evaluate rules and return grouped results with scoring.

    Returns:
        {
            "matched_rules": [...],          # all matched rules
            "by_group": {"group_name": [...]}, # rules grouped by rule_group
            "by_category": {"CPU": [...]},     # rules grouped by category
            "top_rules": [...],                # top 10 by severity score
        }
    """
    matched = evaluate_rules(metrics, rules, workload_type)

    # Add score to each matched rule
    for rule in matched:
        severity = rule.get("severity", "OBSERVE")
        base_score = SEVERITY_SCORE.get(severity, 100)
        # Compound rules get a bonus score since they represent correlated patterns
        is_compound = "all" in rule.get("condition", {}) or "any" in rule.get("condition", {})
        if is_compound:
            base_score += 50
        rule["_score"] = base_score

    matched.sort(key=lambda r: r.get("_score", 0), reverse=True)

    by_group = {}
    by_category = {}
    for rule in matched:
        group = rule.get("rule_group", rule.get("category", "other"))
        by_group.setdefault(group, []).append(rule)
        cat = rule.get("category", "other")
        by_category.setdefault(cat, []).append(rule)

    return {
        "matched_rules": matched,
        "by_group": by_group,
        "by_category": by_category,
        "top_rules": matched[:10],
    }
