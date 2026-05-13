"""AWR metric scoring engine."""
from __future__ import annotations

import re
import logging
from typing import Any

from .utils import _safe_float

logger = logging.getLogger(__name__)


class MetricScorer:
    """Score AWR metrics against configurable thresholds."""

    # Default thresholds: {metric_key: (warning_threshold, serious_threshold, unit, direction)}
    # direction: 'higher_worse' means higher value = worse, 'lower_worse' means lower = worse
    DEFAULT_THRESHOLDS = {
        # --- Load / Capacity ---
        'aas_per_cpu': (0.7, 1.0, 'ratio', 'higher_worse'),
        'db_time_ratio': (1.0, 3.0, 'ratio', 'higher_worse'),
        'transactions_per_sec': (500.0, 2000.0, 'txn/s', 'higher_worse'),
        'logical_reads_per_sec': (2_000_000, 5_000_000, 'reads/s', 'higher_worse'),
        'physical_reads_per_sec': (50_000, 150_000, 'reads/s', 'higher_worse'),
        # --- Wait Events ---
        'top_event_pct_db_time': (15.0, 30.0, '%DB Time', 'higher_worse'),
        'db_file_sequential_read_avg_wait': (10.0, 20.0, 'ms', 'higher_worse'),
        'db_file_scattered_read_avg_wait': (10.0, 20.0, 'ms', 'higher_worse'),
        'log_file_sync_avg_wait': (5.0, 15.0, 'ms', 'higher_worse'),
        'log_file_parallel_write_avg_wait': (5.0, 15.0, 'ms', 'higher_worse'),
        'buffer_busy_waits_avg_wait': (5.0, 20.0, 'ms', 'higher_worse'),
        'read_by_other_session_avg_wait': (10.0, 30.0, 'ms', 'higher_worse'),
        'enq_tx_row_lock_avg_wait': (50.0, 200.0, 'ms', 'higher_worse'),
        # --- Parse ---
        'hard_parse_pct': (10.0, 30.0, '%', 'higher_worse'),
        'hard_parses_per_sec': (100.0, 500.0, 'parses/s', 'higher_worse'),
        'total_parses_per_sec': (1000.0, 5000.0, 'parses/s', 'higher_worse'),
        'execute_to_parse_pct': (50.0, 30.0, '%', 'lower_worse'),
        'soft_parse_pct': (90.0, 70.0, '%', 'lower_worse'),
        'parse_cpu_to_elapsed_pct': (50.0, 20.0, '%', 'lower_worse'),
        # --- SQL Efficiency ---
        'buffer_gets_per_exec': (10000, 100000, 'gets', 'higher_worse'),
        'disk_reads_per_exec': (100, 1000, 'reads', 'higher_worse'),
        'sql_executions_per_sec': (10000, 50000, 'exec/s', 'higher_worse'),
        'top1_sql_pct_db_time': (30.0, 50.0, '%DB Time', 'higher_worse'),
        # --- Memory / Cache ---
        'buffer_cache_hit_ratio': (95.0, 90.0, '%', 'lower_worse'),
        'library_cache_hit_ratio': (99.0, 95.0, '%', 'lower_worse'),
        'shared_pool_free_pct': (10.0, 5.0, '%', 'lower_worse'),
        'in_memory_sort_pct': (95.0, 85.0, '%', 'lower_worse'),
        'latch_hit_pct': (99.0, 98.0, '%', 'lower_worse'),
        'pga_over_allocation_count': (0, 100, 'count', 'higher_worse'),
        # --- I/O ---
        'avg_read_time': (10.0, 20.0, 'ms', 'higher_worse'),
        'avg_write_time': (5.0, 15.0, 'ms', 'higher_worse'),
        'tablespace_io_pct': (60.0, 80.0, '%', 'higher_worse'),
        # --- Redo ---
        'redo_size_per_sec': (50_000_000, 200_000_000, 'bytes/s', 'higher_worse'),
        'log_switches_per_hour': (6, 20, 'switches/hr', 'higher_worse'),
        # --- RAC ---
        'gc_cr_block_receive_time': (1.0, 3.0, 'ms', 'higher_worse'),
        'gc_current_block_receive_time': (1.0, 3.0, 'ms', 'higher_worse'),
        # --- Undo / Temp ---
        'undo_space_used_pct': (85.0, 95.0, '%', 'higher_worse'),
        'temp_space_used_pct': (80.0, 95.0, '%', 'higher_worse'),
        # --- OS ---
        'os_cpu_used_pct': (85.0, 95.0, '%', 'higher_worse'),
        'os_swap_used_pct': (10.0, 30.0, '%', 'higher_worse'),
        'os_load_avg': (2.0, 4.0, 'per CPU', 'higher_worse'),
    }

    def __init__(self, custom_thresholds: dict[str, tuple] | None = None) -> None:
        self.thresholds = dict(self.DEFAULT_THRESHOLDS)
        if custom_thresholds:
            self.thresholds.update(custom_thresholds)

    def score_metric(self, metric_key: str, value: float) -> dict[str, Any]:
        """Score a single metric. Returns dict with level, evidence, thresholds."""
        if metric_key not in self.thresholds:
            return {'level': 'healthy', 'evidence': '', 'warning_threshold': None, 'serious_threshold': None}

        warning_threshold, serious_threshold, unit, direction = self.thresholds[metric_key]

        level = 'healthy'
        if direction == 'higher_worse':
            if value >= serious_threshold:
                level = 'serious'
            elif value >= warning_threshold:
                level = 'warning'
        elif direction == 'lower_worse':
            if value <= serious_threshold:
                level = 'serious'
            elif value <= warning_threshold:
                level = 'warning'

        evidence = ''
        if level != 'healthy':
            metric_display = metric_key.replace('_', ' ')
            if level == 'serious':
                evidence = f"{metric_display} 当前值 {value}{unit}, 超过严重阈值 {serious_threshold}{unit}"
            else:
                evidence = f"{metric_display} 当前值 {value}{unit}, 超过警告阈值 {warning_threshold}{unit}"

        return {
            'level': level,
            'evidence': evidence,
            'warning_threshold': warning_threshold,
            'serious_threshold': serious_threshold,
        }

    def _safe_float(self, val: Any, default: float = 0.0) -> float:
        return _safe_float(val, default)

    def _get_problem_type(self, metric_key: str) -> str:
        """Map metric key to problem type category."""
        IO_KEYS = ('db_file_sequential_read_avg_wait', 'db_file_scattered_read_avg_wait',
                    'avg_read_time', 'avg_write_time', 'tablespace_io_pct', 'physical_reads_per_sec')
        WAIT_KEYS = ('log_file_sync_avg_wait', 'log_file_parallel_write_avg_wait',
                     'top_event_pct_db_time', 'buffer_busy_waits_avg_wait',
                     'read_by_other_session_avg_wait', 'enq_tx_row_lock_avg_wait')
        SQL_KEYS = ('buffer_gets_per_exec', 'disk_reads_per_exec', 'sql_executions_per_sec',
                    'top1_sql_pct_db_time')
        MEMORY_KEYS = ('buffer_cache_hit_ratio', 'library_cache_hit_ratio', 'shared_pool_free_pct',
                       'in_memory_sort_pct', 'latch_hit_pct', 'pga_over_allocation_count')
        PARSE_KEYS = ('hard_parse_pct', 'hard_parses_per_sec', 'total_parses_per_sec',
                      'execute_to_parse_pct', 'soft_parse_pct', 'parse_cpu_to_elapsed_pct')
        REDO_KEYS = ('redo_size_per_sec', 'log_switches_per_hour')
        RAC_KEYS = ('gc_cr_block_receive_time', 'gc_current_block_receive_time')
        LOAD_KEYS = ('db_time_ratio', 'aas_per_cpu', 'transactions_per_sec', 'logical_reads_per_sec')
        OS_KEYS = ('os_cpu_used_pct', 'os_swap_used_pct', 'os_load_avg')
        UNDO_TEMP_KEYS = ('undo_space_used_pct', 'temp_space_used_pct')

        if metric_key in IO_KEYS:
            return 'io'
        elif metric_key in WAIT_KEYS:
            return 'wait_event'
        elif metric_key in SQL_KEYS:
            return 'sql'
        elif metric_key in MEMORY_KEYS:
            return 'memory'
        elif metric_key in PARSE_KEYS:
            return 'parse'
        elif metric_key in REDO_KEYS:
            return 'redo'
        elif metric_key in RAC_KEYS:
            return 'rac'
        elif metric_key in LOAD_KEYS:
            return 'load'
        elif metric_key in OS_KEYS:
            return 'os'
        elif metric_key in UNDO_TEMP_KEYS:
            return 'undo_temp'
        return 'other'

    def _get_problem_title(self, metric_key: str, value: float, unit: str) -> str:
        """Generate Chinese title for a problem."""
        titles = {
            # Load
            'aas_per_cpu': f'平均活跃会话/CPU比率过高 ({value}{unit})',
            'db_time_ratio': f'DB Time远超CPU Time ({value}{unit})',
            'transactions_per_sec': f'事务量过高 ({value}{unit})',
            'logical_reads_per_sec': f'逻辑读/秒过高 ({value}{unit})',
            'physical_reads_per_sec': f'物理读IOPS过高 ({value}{unit})',
            # Wait events
            'top_event_pct_db_time': f'Top等待事件占比过高 ({value}{unit})',
            'db_file_sequential_read_avg_wait': f'db file sequential read 平均等待过高 ({value}{unit})',
            'db_file_scattered_read_avg_wait': f'db file scattered read 平均等待过高 ({value}{unit})',
            'log_file_sync_avg_wait': f'log file sync 平均等待过高 ({value}{unit})',
            'log_file_parallel_write_avg_wait': f'log file parallel write 平均等待过高 ({value}{unit})',
            'buffer_busy_waits_avg_wait': f'buffer busy waits 平均等待过高 ({value}{unit})',
            'read_by_other_session_avg_wait': f'read by other session 平均等待过高 ({value}{unit})',
            'enq_tx_row_lock_avg_wait': f'行锁等待时间过高 ({value}{unit})',
            # Parse
            'hard_parse_pct': f'硬解析比例过高 ({value}{unit})',
            'hard_parses_per_sec': f'每秒硬解析次数过高 ({value}{unit})',
            'total_parses_per_sec': f'每秒总解析次数过高 ({value}{unit})',
            'execute_to_parse_pct': f'Execute to Parse%过低 ({value}{unit})',
            'soft_parse_pct': f'软解析比例过低 ({value}{unit})',
            'parse_cpu_to_elapsed_pct': f'Parse CPU/Elapsed%过低 ({value}{unit})',
            # SQL
            'buffer_gets_per_exec': f'SQL逻辑读过高 ({value}{unit})',
            'disk_reads_per_exec': f'SQL物理读过高 ({value}{unit})',
            'sql_executions_per_sec': f'SQL执行频率过高 ({value}{unit})',
            'top1_sql_pct_db_time': f'Top1 SQL占DB Time过高 ({value}{unit})',
            # Memory
            'buffer_cache_hit_ratio': f'Buffer Cache 命中率过低 ({value}{unit})',
            'library_cache_hit_ratio': f'Library Cache 命中率过低 ({value}{unit})',
            'shared_pool_free_pct': f'Shared Pool 空闲不足 ({value}{unit})',
            'in_memory_sort_pct': f'内存排序比例过低 ({value}{unit})',
            'latch_hit_pct': f'Latch命中率过低 ({value}{unit})',
            'pga_over_allocation_count': f'PGA过度分配 ({value}{unit})',
            # I/O
            'avg_read_time': f'I/O平均读取延迟过高 ({value}{unit})',
            'avg_write_time': f'I/O平均写入延迟过高 ({value}{unit})',
            'tablespace_io_pct': f'单表空间I/O过于集中 ({value}{unit})',
            # Redo
            'redo_size_per_sec': f'Redo生成量过大 ({value}{unit})',
            'log_switches_per_hour': f'日志切换过于频繁 ({value}{unit})',
            # RAC
            'gc_cr_block_receive_time': f'RAC GC CR块传输延迟过高 ({value}{unit})',
            'gc_current_block_receive_time': f'RAC GC Current块传输延迟过高 ({value}{unit})',
            # Undo / Temp
            'undo_space_used_pct': f'Undo表空间使用率过高 ({value}{unit})',
            'temp_space_used_pct': f'临时表空间使用率过高 ({value}{unit})',
            # OS
            'os_cpu_used_pct': f'OS CPU使用率过高 ({value}{unit})',
            'os_swap_used_pct': f'OS Swap使用过多 ({value}{unit})',
            'os_load_avg': f'OS负载均值过高 ({value}{unit})',
        }
        return titles.get(metric_key, f'{metric_key} 异常 ({value}{unit})')

    def score_all(self, parsed_data: dict[str, Any], report: Any = None, threshold_overrides: dict[str, tuple] | None = None) -> list[dict]:
        """Score all extracted metrics. Returns list of problem dicts."""
        if not parsed_data:
            return []

        # Apply workload-specific threshold overrides
        original_thresholds = self.thresholds
        if threshold_overrides:
            self.thresholds = dict(original_thresholds)
            self.thresholds.update(threshold_overrides)

        problems = []
        scored_metrics = {}  # metric_key -> value

        # -----------------------------------------------------------------
        # 1. load_profile computed values
        # -----------------------------------------------------------------
        try:
            load_profile = parsed_data.get('load_profile')
            if load_profile and isinstance(load_profile, dict):
                computed = load_profile.get('computed', {})
                if computed:
                    db_time = self._safe_float(computed.get('db_time'))
                    db_cpu = self._safe_float(computed.get('db_cpu'))
                    if db_cpu > 0:
                        scored_metrics['db_time_ratio'] = db_time / db_cpu

                    hard_parses = self._safe_float(computed.get('hard_parses'))
                    parses = self._safe_float(computed.get('parses'))
                    if parses > 0:
                        scored_metrics['hard_parse_pct'] = hard_parses / parses * 100
                        scored_metrics['hard_parses_per_sec'] = hard_parses
                        scored_metrics['total_parses_per_sec'] = parses

                    redo_size = computed.get('redo_size')
                    if redo_size is not None:
                        scored_metrics['redo_size_per_sec'] = self._safe_float(redo_size)

                    # New: transactions, logical reads, physical reads, executes
                    txn = self._safe_float(computed.get('transactions'))
                    if txn > 0:
                        scored_metrics['transactions_per_sec'] = txn
                    logical_reads = self._safe_float(computed.get('logical_reads'))
                    if logical_reads > 0:
                        scored_metrics['logical_reads_per_sec'] = logical_reads
                    physical_reads = self._safe_float(computed.get('physical_reads'))
                    if physical_reads > 0:
                        scored_metrics['physical_reads_per_sec'] = physical_reads
                    executes = self._safe_float(computed.get('executes'))
                    if executes > 0:
                        scored_metrics['sql_executions_per_sec'] = executes
        except Exception:
            logger.debug("score_all load_profile failed", exc_info=True)
            pass

        # -----------------------------------------------------------------
        # 2. top_events - score avg_wait for all known events
        # -----------------------------------------------------------------
        try:
            top_events = parsed_data.get('top_events', [])
            if top_events and isinstance(top_events, list):
                if len(top_events) > 0:
                    first_event = top_events[0]
                    pct_val = self._safe_float(first_event.get('pct_db_time'))
                    if pct_val > 0:
                        scored_metrics['top_event_pct_db_time'] = pct_val

                # Map event names -> metric keys for avg_wait scoring
                EVENT_AVG_WAIT_MAP = {
                    'db file sequential read': 'db_file_sequential_read_avg_wait',
                    'db file scattered read': 'db_file_scattered_read_avg_wait',
                    'log file sync': 'log_file_sync_avg_wait',
                    'log file parallel write': 'log_file_parallel_write_avg_wait',
                    'buffer busy waits': 'buffer_busy_waits_avg_wait',
                    'read by other session': 'read_by_other_session_avg_wait',
                    'enq: tx - row lock contention': 'enq_tx_row_lock_avg_wait',
                }
                # Also track top1 SQL pct from top events for DB CPU
                for event in top_events:
                    event_name = (event.get('name') or event.get('event') or '').strip().lower()
                    avg_wait = self._safe_float(event.get('avg_wait'))
                    for pattern, metric_key in EVENT_AVG_WAIT_MAP.items():
                        if event_name == pattern and avg_wait > 0:
                            scored_metrics[metric_key] = avg_wait
                            break
        except Exception:
            logger.debug("score_all top_events failed", exc_info=True)
            pass

        # -----------------------------------------------------------------
        # 3. top_sql - buffer gets, disk reads, top1 pct
        # -----------------------------------------------------------------
        try:
            top_sql = parsed_data.get('top_sql', {})
            if top_sql and isinstance(top_sql, dict):
                sql_by_gets = top_sql.get('SQL ordered by Gets') or top_sql.get('sql_by_gets') or []
                if sql_by_gets and len(sql_by_gets) > 0:
                    top_entry = sql_by_gets[0]
                    gets_per_exec = self._safe_float(
                        top_entry.get('gets_per_exec') or top_entry.get('gets/exec')
                        or top_entry.get('Buffer Gets per Exec', 0)
                    )
                    if gets_per_exec > 0:
                        scored_metrics['buffer_gets_per_exec'] = gets_per_exec

                sql_by_reads = top_sql.get('SQL ordered by Reads') or top_sql.get('sql_by_reads') or []
                if sql_by_reads and len(sql_by_reads) > 0:
                    top_entry = sql_by_reads[0]
                    reads_per_exec = self._safe_float(
                        top_entry.get('reads_per_exec') or top_entry.get('reads/exec')
                        or top_entry.get('Physical Reads per Exec', 0)
                    )
                    if reads_per_exec > 0:
                        scored_metrics['disk_reads_per_exec'] = reads_per_exec

                # Top1 SQL by Elapsed Time as % of DB Time
                sql_by_elapsed = top_sql.get('SQL ordered by Elapsed Time') or []
                if sql_by_elapsed and len(sql_by_elapsed) > 0:
                    top1_pct = self._safe_float(
                        sql_by_elapsed[0].get('%Total') or sql_by_elapsed[0].get('pct_db_time')
                        or sql_by_elapsed[0].get('% Total DB Time', 0)
                    )
                    if top1_pct > 0:
                        scored_metrics['top1_sql_pct_db_time'] = top1_pct
        except Exception:
            logger.debug("score_all top_sql failed", exc_info=True)
            pass

        # -----------------------------------------------------------------
        # 4. instance_efficiency - ALL efficiency metrics
        # -----------------------------------------------------------------
        try:
            instance_eff = parsed_data.get('instance_efficiency', [])
            if instance_eff:
                # Unified extraction helper
                def _match_efficiency(name, val):
                    nl = name.lower() if name else ''
                    fval = self._safe_float(val)
                    if fval <= 0:
                        return
                    if 'buffer' in nl and ('hit' in nl or 'nowait' in nl):
                        scored_metrics.setdefault('buffer_cache_hit_ratio', fval)
                    elif 'library' in nl and 'hit' in nl:
                        scored_metrics.setdefault('library_cache_hit_ratio', fval)
                    elif 'soft parse' in nl:
                        scored_metrics.setdefault('soft_parse_pct', fval)
                    elif 'execute to parse' in nl:
                        scored_metrics.setdefault('execute_to_parse_pct', fval)
                    elif 'latch hit' in nl:
                        scored_metrics.setdefault('latch_hit_pct', fval)
                    elif 'in-memory sort' in nl or 'memory sort' in nl:
                        scored_metrics.setdefault('in_memory_sort_pct', fval)
                    elif 'parse cpu' in nl and 'elapsed' in nl:
                        scored_metrics.setdefault('parse_cpu_to_elapsed_pct', fval)
                    elif 'non-parse cpu' in nl:
                        pass  # informational, not scored separately

                if isinstance(instance_eff, list):
                    for item in instance_eff:
                        name = (item.get('name') or item.get('stat_name')
                                or item.get('metric') or '').strip()
                        val = item.get('value') or item.get('pct')
                        _match_efficiency(name, val)
                elif isinstance(instance_eff, dict):
                    for name, val in instance_eff.items():
                        _match_efficiency(name, val)
        except Exception:
            logger.debug("score_all instance_efficiency failed", exc_info=True)
            pass

        # -----------------------------------------------------------------
        # 5. rac_stats - gc cr + gc current
        # -----------------------------------------------------------------
        try:
            rac_stats = parsed_data.get('rac_stats', [])
            if rac_stats and isinstance(rac_stats, list):
                for stat in rac_stats:
                    name = (stat.get('name') or stat.get('stat_name') or '').strip().lower()
                    val = self._safe_float(stat.get('value') or stat.get('avg_wait'))
                    if val > 0:
                        if 'gc cr block receive time' in name:
                            scored_metrics['gc_cr_block_receive_time'] = val
                        elif 'gc current block receive time' in name:
                            scored_metrics['gc_current_block_receive_time'] = val
        except Exception:
            logger.debug("score_all rac_stats failed", exc_info=True)
            pass

        # -----------------------------------------------------------------
        # 6. AAS/CPU
        # -----------------------------------------------------------------
        try:
            if report and hasattr(report, 'cpu_count') and report.cpu_count:
                cpu_count = self._safe_float(report.cpu_count)
                load_profile = parsed_data.get('load_profile')
                if load_profile and isinstance(load_profile, dict):
                    computed = load_profile.get('computed', {})
                    db_time = self._safe_float(computed.get('db_time'))
                    elapsed = self._safe_float(computed.get('elapsed_seconds') or computed.get('elapsed'))
                    if elapsed > 0 and cpu_count > 0:
                        aas = db_time / elapsed
                        aas_per_cpu = aas / cpu_count
                        scored_metrics['aas_per_cpu'] = aas_per_cpu
        except Exception:
            logger.debug("score_all aas_per_cpu failed", exc_info=True)
            pass

        # -----------------------------------------------------------------
        # 7. I/O stats - read/write latency, tablespace concentration
        # -----------------------------------------------------------------
        try:
            io_stats = parsed_data.get('io_stats', [])
            if io_stats and isinstance(io_stats, list):
                total_reads = 0
                max_reads = 0
                for io in io_stats:
                    reads = self._safe_float(io.get('Physical Reads', io.get('reads', io.get('physical_reads', 0))))
                    total_reads += reads
                    if reads > max_reads:
                        max_reads = reads
                    # avg read/write time per tablespace
                    avg_rd = self._safe_float(io.get('Av Rd(ms)', io.get('avg_read_ms', io.get('Av Rd', 0))))
                    avg_wr = self._safe_float(io.get('Av Wr(ms)', io.get('avg_write_ms', io.get('Av Wr', 0))))
                    if avg_rd > scored_metrics.get('avg_read_time', 0):
                        scored_metrics['avg_read_time'] = avg_rd
                    if avg_wr > scored_metrics.get('avg_write_time', 0):
                        scored_metrics['avg_write_time'] = avg_wr
                if total_reads > 0 and max_reads > 0:
                    scored_metrics['tablespace_io_pct'] = (max_reads / total_reads) * 100
        except Exception:
            logger.debug("score_all io_stats failed", exc_info=True)
            pass

        # -----------------------------------------------------------------
        # 8. OS stats
        # -----------------------------------------------------------------
        try:
            os_stats = parsed_data.get('os_stats', [])
            if os_stats and isinstance(os_stats, list):
                busy_time = idle_time = 0
                total_physical_mem = 0
                free_swap = total_swap = 0
                for stat in os_stats:
                    name = (stat.get('name') or stat.get('stat_name') or stat.get('Statistic', '')).strip().lower()
                    val = self._safe_float(stat.get('value') or stat.get('Value', 0))
                    if 'busy_time' in name or 'busy time' in name:
                        busy_time = val
                    elif 'idle_time' in name or 'idle time' in name:
                        idle_time = val
                    elif 'load' in name and ('avg' in name or 'average' in name):
                        if val > 0:
                            cpu_count = 1
                            if report and hasattr(report, 'cpu_count') and report.cpu_count:
                                cpu_count = max(1, report.cpu_count)
                            scored_metrics['os_load_avg'] = val / cpu_count
                    elif 'physical memory' in name and 'total' in name:
                        total_physical_mem = val
                    elif 'free swap' in name or 'swap free' in name:
                        free_swap = val
                    elif ('total swap' in name or 'swap space' in name) and 'free' not in name:
                        total_swap = val
                if busy_time > 0 and (busy_time + idle_time) > 0:
                    scored_metrics['os_cpu_used_pct'] = (busy_time / (busy_time + idle_time)) * 100
                if total_swap > 0:
                    used_swap = total_swap - free_swap
                    scored_metrics['os_swap_used_pct'] = (used_swap / total_swap) * 100
            elif os_stats and isinstance(os_stats, dict):
                if os_stats.get('cpu_used_pct'):
                    scored_metrics['os_cpu_used_pct'] = self._safe_float(os_stats['cpu_used_pct'])
                if os_stats.get('load_avg'):
                    scored_metrics['os_load_avg'] = self._safe_float(os_stats['load_avg'])
                if os_stats.get('swap_used_pct'):
                    scored_metrics['os_swap_used_pct'] = self._safe_float(os_stats['swap_used_pct'])
        except Exception:
            logger.debug("score_all os_stats failed", exc_info=True)
            pass

        # -----------------------------------------------------------------
        # 9. memory_stats - shared pool free, PGA over-allocation
        # -----------------------------------------------------------------
        try:
            memory_stats = parsed_data.get('memory_stats', {})
            if memory_stats:
                # SGA sub-components
                sga_list = memory_stats.get('SGA', []) if isinstance(memory_stats, dict) else []
                if isinstance(sga_list, list):
                    total_sga = 0
                    free_mem = 0
                    for item in sga_list:
                        name = (item.get('Pool', '') + ' ' + item.get('Name', item.get('name', ''))).lower()
                        size = self._safe_float(item.get('Size', item.get('size', item.get('Bytes', 0))))
                        total_sga += size
                        if 'free' in name and 'shared pool' in name:
                            free_mem += size
                    if total_sga > 0 and free_mem > 0:
                        scored_metrics['shared_pool_free_pct'] = (free_mem / total_sga) * 100

                # PGA stats
                pga_list = memory_stats.get('PGA', []) if isinstance(memory_stats, dict) else []
                if isinstance(pga_list, list):
                    for item in pga_list:
                        name = (item.get('name', item.get('Name', item.get('Statistic', '')))).lower()
                        val = self._safe_float(item.get('value', item.get('Value', item.get('Bytes', 0))))
                        if 'over alloc' in name and val > 0:
                            scored_metrics['pga_over_allocation_count'] = val

                # Advisory sections
                advisories = parsed_data.get('advisories', {})
                if isinstance(advisories, dict):
                    pga_advice = advisories.get('PGA', [])
                    if isinstance(pga_advice, list):
                        for row in pga_advice:
                            over = self._safe_float(row.get('Over Alloc', row.get('over_allocation_count', 0)))
                            if over > 0:
                                scored_metrics.setdefault('pga_over_allocation_count', over)
        except Exception:
            logger.debug("score_all memory_stats failed", exc_info=True)
            pass

        # -----------------------------------------------------------------
        # 10. redo_stats - log switches per hour
        # -----------------------------------------------------------------
        try:
            redo_stats = parsed_data.get('redo_stats', {})
            if redo_stats and isinstance(redo_stats, dict):
                log_switches = self._safe_float(redo_stats.get('log_switches', 0))
                elapsed_seconds = self._safe_float(
                    parsed_data.get('snap_info', {}).get('elapsed_seconds', 0)
                )
                if log_switches > 0 and elapsed_seconds > 0:
                    scored_metrics['log_switches_per_hour'] = log_switches / (elapsed_seconds / 3600)
                elif log_switches > 0:
                    scored_metrics['log_switches_per_hour'] = log_switches  # assume per hour
        except Exception:
            logger.debug("score_all redo_stats failed", exc_info=True)
            pass

        # -----------------------------------------------------------------
        # 11. parse_stats supplementary
        # -----------------------------------------------------------------
        try:
            parse_stats = parsed_data.get('parse_stats', {})
            if parse_stats and isinstance(parse_stats, dict):
                if parse_stats.get('execute_to_parse_pct') and 'execute_to_parse_pct' not in scored_metrics:
                    scored_metrics['execute_to_parse_pct'] = self._safe_float(parse_stats['execute_to_parse_pct'])
                if parse_stats.get('parse_cpu_to_elapsed_pct') and 'parse_cpu_to_elapsed_pct' not in scored_metrics:
                    scored_metrics['parse_cpu_to_elapsed_pct'] = self._safe_float(parse_stats['parse_cpu_to_elapsed_pct'])
                if parse_stats.get('hard_parse_pct') and 'hard_parse_pct' not in scored_metrics:
                    scored_metrics['hard_parse_pct'] = self._safe_float(parse_stats['hard_parse_pct'])
                if parse_stats.get('hard_parses_per_sec') and 'hard_parses_per_sec' not in scored_metrics:
                    scored_metrics['hard_parses_per_sec'] = self._safe_float(parse_stats['hard_parses_per_sec'])
                if parse_stats.get('total_parses_per_sec') and 'total_parses_per_sec' not in scored_metrics:
                    scored_metrics['total_parses_per_sec'] = self._safe_float(parse_stats['total_parses_per_sec'])
        except Exception:
            logger.debug("score_all parse_stats failed", exc_info=True)
            pass

        # -----------------------------------------------------------------
        # 12. undo / temp space (from advisories or dedicated sections)
        # -----------------------------------------------------------------
        try:
            undo_stats = parsed_data.get('undo_stats', {})
            if undo_stats and isinstance(undo_stats, dict):
                used_pct = self._safe_float(undo_stats.get('used_pct', 0))
                if used_pct > 0:
                    scored_metrics['undo_space_used_pct'] = used_pct
            temp_stats = parsed_data.get('temp_stats', {})
            if temp_stats and isinstance(temp_stats, dict):
                used_pct = self._safe_float(temp_stats.get('used_pct', 0))
                if used_pct > 0:
                    scored_metrics['temp_space_used_pct'] = used_pct
        except Exception:
            logger.debug("score_all undo_temp_stats failed", exc_info=True)
            pass

        # =================================================================
        # Build problem list from scored metrics
        # =================================================================
        for metric_key, value in scored_metrics.items():
            try:
                result = self.score_metric(metric_key, value)
                if result['level'] != 'healthy':
                    _, _, unit, _ = self.thresholds.get(metric_key, (None, None, '', ''))
                    severity_map = {'warning': 'medium', 'serious': 'high'}
                    problem = {
                        'problem_type': self._get_problem_type(metric_key),
                        'title': self._get_problem_title(metric_key, value, unit),
                        'severity': severity_map.get(result['level'], 'medium'),
                        'health_level': result['level'],
                        'metric_name': metric_key,
                        'metric_value': value,
                        'metric_unit': unit,
                        'threshold_warning': result['warning_threshold'],
                        'threshold_serious': result['serious_threshold'],
                        'evidence': result['evidence'],
                    }
                    problems.append(problem)
            except Exception:
                logger.debug("score_all threshold evaluation failed", exc_info=True)
                pass

        # Restore original thresholds if overrides were applied
        if threshold_overrides:
            self.thresholds = original_thresholds

        return problems


