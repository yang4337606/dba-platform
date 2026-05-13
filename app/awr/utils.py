"""Utility functions for the AWR analysis engine."""
import re

from .constants import (
    PARAMETER_RECOMMENDATIONS,
    VERSION_SPECIFIC_KNOWLEDGE,
    WAIT_EVENT_CLASS,
)


def _safe_float(val, default=0.0):
    """Safely convert a value to float, returning default on failure."""
    if val is None:
        return default
    try:
        if isinstance(val, str):
            val = re.sub(r'[,%\s]', '', val)
        return float(val)
    except (ValueError, TypeError):
        return default


def get_parameter_recommendations(problems: list, parsed_data: dict) -> list:
    """Based on identified problems, return relevant Oracle parameter tuning suggestions."""
    recommendations = []
    problem_keywords = set()
    for p in problems:
        title = (p.get('title', '') + ' ' + p.get('evidence', '')).lower()
        problem_keywords.add(title)
        metric = p.get('metric_name', '')
        if metric:
            problem_keywords.add(metric)

    combined = ' '.join(problem_keywords)
    for param_name, info in PARAMETER_RECOMMENDATIONS.items():
        triggers = info.get('trigger_when', [])
        if not triggers:
            continue
        matched = False
        for trigger in triggers:
            trigger_lower = trigger.lower()
            # Check if any problem matches this trigger
            for kw in problem_keywords:
                if trigger_lower in kw or any(t in kw for t in trigger_lower.split()):
                    matched = True
                    break
            if matched:
                break
        if matched:
            recommendations.append({
                'parameter': param_name,
                'description': info.get('description', ''),
                'recommendation': info.get('recommendation', ''),
                'formula': info.get('formula', ''),
                'notes': info.get('notes', ''),
                'trigger': triggers,
            })

    return recommendations


def get_version_specific_notes(db_version: str) -> list:
    """Return version-specific diagnostic notes for the given Oracle version."""
    if not db_version:
        return []
    notes = []
    for version_prefix, items in VERSION_SPECIFIC_KNOWLEDGE.items():
        if db_version.startswith(version_prefix):
            notes.extend(items)
    return notes


def compute_composite_health_score(problems: list, correlations: list, deviations: list) -> int:
    """Compute a 0-100 composite health score (100 = perfectly healthy).

    Scoring weights:
      - Each problem deducts points based on severity.
      - Correlations (cross-dimension root causes) add extra penalty.
      - Baseline deviations add moderate penalty.
    The score is clamped to [0, 100].
    """
    score = 100.0

    # Severity weights for problems
    severity_penalty = {
        'critical': 12,
        'high': 8,
        'serious': 8,
        'medium': 4,
        'warning': 4,
        'low': 2,
    }

    for p in (problems or []):
        sev = p.get('severity', p.get('health_level', 'medium')).lower()
        score -= severity_penalty.get(sev, 4)

    # Correlation findings indicate deeper systemic issues
    for c in (correlations or []):
        score -= 3

    # Baseline deviations (less severe individually)
    for d in (deviations or []):
        sev = d.get('severity', 'medium').lower()
        score -= severity_penalty.get(sev, 2) * 0.5

    return max(0, min(100, int(round(score))))


def classify_wait_event(event_name: str) -> str:
    """Return Oracle wait class for an event name. Falls back to 'Other'."""
    if not event_name:
        return 'Other'
    lower = event_name.strip().lower()
    # Exact match first
    if lower in WAIT_EVENT_CLASS:
        return WAIT_EVENT_CLASS[lower]
    # Prefix/substring match
    for pattern, cls in WAIT_EVENT_CLASS.items():
        if pattern in lower or lower in pattern:
            return cls
    # Heuristic fallback
    if lower.startswith('enq:'):
        return 'Application'
    if lower.startswith('gc ') or lower.startswith('ges '):
        return 'Cluster'
    if lower.startswith('latch'):
        return 'Concurrency'
    if lower.startswith('cursor:'):
        return 'Concurrency'
    return 'Other'
