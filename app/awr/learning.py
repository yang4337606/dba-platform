"""Self-learning engine for knowledge rule lifecycle management."""
import json
import re
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LEARNING ENGINE
# ---------------------------------------------------------------------------

class LearningEngine:
    """Self-learning engine for knowledge rule lifecycle management."""

    INITIAL_CONFIDENCE = 0.35
    HIT_BOOST = 0.05
    MISS_DECAY = -0.03
    MISS_STREAK_THRESHOLD = 3
    STALE_DAYS = 90
    STALE_DECAY = -0.10
    ACTIVE_THRESHOLD = 0.65
    REJECT_THRESHOLD = 0.20

    def process_analysis(self, report, problems: list, correlations: list,
                         llm_patterns: list, db_session):
        """Process analysis results: update existing rules, create new candidates."""
        from app.models import KnowledgeRule
        matched_rules, unmatched = self._match_rules(problems, db_session)
        matched_ids = {r.id for r in matched_rules}
        all_non_builtin_rules = db_session.query(KnowledgeRule).filter(
            KnowledgeRule.source != 'builtin').all()
        self._update_hit_rules(matched_rules, report, db_session)
        self._update_miss_rules(all_non_builtin_rules, matched_ids, db_session)
        self._create_candidates(unmatched, llm_patterns or [], db_session)
        db_session.flush()

    def _match_rules(self, problems: list, db_session) -> tuple:
        """Match problems against existing knowledge rules.
        Returns (matched_rules, unmatched_problems)."""
        from app.models import KnowledgeRule
        all_rules = db_session.query(KnowledgeRule).filter(
            KnowledgeRule.status != 'rejected').all()
        # Build metrics context from problems
        metrics_context = {}
        for p in problems:
            metric_name = p.get('metric_name', '')
            metric_value = p.get('metric_value', 0)
            if metric_name:
                metrics_context[metric_name] = metric_value
            event_name = p.get('event_name', '')
            if event_name:
                metrics_context['_event_' + metric_name] = event_name
            # Also store pct_db_time if available
            pct = p.get('pct_db_time', p.get('metric_value', 0))
            if event_name:
                metrics_context['pct_db_time'] = pct
                metrics_context['_current_event'] = event_name
        matched_rules = []
        matched_problem_keys = set()
        for rule in all_rules:
            conds = rule.conditions_json if rule.conditions_json else '[]'
            if self.evaluate_conditions(conds, metrics_context):
                matched_rules.append(rule)
                # Mark related problems as matched
                try:
                    conditions = json.loads(conds) if isinstance(conds, str) else conds
                    for cond in conditions:
                        matched_problem_keys.add(cond.get('metric', ''))
                except Exception:
                    pass
        unmatched = [p for p in problems if p.get('metric_name', '') not in matched_problem_keys]
        return (matched_rules, unmatched)

    def _update_hit_rules(self, matched_rules: list, report, db_session):
        """Boost confidence for matched rules."""
        from app.models import KnowledgeHitLog
        for rule in matched_rules:
            rule.hit_count = (rule.hit_count or 0) + 1
            rule.miss_streak = 0
            rule.confidence = min(1.0, (rule.confidence or 0) + self.HIT_BOOST)
            rule.last_hit_at = datetime.utcnow()
            hit_log = KnowledgeHitLog(rule_id=rule.id, report_id=report.id)
            db_session.add(hit_log)
            self._update_status(rule, db_session)

    def _update_miss_rules(self, all_rules, matched_rule_ids: set, db_session):
        """Increment miss streak for unmatched rules, decay if needed."""
        for rule in all_rules:
            if rule.id in matched_rule_ids:
                continue
            if rule.source == 'builtin':
                continue
            rule.miss_streak = (rule.miss_streak or 0) + 1
            if rule.miss_streak >= self.MISS_STREAK_THRESHOLD:
                rule.confidence = (rule.confidence or 0) + self.MISS_DECAY
            if rule.last_hit_at and (datetime.utcnow() - rule.last_hit_at).days > self.STALE_DAYS:
                rule.confidence = (rule.confidence or 0) + self.STALE_DECAY
            self._update_status(rule, db_session)

    def _create_candidates(self, unmatched_problems: list, llm_patterns: list, db_session):
        """Create new candidate rules from unmatched problems and LLM suggestions."""
        from app.models import KnowledgeRule
        # From unmatched problems
        for problem in unmatched_problems:
            name = problem.get('title', '')
            if not name:
                continue
            existing = db_session.query(KnowledgeRule).filter(
                KnowledgeRule.name == name).first()
            if existing:
                continue
            metric_name = problem.get('metric_name', '')
            threshold = problem.get('threshold_warning', problem.get('metric_value', 0))
            conditions = [{"metric": metric_name, "op": ">", "value": threshold}]
            rule = KnowledgeRule(
                name=name,
                category=problem.get('problem_type', 'unknown'),
                conditions_json=json.dumps(conditions),
                root_cause=problem.get('evidence', ''),
                solution='\u9700\u8981\u8fdb\u4e00\u6b65\u5206\u6790',
                confidence=self.INITIAL_CONFIDENCE,
                status='candidate',
                source='learned',
                is_active=False
            )
            db_session.add(rule)
        # From LLM patterns
        for pattern in llm_patterns:
            name = pattern.get('pattern_name', '')
            if not name:
                continue
            existing = db_session.query(KnowledgeRule).filter(
                KnowledgeRule.name == name).first()
            if existing:
                continue
            conditions = pattern.get('conditions', [])
            rule = KnowledgeRule(
                name=name,
                category='llm_learned',
                conditions_json=json.dumps(conditions),
                root_cause=pattern.get('solution', ''),
                solution=pattern.get('solution', ''),
                confidence=self.INITIAL_CONFIDENCE + 0.05,
                status='candidate',
                source='llm',
                is_active=False
            )
            db_session.add(rule)

    def _update_status(self, rule, db_session):
        """Update rule status based on confidence thresholds."""
        if rule.source == 'builtin':
            rule.status = 'active'
            rule.is_active = True
            return
        confidence = rule.confidence or 0
        if confidence >= self.ACTIVE_THRESHOLD:
            rule.status = 'active'
            rule.is_active = True
        elif confidence >= 0.50:
            rule.status = 'observed'
            rule.is_active = True
        elif confidence < self.REJECT_THRESHOLD:
            rule.status = 'rejected'
            rule.is_active = False
        elif confidence < 0.35:
            rule.status = 'stale'
            rule.is_active = False
        else:
            rule.status = 'candidate'
            rule.is_active = False

    def evaluate_conditions(self, conditions_json: str, metrics_context: dict) -> bool:
        """Evaluate structured conditions against current metrics."""
        try:
            if not conditions_json or not metrics_context:
                return False
            if isinstance(conditions_json, str):
                conditions = json.loads(conditions_json)
            else:
                conditions = conditions_json
            if not conditions:
                return False
            for condition in conditions:
                metric = condition.get('metric', '')
                op = condition.get('op', '>')
                value = condition.get('value', 0)
                event = condition.get('event', '')
                # Check if metric exists in context
                if metric not in metrics_context:
                    return False
                current = metrics_context[metric]
                # If event specified, check event name matches
                if event:
                    ctx_event = metrics_context.get('_event_' + metric, '')
                    current_event = metrics_context.get('_current_event', '')
                    if event.lower() not in ctx_event.lower() and event.lower() not in current_event.lower():
                        return False
                # Apply operator
                try:
                    current = float(current)
                    value = float(value)
                except (ValueError, TypeError):
                    return False
                if op == '>':
                    if not (current > value):
                        return False
                elif op == '<':
                    if not (current < value):
                        return False
                elif op == '>=':
                    if not (current >= value):
                        return False
                elif op == '<=':
                    if not (current <= value):
                        return False
                elif op == '==':
                    if not (current == value):
                        return False
                else:
                    return False
            return True
        except Exception:
            return False

