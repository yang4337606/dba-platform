"""Baseline comparison engine."""
from __future__ import annotations

import re
import logging
from typing import Any

from .utils import _safe_float
from .scorer import MetricScorer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BASELINE COMPARER
# ---------------------------------------------------------------------------

class BaselineComparer:
    """Compare current metrics against historical baselines."""

    def compare(self, report: Any, parsed_data: dict[str, Any], db_session: Any) -> list[dict]:
        """Compare current metrics to baseline. Returns list of deviation findings."""
        from app.models import AWRBaseline
        deviations = []
        if not parsed_data or not report:
            return deviations
        metrics = self._extract_key_metrics(parsed_data)
        for metric_name, current_value in metrics.items():
            if current_value is None:
                continue
            baseline = db_session.query(AWRBaseline).filter(
                AWRBaseline.db_name == report.db_name,
                AWRBaseline.instance_name == report.instance_name,
                AWRBaseline.metric_name == metric_name
            ).first()
            if not baseline or baseline.sample_count < 3:
                continue
            dev = self._calculate_deviation(current_value, baseline.avg_value, baseline.max_value)
            if dev['is_anomaly']:
                deviations.append({
                    'metric_name': metric_name,
                    'current_value': current_value,
                    'baseline_avg': baseline.avg_value,
                    'baseline_max': baseline.max_value,
                    'deviation_pct': dev['deviation_pct'],
                    'is_anomaly': dev['is_anomaly'],
                    'evidence': f"{metric_name} \u5f53\u524d {current_value}, \u5386\u53f2\u5e73\u5747 {baseline.avg_value}, \u589e\u957f {dev['deviation_pct']}%"
                })
        return deviations

    def update_baseline(self, report: Any, parsed_data: dict[str, Any], db_session: Any) -> None:
        """Update running baseline statistics after analysis."""
        from app.models import AWRBaseline
        if not parsed_data or not report:
            return
        metrics = self._extract_key_metrics(parsed_data)
        for metric_name, current_value in metrics.items():
            if current_value is None:
                continue
            baseline = db_session.query(AWRBaseline).filter(
                AWRBaseline.db_name == report.db_name,
                AWRBaseline.instance_name == report.instance_name,
                AWRBaseline.metric_name == metric_name,
                AWRBaseline.metric_type == 'auto'
            ).first()
            if baseline:
                old_avg = baseline.avg_value or 0
                old_count = baseline.sample_count or 0
                new_avg = (old_avg * old_count + current_value) / (old_count + 1)
                baseline.avg_value = round(new_avg, 4)
                baseline.min_value = min(baseline.min_value or current_value, current_value)
                baseline.max_value = max(baseline.max_value or current_value, current_value)
                baseline.sample_count = old_count + 1
            else:
                baseline = AWRBaseline(
                    db_name=report.db_name,
                    instance_name=report.instance_name,
                    metric_name=metric_name,
                    metric_type='auto',
                    avg_value=current_value,
                    min_value=current_value,
                    max_value=current_value,
                    sample_count=1
                )
                db_session.add(baseline)
        db_session.flush()

    def _calculate_deviation(self, current: float, avg: float, max_val: float) -> dict[str, Any]:
        """Calculate how much current deviates from baseline."""
        if not avg or avg == 0:
            return {'deviation_pct': 0, 'is_anomaly': False}
        deviation_pct = (current - avg) / avg * 100
        is_anomaly = deviation_pct > 50 or (max_val and current > max_val * 1.2)
        return {'deviation_pct': round(deviation_pct, 1), 'is_anomaly': bool(is_anomaly)}

    def _extract_key_metrics(self, parsed_data: dict[str, Any]) -> dict[str, float]:
        """Extract ALL scoreable metrics from parsed data for baseline comparison.
        Reuses MetricScorer.score_all() extraction logic to stay in sync."""
        metrics = {}
        try:
            # Use MetricScorer to extract all metrics, then harvest the scored_metrics
            scorer = MetricScorer()
            # We need the scored_metrics dict, not the problems list.
            # Replicate the extraction by calling score_all and capturing via a wrapper.
            # Instead, directly compute the same metrics:
            load_profile = parsed_data.get('load_profile', {})
            computed = load_profile.get('computed', {}) if isinstance(load_profile, dict) else {}

            def _sf(v):
                try:
                    return float(v) if v else 0
                except (ValueError, TypeError):
                    return 0

            # Load profile derived
            db_time = _sf(computed.get('db_time'))
            db_cpu = _sf(computed.get('db_cpu'))
            if db_cpu > 0:
                metrics['db_time_ratio'] = round(db_time / db_cpu, 4)
            hard_parses = _sf(computed.get('hard_parses'))
            parses = _sf(computed.get('parses'))
            if parses > 0:
                metrics['hard_parse_pct'] = round(hard_parses / parses * 100, 2)
                metrics['hard_parses_per_sec'] = round(hard_parses, 2)
                metrics['total_parses_per_sec'] = round(parses, 2)
            if computed.get('redo_size'):
                metrics['redo_size_per_sec'] = _sf(computed['redo_size'])
            if computed.get('transactions'):
                metrics['transactions_per_sec'] = _sf(computed['transactions'])
            if computed.get('logical_reads'):
                metrics['logical_reads_per_sec'] = _sf(computed['logical_reads'])
            if computed.get('physical_reads'):
                metrics['physical_reads_per_sec'] = _sf(computed['physical_reads'])
            if computed.get('executes'):
                metrics['sql_executions_per_sec'] = _sf(computed['executes'])

            # Top events (pct + avg_wait)
            top_events = parsed_data.get('top_events', []) or []
            for event in top_events[:10]:
                pct = _sf(event.get('pct_db_time', 0))
                avg_wait = _sf(event.get('avg_wait', 0))
                ename = event.get('event', event.get('name', ''))
                if ename and pct:
                    safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', ename.lower()).strip('_')
                    metrics[f'{safe_name}_pct_db_time'] = pct
                    if avg_wait:
                        metrics[f'{safe_name}_avg_wait'] = avg_wait

            # Instance efficiency
            instance_eff = parsed_data.get('instance_efficiency', {})
            eff_map = {
                'buffer': 'buffer_cache_hit_ratio', 'library': 'library_cache_hit_ratio',
                'soft parse': 'soft_parse_pct', 'execute to parse': 'execute_to_parse_pct',
                'latch hit': 'latch_hit_pct', 'memory sort': 'in_memory_sort_pct',
                'in-memory sort': 'in_memory_sort_pct',
                'parse cpu': 'parse_cpu_to_elapsed_pct',
            }
            if isinstance(instance_eff, dict):
                for name, val in instance_eff.items():
                    fval = _sf(val)
                    if fval > 0:
                        for keyword, metric_key in eff_map.items():
                            if keyword in name.lower():
                                metrics[metric_key] = fval
                                break
            elif isinstance(instance_eff, list):
                for item in instance_eff:
                    name = (item.get('name', item.get('metric', '')) or '').lower()
                    fval = _sf(item.get('value', item.get('pct', 0)))
                    if fval > 0:
                        for keyword, metric_key in eff_map.items():
                            if keyword in name:
                                metrics[metric_key] = fval
                                break

            # Parse stats supplementary
            parse_stats = parsed_data.get('parse_stats', {}) or {}
            if isinstance(parse_stats, dict):
                for key in ('execute_to_parse_pct', 'parse_cpu_to_elapsed_pct'):
                    if parse_stats.get(key) and key not in metrics:
                        metrics[key] = _sf(parse_stats[key])

        except Exception:
            pass
        return metrics


