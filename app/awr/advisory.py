"""Advisory, Time Model, and Wait Histogram analyzers."""
import logging

from .utils import _safe_float

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ADVISORY / TIME MODEL / WAIT HISTOGRAM ANALYSIS ENGINES
# ---------------------------------------------------------------------------

class AdvisoryAnalyzer:
    """Analyze Oracle advisory data and produce sizing recommendations.

    Supports Buffer Pool, PGA, Shared Pool, and SGA Target advisories.
    Each advisory type is evaluated independently to find the optimal
    memory configuration that balances cost and benefit.
    """

    def analyze(self, advisories: dict) -> list:
        """Analyze advisory data and return a list of recommendation dicts.

        Args:
            advisories: Dict keyed by advisory type, each value is a list of
                        row dicts as returned by ``_extract_advisories``.

        Returns:
            List of dicts with keys: advisory_type, current_size_mb,
            recommended_size_mb, benefit, detail, severity.
        """
        if not advisories:
            return []

        recommendations = []

        if 'Buffer Pool' in advisories:
            rec = self._analyze_buffer_pool(advisories['Buffer Pool'])
            if rec:
                recommendations.append(rec)

        if 'PGA' in advisories:
            rec = self._analyze_pga(advisories['PGA'])
            if rec:
                recommendations.append(rec)

        if 'Shared Pool' in advisories:
            rec = self._analyze_shared_pool(advisories['Shared Pool'])
            if rec:
                recommendations.append(rec)

        if 'SGA Target' in advisories:
            rec = self._analyze_sga_target(advisories['SGA Target'])
            if rec:
                recommendations.append(rec)

        return recommendations

    # -- Buffer Pool Advisory ------------------------------------------------

    def _analyze_buffer_pool(self, rows: list) -> dict | None:
        """Find optimal buffer pool size based on physical read factor."""
        if not rows:
            return None

        current_row = None
        for row in rows:
            try:
                if float(row.get('Size Factor', 0)) == 1.0:
                    current_row = row
                    break
            except (ValueError, TypeError):
                continue

        if current_row is None:
            return None

        current_size = float(current_row.get('Size (M)', 0))
        current_reads = float(current_row.get('Estimated Physical Reads', 1))
        if current_size <= 0 or current_reads <= 0:
            return None

        best_row = None
        best_score = None  # lower is better: read_factor / size_factor

        for row in rows:
            try:
                size_factor = float(row.get('Size Factor', 0))
                read_factor = float(row.get('Physical Read Factor', 0))
                size_mb = float(row.get('Size (M)', 0))
            except (ValueError, TypeError):
                continue

            # Only consider sizes larger than current up to 2x
            if size_factor <= 1.0 or size_factor > 2.0:
                continue

            score = read_factor / size_factor if size_factor > 0 else None
            if score is not None and (best_score is None or score < best_score):
                best_score = score
                best_row = row

        if best_row is None:
            return None

        rec_size = float(best_row.get('Size (M)', 0))
        rec_reads = float(best_row.get('Estimated Physical Reads', 1))
        reduction_pct = (1 - rec_reads / current_reads) * 100 if current_reads > 0 else 0

        if reduction_pct <= 20:
            return None

        severity = 'high' if reduction_pct > 40 else 'medium'

        return {
            'advisory_type': 'Buffer Pool',
            'current_size_mb': current_size,
            'recommended_size_mb': rec_size,
            'benefit': f'预计减少物理读 {reduction_pct:.1f}%',
            'detail': (
                f'当前缓冲池 {current_size:.0f}MB, 物理读 {current_reads:.0f}; '
                f'建议扩展到 {rec_size:.0f}MB, 预计物理读降至 {rec_reads:.0f}'
            ),
            'severity': severity,
        }

    # -- PGA Advisory --------------------------------------------------------

    def _analyze_pga(self, rows: list) -> dict | None:
        """Find optimal PGA target that eliminates over-allocation."""
        if not rows:
            return None

        # Sort by PGA target size ascending
        parsed = []
        for row in rows:
            try:
                target = float(row.get('PGA Target Est (MB)', 0))
                overalloc = int(row.get('Estd PGA Overalloc Count', 0))
                extra_bytes = float(row.get('Estd Extra Bytes Read/Written to Disk', 0))
                parsed.append({
                    'target_mb': target,
                    'overalloc': overalloc,
                    'extra_bytes': extra_bytes,
                    'raw': row,
                })
            except (ValueError, TypeError):
                continue

        if not parsed:
            return None

        parsed.sort(key=lambda r: r['target_mb'])

        # Identify current (smallest target with overalloc = 0, or just the first)
        current = parsed[0]
        for p in parsed:
            if p['overalloc'] > 0:
                current = p
                break

        # If current already has zero over-allocation, no recommendation needed
        if current['overalloc'] == 0:
            return None

        # Find smallest target with zero over-allocation and minimal extra bytes
        optimal = None
        for p in parsed:
            if p['overalloc'] == 0:
                if optimal is None or p['extra_bytes'] < optimal['extra_bytes']:
                    optimal = p

        if optimal is None or optimal['target_mb'] <= current['target_mb']:
            return None

        severity = 'high' if current['overalloc'] > 10 else 'medium'

        return {
            'advisory_type': 'PGA',
            'current_size_mb': current['target_mb'],
            'recommended_size_mb': optimal['target_mb'],
            'benefit': f'消除PGA过度分配 (当前过度分配次数: {current["overalloc"]})',
            'detail': (
                f'当前PGA目标 {current["target_mb"]:.0f}MB 存在 '
                f'{current["overalloc"]} 次过度分配; '
                f'建议调整到 {optimal["target_mb"]:.0f}MB'
            ),
            'severity': severity,
        }

    # -- Shared Pool Advisory ------------------------------------------------

    def _analyze_shared_pool(self, rows: list) -> dict | None:
        """Find optimal shared pool size maximizing LC Time Saved."""
        if not rows:
            return None

        parsed = []
        for row in rows:
            try:
                size = float(row.get('Shared Pool Size(M)', 0))
                lc_time = float(row.get('Estd LC Time Saved (s)', 0))
                lc_hits = float(row.get('Estd LC Memory Object Hits', 0))
                size_factor = float(row.get('Size Factor', row.get('Shared Pool Size Factor', 0)))
                parsed.append({
                    'size_mb': size,
                    'lc_time_saved': lc_time,
                    'lc_hits': lc_hits,
                    'size_factor': size_factor,
                    'raw': row,
                })
            except (ValueError, TypeError):
                continue

        if not parsed:
            return None

        parsed.sort(key=lambda r: r['size_mb'])

        # Find current configuration (Size Factor = 1.0), fallback to first entry
        current = parsed[0]
        for p in parsed:
            if abs(p.get('size_factor', 0) - 1.0) < 0.01:
                current = p
                break

        # Find optimal: maximize LC Time Saved with good LC Hits
        best = max(parsed, key=lambda r: r['lc_time_saved'])

        if best['size_mb'] <= current['size_mb']:
            return None

        improvement = (
            (best['lc_time_saved'] - current['lc_time_saved'])
            / current['lc_time_saved'] * 100
            if current['lc_time_saved'] > 0 else 0
        )

        if improvement <= 5:
            return None

        severity = 'high' if improvement > 30 else ('medium' if improvement > 10 else 'low')

        return {
            'advisory_type': 'Shared Pool',
            'current_size_mb': current['size_mb'],
            'recommended_size_mb': best['size_mb'],
            'benefit': f'预计库缓存时间节省提升 {improvement:.1f}%',
            'detail': (
                f'当前共享池 {current["size_mb"]:.0f}MB, LC Time Saved '
                f'{current["lc_time_saved"]:.0f}s; '
                f'建议扩展到 {best["size_mb"]:.0f}MB, '
                f'LC Time Saved {best["lc_time_saved"]:.0f}s'
            ),
            'severity': severity,
        }

    # -- SGA Target Advisory -------------------------------------------------

    def _analyze_sga_target(self, rows: list) -> dict | None:
        """Find the SGA target size that minimizes estimated DB Time."""
        if not rows:
            return None

        parsed = []
        for row in rows:
            try:
                size = float(row.get('SGA Target Size (M)', 0))
                db_time = float(row.get('Estd DB Time (s)', 0))
                size_factor = float(row.get('SGA Size Factor', row.get('Size Factor', 0)))
                parsed.append({'size_mb': size, 'db_time': db_time, 'size_factor': size_factor, 'raw': row})
            except (ValueError, TypeError):
                continue

        if not parsed:
            return None

        parsed.sort(key=lambda r: r['size_mb'])

        # Find current configuration (Size Factor = 1.0), fallback to first entry
        current = parsed[0]
        for p in parsed:
            if abs(p.get('size_factor', 0) - 1.0) < 0.01:
                current = p
                break
        best = min(parsed, key=lambda r: r['db_time'])

        if best['size_mb'] <= current['size_mb']:
            return None

        reduction_pct = (
            (current['db_time'] - best['db_time']) / current['db_time'] * 100
            if current['db_time'] > 0 else 0
        )

        if reduction_pct <= 5:
            return None

        severity = 'high' if reduction_pct > 20 else ('medium' if reduction_pct > 10 else 'low')

        return {
            'advisory_type': 'SGA Target',
            'current_size_mb': current['size_mb'],
            'recommended_size_mb': best['size_mb'],
            'benefit': f'预计DB Time减少 {reduction_pct:.1f}%',
            'detail': (
                f'当前SGA目标 {current["size_mb"]:.0f}MB, DB Time '
                f'{current["db_time"]:.0f}s; '
                f'建议调整到 {best["size_mb"]:.0f}MB, '
                f'DB Time {best["db_time"]:.0f}s'
            ),
            'severity': severity,
        }


