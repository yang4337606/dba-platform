"""Workload auto-classifier (OLTP / OLAP / MIXED / HTAP)."""
import logging

from .utils import _safe_float

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# WORKLOAD AUTO-CLASSIFIER (OLTP / OLAP / MIXED / HTAP)
# ---------------------------------------------------------------------------

class WorkloadClassifier:
    """Auto-classify database workload as OLTP, OLAP, MIXED, or HTAP based on AWR metrics."""

    def classify(self, parsed_data: dict) -> dict:
        """Classify workload type from parsed AWR data.

        Returns dict with:
          - workload_type: 'OLTP' | 'OLAP' | 'MIXED' | 'HTAP'
          - confidence: float 0-1
          - signals: list of evidence strings
          - oltp_score: float 0-100
          - olap_score: float 0-100
          - threshold_adjustments: dict of metric_key -> (warning, serious) overrides
        """
        signals = []
        oltp_score = 0
        olap_score = 0

        # --- Signal 1: Logical Reads vs Physical Reads ratio ---
        load_profile = parsed_data.get('load_profile', {})
        computed = load_profile.get('computed', {}) if isinstance(load_profile, dict) else {}
        logical_reads = self._sf(computed.get('logical_reads', 0))
        physical_reads = self._sf(computed.get('physical_reads', 0))
        if logical_reads > 0 and physical_reads > 0:
            lr_pr_ratio = logical_reads / physical_reads
            if lr_pr_ratio > 100:
                oltp_score += 20
                signals.append(f'逻辑读/物理读比率={lr_pr_ratio:.0f} (高, OLTP特征)')
            elif lr_pr_ratio < 10:
                olap_score += 20
                signals.append(f'逻辑读/物理读比率={lr_pr_ratio:.0f} (低, OLAP特征: 大量全扫描)')
            else:
                oltp_score += 5
                olap_score += 5
                signals.append(f'逻辑读/物理读比率={lr_pr_ratio:.0f} (中等)')

        # --- Signal 2: Transactions per second ---
        txn_per_sec = self._sf(computed.get('transactions', 0))
        if txn_per_sec > 100:
            oltp_score += 15
            signals.append(f'事务率={txn_per_sec:.1f}/s (高, OLTP特征)')
        elif txn_per_sec < 5:
            olap_score += 15
            signals.append(f'事务率={txn_per_sec:.1f}/s (低, OLAP特征: 少量大事务)')
        else:
            oltp_score += 5
            olap_score += 5

        # --- Signal 3: Redo size per second (high = lots of DML = OLTP) ---
        redo_size = self._sf(computed.get('redo_size', 0))
        if redo_size > 10_000_000:  # >10MB/s
            oltp_score += 10
            signals.append(f'Redo生成={redo_size/1e6:.1f}MB/s (高DML活动)')
        elif redo_size < 500_000:   # <500KB/s
            olap_score += 10
            signals.append(f'Redo生成={redo_size/1e6:.2f}MB/s (低DML, 读密集)')

        # --- Signal 4: Wait event profile ---
        top_events = parsed_data.get('top_events', [])
        seq_read_pct = 0  # db file sequential read = index scan = OLTP
        scat_read_pct = 0  # db file scattered read = full scan = OLAP
        direct_pct = 0     # direct path read = large scan = OLAP
        for evt in top_events:
            ename = (evt.get('event', evt.get('name', '')) or '').lower()
            pct = self._sf(evt.get('pct_db_time', 0))
            if 'db file sequential read' in ename:
                seq_read_pct += pct
            elif 'db file scattered read' in ename:
                scat_read_pct += pct
            elif 'direct path read' in ename and 'temp' not in ename:
                direct_pct += pct

        if seq_read_pct > 20 and scat_read_pct < 5:
            oltp_score += 15
            signals.append(f'单块读={seq_read_pct:.1f}%DBTime, 多块读={scat_read_pct:.1f}% (索引访问主导)')
        elif scat_read_pct > 15 or direct_pct > 15:
            olap_score += 15
            signals.append(f'多块读={scat_read_pct:.1f}%, 直接路径读={direct_pct:.1f}% (全扫描主导)')

        # --- Signal 5: Parse activity (high parse = many distinct SQLs = OLTP) ---
        parses = self._sf(computed.get('parses', 0))
        executes = self._sf(computed.get('executes', 0))
        if executes > 0 and parses > 0:
            exec_to_parse = executes / parses
            if exec_to_parse > 10:
                oltp_score += 10
                signals.append(f'执行/解析比={exec_to_parse:.1f} (高复用, OLTP特征)')
            elif exec_to_parse < 2:
                olap_score += 10
                signals.append(f'执行/解析比={exec_to_parse:.1f} (低复用, OLAP/Ad-hoc特征)')

        # --- Signal 6: Temp/Sort spills (high = large sorts = OLAP) ---
        temp_stats = parsed_data.get('temp_stats', {})
        disk_sort_pct = self._sf(temp_stats.get('disk_sort_pct', 0)) if isinstance(temp_stats, dict) else 0
        if disk_sort_pct > 10:
            olap_score += 10
            signals.append(f'磁盘排序占比={disk_sort_pct:.1f}% (大排序操作)')

        # --- Signal 7: Parallelism (parallel query = OLAP) ---
        # Check wait events for PX-related waits
        px_pct = 0
        for evt in top_events:
            ename = (evt.get('event', evt.get('name', '')) or '').lower()
            if 'px' in ename or 'parallel' in ename:
                px_pct += self._sf(evt.get('pct_db_time', 0))
        if px_pct > 5:
            olap_score += 10
            signals.append(f'并行查询等待={px_pct:.1f}%DBTime (并行负载)')

        # --- Classify ---
        total = oltp_score + olap_score
        if total == 0:
            return {
                'workload_type': 'MIXED',
                'confidence': 0.3,
                'signals': ['数据不足，无法准确分类'],
                'oltp_score': 0, 'olap_score': 0,
                'threshold_adjustments': {},
            }

        oltp_pct = oltp_score / total * 100
        olap_pct = olap_score / total * 100

        if oltp_pct >= 70:
            wtype = 'OLTP'
            confidence = min(0.95, oltp_pct / 100)
        elif olap_pct >= 70:
            wtype = 'OLAP'
            confidence = min(0.95, olap_pct / 100)
        elif oltp_pct >= 40 and olap_pct >= 40:
            wtype = 'HTAP'
            confidence = 0.6
        else:
            wtype = 'MIXED'
            confidence = 0.5

        # --- Generate threshold adjustments ---
        adjustments = self._get_threshold_adjustments(wtype)

        return {
            'workload_type': wtype,
            'confidence': round(confidence, 2),
            'signals': signals,
            'oltp_score': oltp_score,
            'olap_score': olap_score,
            'threshold_adjustments': adjustments,
        }

    def _get_threshold_adjustments(self, workload_type: str) -> dict:
        """Return threshold overrides based on workload type.

        Format: metric_key -> (warning_threshold, serious_threshold, unit, direction)
        These override MetricScorer.DEFAULT_THRESHOLDS for this analysis.
        """
        if workload_type == 'OLAP':
            # OLAP: relax I/O and sort thresholds, tighten parse thresholds
            return {
                'physical_reads_per_sec': (200_000, 500_000, 'reads/s', 'higher_worse'),
                'db_file_scattered_read_avg_wait': (15.0, 30.0, 'ms', 'higher_worse'),
                'temp_space_used_pct': (90.0, 98.0, '%', 'higher_worse'),
                'in_memory_sort_pct': (80.0, 60.0, '%', 'lower_worse'),
                'buffer_gets_per_exec': (100000, 1000000, 'gets', 'higher_worse'),
                'disk_reads_per_exec': (1000, 10000, 'reads', 'higher_worse'),
                'logical_reads_per_sec': (5_000_000, 20_000_000, 'reads/s', 'higher_worse'),
                'top1_sql_pct_db_time': (50.0, 70.0, '%DB Time', 'higher_worse'),
            }
        elif workload_type == 'OLTP':
            # OLTP: tighter on latency, relaxed on throughput ratios
            return {
                'db_file_sequential_read_avg_wait': (8.0, 15.0, 'ms', 'higher_worse'),
                'log_file_sync_avg_wait': (3.0, 10.0, 'ms', 'higher_worse'),
                'hard_parse_pct': (5.0, 15.0, '%', 'higher_worse'),
                'enq_tx_row_lock_avg_wait': (30.0, 100.0, 'ms', 'higher_worse'),
            }
        elif workload_type == 'HTAP':
            return {
                'physical_reads_per_sec': (150_000, 400_000, 'reads/s', 'higher_worse'),
                'buffer_gets_per_exec': (50000, 500000, 'gets', 'higher_worse'),
            }
        return {}

    def _sf(self, val, default=0.0):
        try:
            if val is None:
                return default
            return float(val)
        except (ValueError, TypeError):
            return default


def classify_workload(parsed_data: dict) -> dict:
    """Convenience function to classify workload type."""
    classifier = WorkloadClassifier()
    return classifier.classify(parsed_data)

