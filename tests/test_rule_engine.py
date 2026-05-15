from app.core.rule_engine import evaluate_rules, rule_matched


def test_single_condition_matches():
    rule = {"condition": {"metric": "cpu", "op": ">=", "value": 70}}
    assert rule_matched({"cpu": 80}, rule) is True


def test_single_condition_not_matches():
    rule = {"condition": {"metric": "cpu", "op": ">=", "value": 70}}
    assert rule_matched({"cpu": 20}, rule) is False


def test_all_conditions_match():
    rule = {
        "all": [
            {"metric": "cpu", "op": ">=", "value": 70},
            {"metric": "io", "op": "<", "value": 20},
        ]
    }
    assert rule_matched({"cpu": 80, "io": 5}, rule) is True


def test_any_conditions_match():
    rule = {
        "any": [
            {"metric": "cpu", "op": ">=", "value": 70},
            {"metric": "io", "op": ">=", "value": 30},
        ]
    }
    assert rule_matched({"cpu": 10, "io": 35}, rule) is True


def test_missing_metric_does_not_raise():
    rules = [{"id": "cpu", "condition": {"metric": "cpu", "op": ">=", "value": 70}}]
    assert evaluate_rules({}, rules) == []