class TimeModelAnalyzer:
    """Analyze Oracle Time Model statistics to surface abnormal time distribution.

    Compares each component's percentage of DB Time against known thresholds
    and produces findings with severity ratings and actionable suggestions.
    """

    # Threshold definitions: (key, threshold_pct, severity, finding, suggestion)
    _RULES = [
        (
            'pl_sql_execution_elapsed_time', 30, 'warning',
            'PL/SQL执行占比过高',
            '检查PL/SQL代码效率，考虑将逻辑移至SQL或减少上下文切换',
        ),
        (
            'parse_time_elapsed', 15, 'warning',
            '解析时间占比过高',
            '检查是否缺少绑定变量，或cursor_sharing参数设置',
        ),
        (
            'hard_parse_elapsed_time', 10, 'high',
            '硬解析占DB Time过高',
            '使用绑定变量减少硬解析，检查shared_pool大小，考虑cursor_sharing=FORCE',
        ),
        (
            'sequence_load_elapsed_time', 5, 'warning',
            '序列加载时间异常',
            '增大序列缓存 (CACHE) 值，减少序列相关的等待',
        ),
        (
            'connection_management_call_elapsed_time', 10, 'warning',
            '连接管理耗时过多，可能存在频繁连接/断开',
            '使用连接池，减少频繁创建/销毁数据库连接',
        ),
    ]

    def analyze(self, time_model: dict, db_time_seconds: float = 0) -> list:
        """Analyze time model data and return findings.

        Args:
            time_model: Dict keyed by metric key (e.g. ``'db_cpu'``), each
                        value has ``name``, ``time_seconds``, ``pct_db_time``.
            db_time_seconds: Total DB Time in seconds.  If 0, it will be
                             derived from ``sql_execute_elapsed_time``.

        Returns:
            List of dicts with keys: component, pct_db_time, threshold,
            finding, severity, suggestion.
        """
        if not time_model:
            return []

        findings = []

        # Derive DB Time if not provided
        if db_time_seconds <= 0:
            sql_exec = time_model.get('sql_execute_elapsed_time', {})
            db_time_seconds = float(sql_exec.get('time_seconds', 0))
        if db_time_seconds <= 0:
            return []

        # Check each threshold rule
        for key, threshold, severity, finding_text, suggestion in self._RULES:
            entry = time_model.get(key)
            if entry is None:
                continue
            pct = float(entry.get('pct_db_time', 0))
            if pct > threshold:
                findings.append({
                    'component': entry.get('name', key),
                    'pct_db_time': round(pct, 2),
                    'threshold': threshold,
                    'finding': finding_text,
                    'severity': severity,
                    'suggestion': suggestion,
                })

        # DB CPU ratio check
        db_cpu_entry = time_model.get('db_cpu')
        if db_cpu_entry:
            cpu_pct = float(db_cpu_entry.get('pct_db_time', 0))
            if cpu_pct < 30:
                findings.append({
                    'component': db_cpu_entry.get('name', 'DB CPU'),
                    'pct_db_time': round(cpu_pct, 2),
                    'threshold': 30,
                    'finding': 'DB CPU占比低，大量时间消耗在等待上',
                    'severity': 'warning',
                    'suggestion': '分析Top等待事件，优化I/O或锁等待',
                })

        # SQL execute wait ratio check
        sql_exec = time_model.get('sql_execute_elapsed_time')
        if sql_exec and db_cpu_entry:
            sql_time = float(sql_exec.get('time_seconds', 0))
            cpu_time = float(db_cpu_entry.get('time_seconds', 0))
            if sql_time > 0:
                wait_ratio = (sql_time - cpu_time) / sql_time * 100
                if wait_ratio > 60:
                    findings.append({
                        'component': sql_exec.get('name', 'sql execute elapsed time'),
                        'pct_db_time': round(wait_ratio, 2),
                        'threshold': 60,
                        'finding': 'SQL执行中等待占比过高',
                        'severity': 'warning',
                        'suggestion': (
                            'SQL执行中大部分时间在等待而非CPU运算，'
                            '需分析具体等待事件 (I/O、锁、网络等)'
                        ),
                    })

        return findings


class WaitHistogramAnalyzer:
    """Analyze Oracle wait event histogram data for latency distribution patterns.

    Examines bucket distributions to estimate P95/P99 latencies and detect
    anomalous patterns such as long tails, bimodal distributions, and
    high-latency spikes.
    """

    # Ordered bucket labels and their upper-bound latency in ms
    _BUCKETS = [
        ('< 1ms', 1),
        ('< 2ms', 2),
        ('< 4ms', 4),
        ('< 8ms', 8),
        ('< 16ms', 16),
        ('< 32ms', 32),
        ('>= 32ms', 64),  # use 64ms as approximate representative
    ]

    def analyze(self, wait_histogram: list) -> list:
        """Analyze wait histogram rows and return latency findings.

        Args:
            wait_histogram: List of row dicts as returned by
                            ``_extract_wait_histogram``.

        Returns:
            List of dicts with keys: event, total_waits, p95_bucket,
            p99_bucket, pattern, finding, severity.
        """
        if not wait_histogram:
            return []

        findings = []

        for row in wait_histogram:
            event = row.get('Event', 'unknown')

            # Parse bucket counts
            counts = []
            for label, _ in self._BUCKETS:
                try:
                    counts.append(int(row.get(label, 0)))
                except (ValueError, TypeError):
                    counts.append(0)

            total = sum(counts)
            if total == 0:
                continue

            # Calculate percentages per bucket
            pcts = [c / total * 100 for c in counts]

            # Estimate P95 and P99 buckets
            p95_bucket = self._percentile_bucket(counts, total, 95)
            p99_bucket = self._percentile_bucket(counts, total, 99)

            # Detect patterns
            pattern, finding_text, severity = self._detect_pattern(
                event, pcts, p99_bucket,
            )

            findings.append({
                'event': event,
                'total_waits': total,
                'p95_bucket': self._BUCKETS[p95_bucket][0],
                'p99_bucket': self._BUCKETS[p99_bucket][0],
                'pattern': pattern,
                'finding': finding_text,
                'severity': severity,
            })

        return findings

    def _percentile_bucket(self, counts: list, total: int, pct: float) -> int:
        """Return the bucket index where the cumulative count reaches *pct*%."""
        target = total * pct / 100.0
        cumulative = 0
        for i, c in enumerate(counts):
            cumulative += c
            if cumulative >= target:
                return i
        return len(counts) - 1

    def _detect_pattern(
        self, event: str, pcts: list, p99_idx: int,
    ) -> tuple:
        """Detect distribution pattern and return (pattern, finding, severity).

        Returns:
            Tuple of (pattern_name, finding_text, severity).
        """
        # Index constants
        IDX_LT1 = 0
        IDX_GE32 = 6
        IDX_GE16 = 5  # '< 32ms' bucket index; >= 16ms starts at index 5

        # Long tail detection: >= 32ms bucket > 5%
        if pcts[IDX_GE32] > 5:
            return (
                'long_tail',
                f'长尾延迟: {event} P99 > 32ms, >= 32ms等待占比 {pcts[IDX_GE32]:.1f}%',
                'high',
            )

        # Bimodal detection: < 1ms > 20% AND >= 16ms buckets collectively > 20%
        high_bucket_pct = pcts[IDX_GE16] + pcts[IDX_GE32]  # >= 16ms region
        if pcts[IDX_LT1] > 20 and high_bucket_pct > 20:
            return (
                'bimodal',
                f'双峰分布: {event} 存在两种不同延迟模式 '
                f'(< 1ms: {pcts[IDX_LT1]:.1f}%, >= 16ms: {high_bucket_pct:.1f}%)',
                'warning',
            )

        # Spike detection: any single bucket > 80%
        max_pct = max(pcts)
        max_idx = pcts.index(max_pct)
        if max_pct > 80:
            if max_idx >= 4:  # >= 16ms bucket region
                return (
                    'high_spike',
                    f'延迟集中在高等待区间: {event} '
                    f'{self._BUCKETS[max_idx][0]} 占比 {max_pct:.1f}%',
                    'high',
                )
            return (
                'uniform_low',
                f'均匀延迟模式: {event} 延迟集中在 {self._BUCKETS[max_idx][0]}',
                'low',
            )

        # Default: normal distribution
        return (
            'normal',
            f'{event} 延迟分布正常, P99 在 {self._BUCKETS[p99_idx][0]} 范围内',
            'low',
        )


# -- Convenience functions ---------------------------------------------------

def get_advisory_recommendations(advisories: dict) -> list:
    """Convenience function to get advisory recommendations.

    Args:
        advisories: Dict of advisory data as returned by
                    ``_extract_advisories``.

    Returns:
        List of recommendation dicts.
    """
    analyzer = AdvisoryAnalyzer()
    return analyzer.analyze(advisories)


def get_time_model_findings(time_model: dict, db_time_seconds: float = 0) -> list:
    """Convenience function to get time model analysis findings.

    Args:
        time_model: Dict of time model data as returned by
                    ``_extract_time_model``.
        db_time_seconds: Optional total DB Time in seconds.

    Returns:
        List of finding dicts.
    """
    analyzer = TimeModelAnalyzer()
    return analyzer.analyze(time_model, db_time_seconds)


def get_wait_histogram_findings(wait_histogram: list) -> list:
    """Convenience function to get wait histogram analysis findings.

    Args:
        wait_histogram: List of histogram row dicts as returned by
                        ``_extract_wait_histogram``.

    Returns:
        List of finding dicts.
    """
    analyzer = WaitHistogramAnalyzer()
    return analyzer.analyze(wait_histogram)

