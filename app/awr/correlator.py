"""Cross-dimension correlation analyzer."""
from __future__ import annotations

import logging
from typing import Any

from .utils import _safe_float

logger = logging.getLogger(__name__)


class CorrelationAnalyzer:
    """Correlate metrics across dimensions to identify root causes."""

    # Correlation rules: each rule defines a chain of evidence
    CORRELATION_RULES = [
        {'name': 'io_sql', 'trigger': ['db_file_sequential_read', 'db_file_scattered_read'],
         'check': 'top_sql_gets_reads'},
        {'name': 'cpu_sql', 'trigger': ['cpu', 'db_time_ratio'],
         'check': 'top_sql_cpu'},
        {'name': 'redo_commit', 'trigger': ['log_file_sync'],
         'check': 'redo_transactions'},
        {'name': 'parse', 'trigger': ['library_cache', 'latch'],
         'check': 'hard_parse_pct'},
        {'name': 'rac', 'trigger': ['gc'],
         'check': 'rac_stats'},
        {'name': 'memory', 'trigger': ['buffer_cache_hit'],
         'check': 'physical_reads_sga'},
    ]

    def analyze(self, parsed_data: dict[str, Any], problems: list[dict]) -> list[dict]:
        """Analyze correlations between identified problems and metrics.
        Returns list of correlation findings."""
        if not parsed_data or not problems:
            return []
        findings = []
        findings.extend(self._check_io_sql_correlation(parsed_data, problems))
        findings.extend(self._check_cpu_sql_correlation(parsed_data, problems))
        findings.extend(self._check_redo_commit_correlation(parsed_data, problems))
        findings.extend(self._check_parse_correlation(parsed_data, problems))
        findings.extend(self._check_rac_correlation(parsed_data, problems))
        findings.extend(self._check_memory_correlation(parsed_data, problems))
        findings.extend(self._check_temp_pga_correlation(parsed_data, problems))
        findings.extend(self._check_lock_sql_correlation(parsed_data, problems))
        findings.extend(self._check_os_db_correlation(parsed_data, problems))
        findings.extend(self._check_segment_sql_correlation(parsed_data, problems))
        findings.extend(self._check_composite_patterns(parsed_data, problems))
        return findings

    def _check_io_sql_correlation(self, parsed_data: dict[str, Any], problems: list[dict]) -> list[dict]:
        """db file sequential/scattered read high -> check Top SQL buffer gets/reads."""
        findings = []
        io_problems = [p for p in problems if p.get('metric_name', '') and
                       ('db_file_sequential_read' in p.get('metric_name', '') or
                        'db_file_scattered_read' in p.get('metric_name', ''))]
        if not io_problems:
            return findings
        top_sql = parsed_data.get('top_sql', {}) or {}
        sql_by_gets = top_sql.get('SQL ordered by Gets', []) or []
        sql_by_reads = top_sql.get('SQL ordered by Reads', []) or []
        for io_problem in io_problems:
            evidence = []
            pct = io_problem.get('metric_value', 0)
            event_name = io_problem.get('event_name', io_problem.get('metric_name', ''))
            evidence.append(f"{event_name} \u5360 DB Time {pct}%")
            for sql in sql_by_gets[:3]:
                sql_id = sql.get('sql_id', sql.get('SQL Id', 'unknown'))
                gets = sql.get('buffer_gets_per_exec', sql.get('Buffer Gets per Exec', 0))
                if gets:
                    evidence.append(f"SQL_ID={sql_id} Buffer Gets/Exec={gets}")
            for sql in sql_by_reads[:3]:
                sql_id = sql.get('sql_id', sql.get('SQL Id', 'unknown'))
                reads = sql.get('disk_reads_per_exec', sql.get('Physical Reads per Exec', 0))
                if reads:
                    evidence.append(f"SQL_ID={sql_id} Disk Reads/Exec={reads}")
            if len(evidence) > 1:
                findings.append({
                    'title': 'I/O\u7b49\u5f85\u4e0e\u9ad8\u903b\u8f91\u8bfbSQL\u5173\u8054',
                    'trigger_problem': io_problem.get('title', event_name),
                    'related_evidence': evidence,
                    'root_cause': '\u5b58\u5728\u9ad8\u903b\u8f91\u8bfbSQL\u5bfc\u81f4\u5927\u91cf\u5355\u5757\u8bfbI/O\u7b49\u5f85',
                    'suggestion': '\u4f18\u5148\u4f18\u5316Top SQL\u6267\u884c\u8ba1\u5212\u548c\u7d22\u5f15\u9009\u62e9\u6027'
                })
        return findings

    def _check_cpu_sql_correlation(self, parsed_data: dict[str, Any], problems: list[dict]) -> list[dict]:
        """CPU high -> check SQL CPU time and buffer gets."""
        findings = []
        cpu_problems = [p for p in problems if p.get('metric_name', '') and
                        ('cpu' in p.get('metric_name', '').lower() or
                         'db_time_ratio' in p.get('metric_name', ''))]
        if not cpu_problems:
            return findings
        top_sql = parsed_data.get('top_sql', {}) or {}
        sql_by_cpu = top_sql.get('SQL ordered by CPU Time', []) or []
        for cpu_problem in cpu_problems:
            evidence = []
            evidence.append(f"{cpu_problem.get('title', 'CPU\u95ee\u9898')}")
            for sql in sql_by_cpu[:3]:
                sql_id = sql.get('sql_id', sql.get('SQL Id', 'unknown'))
                cpu_time = sql.get('cpu_time_s', sql.get('CPU Time (s)', 0))
                if cpu_time:
                    evidence.append(f"SQL_ID={sql_id} CPU Time={cpu_time}s")
            if len(evidence) > 1:
                findings.append({
                    'title': 'CPU\u74f6\u9888\u4e0e\u9ad8CPU\u6d88\u8017SQL\u5173\u8054',
                    'trigger_problem': cpu_problem.get('title', 'CPU\u4f7f\u7528\u7387\u9ad8'),
                    'related_evidence': evidence,
                    'root_cause': '\u5b58\u5728\u9ad8CPU\u6d88\u8017\u7684SQL\u8bed\u53e5\u5bfc\u81f4CPU\u8d44\u6e90\u7d27\u5f20',
                    'suggestion': '\u4f18\u5316Top CPU SQL\u7684\u6267\u884c\u8ba1\u5212\uff0c\u51cf\u5c11\u903b\u8f91\u8bfb\u548c\u8ba1\u7b97\u91cf'
                })
        return findings

    def _check_redo_commit_correlation(self, parsed_data: dict[str, Any], problems: list[dict]) -> list[dict]:
        """log file sync high -> check redo size, commit frequency, log file parallel write."""
        findings = []
        log_problems = [p for p in problems if p.get('metric_name', '') and
                        'log_file_sync' in p.get('metric_name', '')]
        if not log_problems:
            return findings
        load_profile = parsed_data.get('load_profile', {})
        if isinstance(load_profile, dict):
            computed = load_profile.get('computed', {})
        else:
            computed = {}
        redo_size = computed.get('redo_size', 0)
        transactions_per_sec = computed.get('transactions', 0)
        for log_problem in log_problems:
            evidence = []
            evidence.append(f"log file sync \u5e73\u5747\u7b49\u5f85 {log_problem.get('metric_value', 0)}ms")
            if redo_size > 0:
                evidence.append(f"Redo Size/Sec = {redo_size:.0f} bytes")
            if transactions_per_sec > 0:
                evidence.append(f"Transactions/Sec = {transactions_per_sec:.1f}")
            if redo_size > 50_000_000:
                evidence.append('Redo\u751f\u6210\u91cf\u8fc7\u5927')
            if transactions_per_sec > 100:
                evidence.append('\u63d0\u4ea4\u9891\u7387\u8fc7\u9ad8')
            findings.append({
                'title': 'Redo\u65e5\u5fd7\u540c\u6b65\u4e0e\u63d0\u4ea4\u9891\u7387\u5173\u8054',
                'trigger_problem': log_problem.get('title', 'log file sync\u7b49\u5f85'),
                'related_evidence': evidence,
                'root_cause': '\u9891\u7e41\u63d0\u4ea4\u6216\u5927\u91cfredo\u751f\u6210\u5bfc\u81f4\u65e5\u5fd7\u540c\u6b65\u7b49\u5f85',
                'suggestion': '\u51cf\u5c11\u4e0d\u5fc5\u8981\u7684\u9891\u7e41COMMIT\uff0c\u5408\u5e76\u5c0f\u4e8b\u52a1\uff0c\u68c0\u67e5redo\u65e5\u5fd7I/O\u6027\u80fd'
            })
        return findings

    def _check_parse_correlation(self, parsed_data: dict[str, Any], problems: list[dict]) -> list[dict]:
        """library cache / latch high -> check hard parse ratio."""
        findings = []
        parse_problems = [p for p in problems if p.get('metric_name', '') and
                          ('library_cache' in p.get('metric_name', '') or
                           'latch' in p.get('metric_name', '').lower())]
        if not parse_problems:
            return findings
        parse_stats = parsed_data.get('parse_stats', {}) or {}
        hard_parse_pct = parse_stats.get('hard_parse_pct', 0)
        for problem in parse_problems:
            evidence = []
            evidence.append(f"{problem.get('title', 'Library Cache\u95ee\u9898')}")
            if hard_parse_pct:
                evidence.append(f"\u786c\u89e3\u6790\u6bd4\u4f8b = {hard_parse_pct}%")
            if hard_parse_pct and float(hard_parse_pct) > 10:
                evidence.append('\u786c\u89e3\u6790\u6bd4\u4f8b\u8fc7\u9ad8\uff0c\u6d88\u8017\u5927\u91cfshared pool\u8d44\u6e90')
            findings.append({
                'title': 'Library Cache\u4e89\u7528\u4e0e\u786c\u89e3\u6790\u5173\u8054',
                'trigger_problem': problem.get('title', 'Library Cache\u95ee\u9898'),
                'related_evidence': evidence,
                'root_cause': '\u5927\u91cf\u786c\u89e3\u6790\u5bfc\u81f4Library Cache\u548cLatch\u4e89\u7528',
                'suggestion': '\u63a8\u52a8\u5e94\u7528\u4f7f\u7528\u7ed1\u5b9a\u53d8\u91cf\uff0c\u51cf\u5c11\u786c\u89e3\u6790\u6b21\u6570'
            })
        return findings

    def _check_rac_correlation(self, parsed_data: dict[str, Any], problems: list[dict]) -> list[dict]:
        """gc wait high -> check RAC interconnect and hot SQL."""
        findings = []
        gc_problems = [p for p in problems if p.get('metric_name', '') and
                       'gc' in p.get('metric_name', '').lower()]
        if not gc_problems:
            return findings
        rac_stats = parsed_data.get('rac_stats', []) or []
        for problem in gc_problems:
            evidence = []
            evidence.append(f"{problem.get('title', 'GC\u7b49\u5f85\u95ee\u9898')}")
            for stat in rac_stats[:3]:
                name = stat.get('name', stat.get('Statistic', ''))
                value = stat.get('value', stat.get('Total', ''))
                if name and value:
                    evidence.append(f"{name} = {value}")
            findings.append({
                'title': 'RAC\u8282\u70b9\u95f4GC\u7b49\u5f85\u5173\u8054',
                'trigger_problem': problem.get('title', 'GC\u7b49\u5f85'),
                'related_evidence': evidence,
                'root_cause': 'RAC\u8282\u70b9\u95f4\u6570\u636e\u5757\u4f20\u8f93\u5ef6\u8fdf\u5bfc\u81f4GC\u7b49\u5f85',
                'suggestion': '\u68c0\u67e5RAC\u4e92\u8054\u7f51\u7edc\u6027\u80fd\uff0c\u8bc6\u522b\u70ed\u70b9\u5bf9\u8c61\u5e76\u505a\u5b9e\u4f8b\u9694\u79bb'
            })
        return findings

    def _check_memory_correlation(self, parsed_data: dict[str, Any], problems: list[dict]) -> list[dict]:
        """Buffer cache hit low -> check physical reads and SGA sizing."""
        findings = []
        mem_problems = [p for p in problems if p.get('metric_name', '') and
                        'buffer_cache_hit' in p.get('metric_name', '')]
        if not mem_problems:
            return findings
        memory_stats = parsed_data.get('memory_stats', {}) or {}
        io_stats = parsed_data.get('io_stats', []) or []
        for problem in mem_problems:
            evidence = []
            evidence.append(f"Buffer Cache\u547d\u4e2d\u7387 = {problem.get('metric_value', 0)}%")
            if memory_stats:
                sga_size = memory_stats.get('sga_size', memory_stats.get('SGA Size', ''))
                if sga_size:
                    evidence.append(f"SGA Size = {sga_size}")
                buffer_cache = memory_stats.get('buffer_cache_size', memory_stats.get('Buffer Cache Size', ''))
                if buffer_cache:
                    evidence.append(f"Buffer Cache Size = {buffer_cache}")
            for io in io_stats[:2]:
                name = io.get('name', io.get('Tablespace', ''))
                reads = io.get('physical_reads', io.get('Physical Reads', ''))
                if name and reads:
                    evidence.append(f"{name} Physical Reads = {reads}")
            findings.append({
                'title': 'Buffer Cache\u4e0d\u8db3\u4e0e\u7269\u7406\u8bfb\u5173\u8054',
                'trigger_problem': problem.get('title', 'Buffer Cache\u547d\u4e2d\u7387\u4f4e'),
                'related_evidence': evidence,
                'root_cause': 'Buffer Cache\u8fc7\u5c0f\u6216\u5b58\u5728\u5927\u91cf\u5168\u8868\u626b\u63cf\u5bfc\u81f4\u7269\u7406\u8bfb\u589e\u591a',
                'suggestion': '\u8003\u8651\u589e\u5927db_cache_size\uff0c\u68c0\u67e5\u5168\u8868\u626b\u63cfSQL\u5e76\u4f18\u5316'
            })
        return findings

    def _check_temp_pga_correlation(self, parsed_data: dict[str, Any], problems: list[dict]) -> list[dict]:
        """direct path read/write temp high -> check PGA and sort spills."""
        findings = []
        temp_problems = [p for p in problems if p.get('metric_name', '') and
                         ('temp_space' in p.get('metric_name', '') or
                          'in_memory_sort' in p.get('metric_name', '') or
                          'pga_over_allocation' in p.get('metric_name', ''))]
        if not temp_problems:
            top_events = parsed_data.get('top_events', []) or []
            for evt in top_events:
                ename = (evt.get('event', '') or '').lower()
                pct = float(evt.get('pct_db_time', 0) or 0)
                if 'direct path' in ename and 'temp' in ename and pct > 5:
                    temp_problems.append({
                        'metric_name': 'direct_path_temp',
                        'title': f'{evt.get("event", "")} 占 DB Time {pct}%',
                        'metric_value': pct
                    })
        if not temp_problems:
            return findings
        load_profile = parsed_data.get('load_profile', {})
        computed = load_profile.get('computed', {}) if isinstance(load_profile, dict) else {}
        for problem in temp_problems:
            evidence = [f"{problem.get('title', '临时表空间/PGA问题')}"]
            if computed.get('physical_reads'):
                evidence.append(f"Physical Reads/Sec = {computed['physical_reads']}")
            evidence.append('排序/Hash操作溢出到临时表空间，PGA可能不足')
            findings.append({
                'title': '临时表空间压力与PGA不足关联',
                'trigger_problem': problem.get('title', '临时表空间/PGA问题'),
                'related_evidence': evidence,
                'root_cause': 'PGA不足导致排序/Hash Join溢出到磁盘临时表空间',
                'suggestion': '增大PGA_AGGREGATE_TARGET，优化大排序SQL减少排序集'
            })
        return findings

    def _check_lock_sql_correlation(self, parsed_data: dict[str, Any], problems: list[dict]) -> list[dict]:
        """TX row lock / TM contention -> check SQL and segment stats."""
        findings = []
        lock_problems = [p for p in problems if p.get('metric_name', '') and
                         ('enq_tx_row_lock' in p.get('metric_name', '') or
                          'tx' in p.get('metric_name', '').lower())]
        if not lock_problems:
            top_events = parsed_data.get('top_events', []) or []
            for evt in top_events:
                ename = (evt.get('event', '') or '').lower()
                pct = float(evt.get('pct_db_time', 0) or 0)
                if ('enq: tx' in ename or 'enq: tm' in ename) and pct > 5:
                    lock_problems.append({
                        'metric_name': 'lock_event',
                        'title': f'{evt.get("event", "")} 占 DB Time {pct}%',
                        'metric_value': pct
                    })
        if not lock_problems:
            return findings
        segment_stats = parsed_data.get('segment_stats', []) or []
        top_sql = parsed_data.get('top_sql', {}) or {}
        sql_by_elapsed = top_sql.get('SQL ordered by Elapsed Time', []) or []
        for problem in lock_problems:
            evidence = [f"{problem.get('title', '锁等待问题')}"]
            for seg in segment_stats[:3]:
                seg_name = seg.get('Segment Name', seg.get('name', ''))
                if seg_name:
                    evidence.append(f"热点段: {seg_name}")
            for sql in sql_by_elapsed[:2]:
                sql_id = sql.get('sql_id', sql.get('SQL Id', ''))
                if sql_id:
                    evidence.append(f"Top SQL_ID: {sql_id}")
            findings.append({
                'title': '锁争用与热点段/SQL关联',
                'trigger_problem': problem.get('title', '锁等待'),
                'related_evidence': evidence,
                'root_cause': '热点段上的并发DML导致行锁或表锁争用',
                'suggestion': '优化事务粒度和持有时间，检查外键是否缺少索引'
            })
        return findings

    def _check_os_db_correlation(self, parsed_data: dict[str, Any], problems: list[dict]) -> list[dict]:
        """OS CPU/memory high -> correlate with DB load."""
        findings = []
        os_problems = [p for p in problems if p.get('metric_name', '') and
                       p.get('metric_name', '').startswith('os_')]
        if not os_problems:
            return findings
        load_profile = parsed_data.get('load_profile', {})
        computed = load_profile.get('computed', {}) if isinstance(load_profile, dict) else {}
        for problem in os_problems:
            evidence = [f"{problem.get('title', 'OS资源问题')}"]
            if computed.get('db_time'):
                evidence.append(f"DB Time/Sec = {computed['db_time']}")
            if computed.get('db_cpu'):
                evidence.append(f"DB CPU/Sec = {computed['db_cpu']}")
            findings.append({
                'title': 'OS资源压力与数据库负载关联',
                'trigger_problem': problem.get('title', 'OS资源问题'),
                'related_evidence': evidence,
                'root_cause': '数据库高负载消耗OS资源，或外部进程与数据库竞争资源',
                'suggestion': '优化数据库Top SQL降低资源消耗，检查非数据库进程占用'
            })
        return findings

    def _check_segment_sql_correlation(self, parsed_data: dict[str, Any], problems: list[dict]) -> list[dict]:
        """Hot segment -> correlate with Top SQL accessing that segment."""
        findings = []
        seg_problems = [p for p in problems if p.get('problem_type', '') == 'segment' or
                        ('segment' in p.get('metric_name', '').lower())]
        if not seg_problems:
            return findings
        top_sql = parsed_data.get('top_sql', {}) or {}
        sql_by_gets = top_sql.get('SQL ordered by Gets', []) or []
        for problem in seg_problems:
            evidence = [f"{problem.get('title', '热点段问题')}"]
            for sql in sql_by_gets[:3]:
                sql_id = sql.get('sql_id', sql.get('SQL Id', ''))
                gets = sql.get('buffer_gets_per_exec', sql.get('Buffer Gets per Exec', ''))
                if sql_id:
                    evidence.append(f"SQL_ID={sql_id} Gets/Exec={gets}")
            if len(evidence) > 1:
                findings.append({
                    'title': '热点段与高逻辑读SQL关联',
                    'trigger_problem': problem.get('title', '热点段'),
                    'related_evidence': evidence,
                    'root_cause': '高频SQL访问热点段导致段级争用和缓存压力',
                    'suggestion': '优化SQL减少对热点段的访问频率和范围'
                })
        return findings

    def _check_composite_patterns(self, parsed_data: dict[str, Any], problems: list[dict]) -> list[dict]:
        """Detect classic multi-symptom composite patterns from production experience.

        Unlike single-dimension correlators, these match on combinations of 3+ symptoms
        that experienced DBAs recognize as canonical problem scenarios.
        """
        findings = []

        # Build a quick-lookup set of problem signatures
        problem_keywords = set()
        problem_metrics = {}
        for p in problems:
            title = (p.get('title', '') + ' ' + p.get('evidence', '')).lower()
            problem_keywords.add(title)
            mk = p.get('metric_name', '')
            if mk:
                problem_metrics[mk] = p.get('metric_value', 0)

        combined_text = ' '.join(problem_keywords)

        # Helper: check if any keyword appears
        def has(*keywords):
            return any(k in combined_text for k in keywords)

        def has_metric(*prefixes):
            return any(any(mk.startswith(p) for p in prefixes) for mk in problem_metrics)

        # Extract commonly needed values
        load_profile = parsed_data.get('load_profile', {})
        computed = load_profile.get('computed', {}) if isinstance(load_profile, dict) else {}
        top_events = parsed_data.get('top_events', [])

        def event_pct(name_fragment):
            for evt in top_events:
                ename = (evt.get('event', evt.get('name', '')) or '').lower()
                if name_fragment in ename:
                    return float(evt.get('pct_db_time', 0) or 0)
            return 0

        txn_per_sec = float(computed.get('transactions', 0) or 0)
        redo_per_sec = float(computed.get('redo_size', 0) or 0)

        # =================================================================
        # Pattern 1: 经典绑定变量缺失链
        # hard parse高 + library cache争用 + cursor: pin S + shared pool free低
        # =================================================================
        if (has('硬解析', 'hard_parse') and
            (has('library cache', 'library_cache') or has('latch', 'shared pool') or
             event_pct('cursor: pin s') > 3)):
            evidence = []
            if has_metric('hard_parse'):
                evidence.append('硬解析比例/频率异常')
            if event_pct('cursor: pin s') > 0:
                evidence.append(f"cursor: pin S wait on X = {event_pct('cursor: pin s'):.1f}% DB Time")
            if has('shared_pool_free', 'shared pool'):
                evidence.append('Shared Pool空闲不足')
            if has('library_cache'):
                evidence.append('Library Cache命中率低')
            findings.append({
                'title': '经典模式: 绑定变量缺失导致的解析风暴',
                'trigger_problem': '硬解析 + Library Cache争用 + Cursor Mutex',
                'related_evidence': evidence,
                'root_cause': '应用未使用绑定变量，导致每次执行都硬解析新游标。'
                    '大量硬解析争抢Shared Pool内存和Library Cache Latch，'
                    '并发session在cursor: pin S wait on X上排队等待',
                'suggestion': '1. 紧急: 设置CURSOR_SHARING=FORCE临时缓解\n'
                    '2. 根本: 推动应用使用绑定变量\n'
                    '3. 增大SHARED_POOL_SIZE作为缓冲\n'
                    '4. 检查V$SQL中VERSION_COUNT异常高的游标'
            })

        # =================================================================
        # Pattern 2: 批量小事务提交风暴
        # log file sync高 + redo量大 + transactions/sec高
        # =================================================================
        if (has('log file sync', 'log_file_sync') and txn_per_sec > 50):
            redo_mb = redo_per_sec / 1e6
            avg_redo_per_txn = (redo_per_sec / txn_per_sec) if txn_per_sec > 0 else 0
            evidence = [
                'log file sync 等待异常',
                f'事务率 = {txn_per_sec:.1f}/s',
                f'Redo生成 = {redo_mb:.1f}MB/s',
            ]
            if avg_redo_per_txn < 5000 and txn_per_sec > 100:
                evidence.append(f'平均每事务Redo = {avg_redo_per_txn:.0f} bytes (极小事务)')
                findings.append({
                    'title': '经典模式: 小事务频繁提交风暴',
                    'trigger_problem': 'log file sync高 + 高事务率 + 低单事务Redo',
                    'related_evidence': evidence,
                    'root_cause': '应用逐行COMMIT或循环内频繁COMMIT，每次COMMIT都触发LGWR写redo并等待确认。'
                        f'当前每秒{txn_per_sec:.0f}个事务，每事务仅{avg_redo_per_txn:.0f}字节redo，属于典型的小事务模式',
                    'suggestion': '1. 合并事务: 每100-1000行COMMIT一次\n'
                        '2. 使用BATCH DML或FORALL批量操作\n'
                        '3. 如果是ETL加载，使用APPEND hint直接路径写入\n'
                        '4. 将redo log放到低延迟存储'
                })

        # =================================================================
        # Pattern 3: Buffer Cache不足 + Advisory建议增大
        # buffer cache hit低 + physical reads高 + Advisory有数据
        # =================================================================
        if (has('buffer cache', 'buffer_cache_hit') and has_metric('physical_reads')):
            advisories = parsed_data.get('advisories', {})
            bp_advice = advisories.get('Buffer Pool', []) if isinstance(advisories, dict) else []
            evidence = [
                'Buffer Cache命中率低',
                '物理读IOPS过高',
            ]
            if bp_advice:
                evidence.append('Buffer Pool Advisory有优化空间')
            direct_pct = event_pct('direct path read')
            if direct_pct > 10:
                evidence.append(f'direct path read = {direct_pct:.1f}% DB Time (大表绕过缓存)')
                findings.append({
                    'title': '经典模式: 大表全扫描绕过Buffer Cache',
                    'trigger_problem': 'Buffer Cache命中低 + 物理读高 + direct path read',
                    'related_evidence': evidence,
                    'root_cause': '大表(>5x buffer cache)自动走direct path read绕过缓存。'
                        '增大Buffer Cache无法解决此问题，需要从SQL层面优化',
                    'suggestion': '1. 检查Top SQL是否有不必要的全表扫描\n'
                        '2. 添加合适索引避免全扫描\n'
                        '3. 如确需全扫描，可调整_serial_direct_read或_small_table_threshold\n'
                        '4. 考虑分区表减少扫描范围'
                })
            else:
                findings.append({
                    'title': '经典模式: Buffer Cache容量不足',
                    'trigger_problem': 'Buffer Cache命中低 + 物理读高',
                    'related_evidence': evidence,
                    'root_cause': 'Buffer Cache大小不足以容纳活跃数据集，频繁的缓存淘汰导致大量物理读',
                    'suggestion': '1. 参考Buffer Pool Advisory增大DB_CACHE_SIZE\n'
                        '2. 确认SGA_TARGET允许Buffer Cache增长\n'
                        '3. 优化Top SQL减少不必要的数据访问\n'
                        '4. 检查是否有大批量操作污染缓存(CACHE vs NOCACHE)'
                })
        # =================================================================
        # Pattern 4: RAC热点块经典模式
        # gc block busy + segment热点 + TX row lock
        # =================================================================
        gc_busy_pct = event_pct('gc current block busy') + event_pct('gc cr block busy')
        if gc_busy_pct > 5:
            evidence = [f'gc block busy 合计 = {gc_busy_pct:.1f}% DB Time']
            if has('行锁', 'row lock', 'tx_row_lock', 'enq_tx'):
                evidence.append('存在TX行锁争用')
            segment_stats = parsed_data.get('segment_stats', [])
            if segment_stats:
                for seg in segment_stats[:3]:
                    seg_name = seg.get('Segment Name', seg.get('name', seg.get('segment_name', '')))
                    if seg_name:
                        evidence.append(f'热点段: {seg_name}')
            findings.append({
                'title': '经典模式: RAC跨实例热点块争用',
                'trigger_problem': 'gc block busy + 热点段 + 可能的行锁',
                'related_evidence': evidence,
                'root_cause': '多个RAC实例并发访问/修改同一数据块。gc current block busy表示远端正在修改请求的块，'
                    '常见于热点表的主键索引右侧插入、计数器表更新等场景',
                'suggestion': '1. 识别热点对象: V$SEGMENT_STATISTICS按gc_buffer_busy排序\n'
                    '2. 使用Hash分区将数据分散到不同块\n'
                    '3. 使用反转索引(Reverse Key)避免右侧插入争用\n'
                    '4. 将相关操作路由到同一RAC实例\n'
                    '5. 12.2+考虑使用Read-Mostly Locking'
            })

        # =================================================================
        # Pattern 5: PGA不足导致的排序溢出链
        # =================================================================
        direct_temp_write = event_pct('direct path write temp')
        direct_temp_read = event_pct('direct path read temp')
        if (direct_temp_write + direct_temp_read > 5 or
            has('in_memory_sort', '内存排序', 'pga_over_allocation')):
            evidence = []
            if direct_temp_write > 0:
                evidence.append(f'direct path write temp = {direct_temp_write:.1f}% DB Time')
            if direct_temp_read > 0:
                evidence.append(f'direct path read temp = {direct_temp_read:.1f}% DB Time')
            if has('in_memory_sort', '内存排序'):
                evidence.append('内存排序比例低')
            if has('pga_over_allocation'):
                evidence.append('PGA存在过度分配')
            findings.append({
                'title': '经典模式: PGA不足导致Sort/Hash溢出到磁盘',
                'trigger_problem': 'direct path temp I/O + 内存排序低 + PGA过度分配',
                'related_evidence': evidence,
                'root_cause': 'PGA工作区不足以在内存中完成排序或Hash Join操作，'
                    '数据溢出到TEMP表空间产生磁盘I/O。这在大结果集的ORDER BY、GROUP BY、'
                    'Hash Join、DISTINCT等操作中最常见',
                'suggestion': '1. 增大PGA_AGGREGATE_TARGET(物理内存的20-30%)\n'
                    '2. 优化Top SQL减少排序集大小(添加WHERE条件、使用分页)\n'
                    '3. 对大批量排序使用并行查询分摊到多个PGA\n'
                    '4. 检查TEMP表空间是否在高速存储上'
            })

        # =================================================================
        # Pattern 6: 日志切换风暴
        # =================================================================
        log_switch_pct = (event_pct('log file switch completion') +
                         event_pct('log file switch (checkpoint incomplete)') +
                         event_pct('log file switch (archiving needed)'))
        if log_switch_pct > 3 or has('日志切换', 'log_switches_per_hour'):
            evidence = []
            if log_switch_pct > 0:
                evidence.append(f'日志切换等待 = {log_switch_pct:.1f}% DB Time')
            if redo_per_sec > 0:
                evidence.append(f'Redo生成 = {redo_per_sec / 1e6:.1f}MB/s')
            redo_stats = parsed_data.get('redo_stats', {})
            log_switches = float(redo_stats.get('log_switches', 0) or 0) if isinstance(redo_stats, dict) else 0
            if log_switches > 0:
                evidence.append(f'日志切换次数 = {log_switches}')
            root_cause = '日志切换过于频繁'
            suggestion = '1. 增大redo log文件大小(建议每组1-4GB)\n2. 增加redo log组数(3-5组)'
            if event_pct('log file switch (checkpoint incomplete)') > 0:
                root_cause += '，且checkpoint跟不上切换速度'
                suggestion += '\n3. 检查db_writer_processes是否足够\n4. 增大LOG_CHECKPOINT_TIMEOUT'
            if event_pct('log file switch (archiving needed)') > 0:
                root_cause += '，归档进程跟不上'
                suggestion += '\n5. 增大LOG_ARCHIVE_MAX_PROCESSES\n6. 检查归档目的地存储性能'
            findings.append({
                'title': '经典模式: Redo日志切换风暴',
                'trigger_problem': '日志切换等待 + Redo量大',
                'related_evidence': evidence,
                'root_cause': root_cause,
                'suggestion': suggestion,
            })

        # =================================================================
        # Pattern 7: DataGuard同步模式拖慢主库
        # =================================================================
        lns_pct = event_pct('lgwr-lns wait on channel') + event_pct('lgwr wait on lns')
        lfs_pct = event_pct('log file sync')
        lfpw_pct = event_pct('log file parallel write')
        if lns_pct > 2 or (lfs_pct > 10 and lns_pct > 0):
            evidence = [
                f'log file sync = {lfs_pct:.1f}% DB Time',
                f'LGWR-LNS wait = {lns_pct:.1f}% DB Time',
                f'log file parallel write = {lfpw_pct:.1f}% DB Time',
            ]
            if lfs_pct > lfpw_pct * 2 and lfpw_pct > 0:
                evidence.append('log file sync >> log file parallel write, 差值为DG网络开销')
            findings.append({
                'title': '经典模式: Data Guard SYNC模式拖慢主库事务',
                'trigger_problem': 'log file sync高 + LGWR-LNS等待',
                'related_evidence': evidence,
                'root_cause': 'Data Guard使用SYNC传输模式时，主库每次COMMIT需等待备库确认收到redo。'
                    '网络延迟直接叠加到log file sync等待上。'
                    f'当前log file sync中约有{max(0, lfs_pct - lfpw_pct):.1f}%是DG网络开销',
                'suggestion': '1. 评估切换到ASYNC模式(牺牲零数据丢失保证)\n'
                    '2. 使用SYNC NOAFFIRM减少备库磁盘I/O等待\n'
                    '3. 优化主备间网络(降低RTT)\n'
                    '4. 增大SDU_SIZE提高网络传输效率\n'
                    '5. 检查备库apply是否跟得上'
            })
        # =================================================================
        # Pattern 8: Latch/Mutex并发瓶颈
        # =================================================================
        cursor_mutex_pct = event_pct('cursor: mutex s') + event_pct('cursor: mutex x')
        buffer_busy_pct = event_pct('buffer busy waits')
        if (has('latch_hit', 'latch命中') and (cursor_mutex_pct > 3 or buffer_busy_pct > 3)):
            evidence = []
            if has('latch_hit', 'latch命中'):
                evidence.append('Latch命中率低')
            if cursor_mutex_pct > 0:
                evidence.append(f'cursor: mutex = {cursor_mutex_pct:.1f}% DB Time')
            if buffer_busy_pct > 0:
                evidence.append(f'buffer busy waits = {buffer_busy_pct:.1f}% DB Time')
            findings.append({
                'title': '经典模式: 高并发下的Latch/Mutex瓶颈',
                'trigger_problem': 'Latch命中低 + Cursor Mutex + Buffer Busy',
                'related_evidence': evidence,
                'root_cause': '高并发访问导致内部序列化机制(Latch/Mutex)成为瓶颈。'
                    'cursor: mutex通常与高频执行的热点SQL相关，buffer busy waits与热点数据块相关',
                'suggestion': '1. 识别热点SQL(V$SQL中EXECUTIONS极高的语句)\n'
                    '2. 减少逻辑读: 优化SQL执行计划\n'
                    '3. 检查是否有多个子游标(VERSION_COUNT高)\n'
                    '4. 考虑将热点表使用Hash分区分散访问\n'
                    '5. 检查Oracle补丁 - cursor: mutex有已知bug修复'
            })

        # =================================================================
        # Pattern 9: 索引争用(序列+右侧插入)
        # =================================================================
        idx_contention_pct = event_pct('enq: tx - index contention')
        seq_load_pct = 0
        time_model = parsed_data.get('time_model', {})
        for k, v in time_model.items():
            if isinstance(v, dict) and 'sequence' in v.get('name', '').lower():
                seq_load_pct = float(v.get('pct_db_time', 0) or 0)

        if idx_contention_pct > 3 or (idx_contention_pct > 0 and seq_load_pct > 1):
            evidence = [f'enq: TX - index contention = {idx_contention_pct:.1f}% DB Time']
            if seq_load_pct > 0:
                evidence.append(f'序列加载时间 = {seq_load_pct:.1f}% DB Time')
            findings.append({
                'title': '经典模式: 单调递增主键索引右侧插入争用',
                'trigger_problem': 'TX index contention + 序列加载',
                'related_evidence': evidence,
                'root_cause': '使用序列(SEQUENCE)生成单调递增主键时，所有INSERT都集中在B-tree索引的最右叶子块，'
                    '导致该块成为热点。RAC环境下尤其严重(跨实例争用同一块)',
                'suggestion': '1. 增大SEQUENCE CACHE(1000-10000)\n'
                    '2. RAC环境使用ORDER/NOORDER + 大CACHE\n'
                    '3. 考虑反转索引(Reverse Key Index)\n'
                    '4. 使用Hash分区索引分散插入点\n'
                    '5. 18c+考虑使用Scalable Sequences'
            })

        # =================================================================
        # Pattern 10: 统计信息过期导致的执行计划退化
        # =================================================================
        if (has('buffer_gets_per_exec', 'sql逻辑读') and
            has('physical_reads', '物理读') and
            has_metric('top1_sql_pct_db_time')):
            evidence = [
                'Top SQL逻辑读/执行异常高',
                '物理读指标偏高',
                '单条SQL占DB Time比例过高',
            ]
            findings.append({
                'title': '经典模式: 可能的执行计划退化(统计信息过期)',
                'trigger_problem': 'SQL效率指标恶化 + 资源消耗集中',
                'related_evidence': evidence,
                'root_cause': '当表统计信息过期后，优化器可能选择次优执行计划(如全表扫描替代索引扫描)，'
                    '导致单条SQL的Buffer Gets和Physical Reads急剧增加',
                'suggestion': '1. 检查Top SQL的执行计划是否合理(EXPLAIN PLAN)\n'
                    '2. 查看DBA_TAB_STATISTICS.STALE_STATS是否为YES\n'
                    '3. 执行DBMS_STATS.GATHER_TABLE_STATS更新统计信息\n'
                    '4. 使用SQL Plan Baseline(SPM)锁定好的执行计划\n'
                    '5. 设置统计信息自动收集窗口'
            })

        # =================================================================
        # Pattern 11: ITL争用(高并发DML小表)
        # =================================================================
        itl_pct = event_pct('enq: tx - allocate itl entry')
        if itl_pct > 2 or (itl_pct > 0 and buffer_busy_pct > 5):
            evidence = [f'enq: TX - allocate ITL entry = {itl_pct:.1f}% DB Time']
            if buffer_busy_pct > 0:
                evidence.append(f'buffer busy waits = {buffer_busy_pct:.1f}% DB Time')
            findings.append({
                'title': '经典模式: ITL槽位不足(高并发DML小表)',
                'trigger_problem': 'TX ITL contention + Buffer Busy',
                'related_evidence': evidence,
                'root_cause': '数据块的ITL(Interested Transaction List)槽位不足，'
                    '多个并发事务无法同时在同一块上注册。常见于小表的高并发UPDATE/INSERT场景',
                'suggestion': '1. ALTER TABLE xxx INITRANS 20 MAXTRANS 255\n'
                    '2. ALTER INDEX xxx INITRANS 20\n'
                    '3. 重建表和索引使新INITRANS生效\n'
                    '4. 对于极热点小表，考虑Hash分区分散到多个块'
            })

        # =================================================================
        # Pattern 12: 连接风暴(频繁建断连接)
        # =================================================================
        conn_mgmt_pct = 0
        for k, v in time_model.items():
            if isinstance(v, dict) and 'connection management' in v.get('name', '').lower():
                conn_mgmt_pct = float(v.get('pct_db_time', 0) or 0)

        os_thread_pct = event_pct('os thread startup')
        if conn_mgmt_pct > 5 or os_thread_pct > 3:
            evidence = []
            if conn_mgmt_pct > 0:
                evidence.append(f'连接管理耗时 = {conn_mgmt_pct:.1f}% DB Time')
            if os_thread_pct > 0:
                evidence.append(f'os thread startup = {os_thread_pct:.1f}% DB Time')
            findings.append({
                'title': '经典模式: 连接风暴(频繁创建/销毁数据库连接)',
                'trigger_problem': '连接管理耗时高 + os thread startup',
                'related_evidence': evidence,
                'root_cause': '应用频繁创建和销毁数据库连接，每次连接需要OS分配线程和Oracle分配PGA等资源。'
                    '连接池配置不当或短连接应用是常见原因',
                'suggestion': '1. 使用连接池(如HikariCP/Druid/UCP)\n'
                    '2. 调整连接池min/max大小和idle超时\n'
                    '3. 增大PARALLEL_MIN_SERVERS预启动线程\n'
                    '4. 考虑使用DRCP(Database Resident Connection Pool)\n'
                    '5. 检查应用是否有连接泄漏'
            })

        # =================================================================
        # Pattern 13: Undo争用(长查询+高DML并发)
        # =================================================================
        if has('undo_space', 'undo') and (has('read by other session') or event_pct('read by other session') > 3):
            evidence = ['Undo表空间使用率高']
            rbos_pct = event_pct('read by other session')
            if rbos_pct > 0:
                evidence.append(f'read by other session = {rbos_pct:.1f}% DB Time')
            evidence.append('可能存在长查询与高DML并发的一致性读冲突')
            findings.append({
                'title': '经典模式: Undo争用(长查询与DML并发)',
                'trigger_problem': 'Undo空间高 + read by other session',
                'related_evidence': evidence,
                'root_cause': '长时间运行的查询需要读取一致性快照(CR块)，但undo信息可能被并发DML覆盖。'
                    'read by other session表示多个session争读同一块的CR版本',
                'suggestion': '1. 增大UNDO_RETENTION(至少覆盖最长查询时间)\n'
                    '2. 确保UNDO表空间自动扩展且有足够空间\n'
                    '3. 优化长查询减少执行时间\n'
                    '4. 错峰执行: 大查询避开DML高峰期'
            })

        # =================================================================
        # Pattern 14: library cache无效化(DDL频繁)
        # =================================================================
        lib_lock_pct = event_pct('library cache lock') + event_pct('library cache pin')
        if lib_lock_pct > 3:
            evidence = [f'library cache lock/pin = {lib_lock_pct:.1f}% DB Time']
            if has('硬解析', 'hard_parse'):
                evidence.append('伴随硬解析升高')
            findings.append({
                'title': '经典模式: Library Cache对象频繁无效化',
                'trigger_problem': 'library cache lock/pin等待',
                'related_evidence': evidence,
                'root_cause': 'DDL操作(如TRUNCATE TABLE, ALTER TABLE, GRANT等)导致共享池中相关SQL游标失效，'
                    '大量session排队等待重新解析。常见于在线DDL变更期间',
                'suggestion': '1. 避免高峰期执行DDL操作\n'
                    '2. 使用ONLINE选项(ALTER TABLE ... ONLINE)\n'
                    '3. 检查是否有定时任务频繁执行DDL\n'
                    '4. 检查dbms_stats的AUTO收集是否过于频繁'
            })

        # =================================================================
        # Pattern 15: 全局资源耗尽(AAS远超CPU数)
        # =================================================================
        if (has('db_time_ratio', 'db time') and
            has('os_cpu_used', 'os cpu', 'cpu使用率') and
            len(problems) > 8):
            evidence = [
                f'发现 {len(problems)} 个问题',
                'DB Time远超CPU Time (数据库过载)',
                'OS CPU使用率高',
            ]
            wait_classes = set()
            for evt in top_events[:10]:
                wclass = evt.get('wait_class', '')
                pct = float(evt.get('pct_db_time', 0) or 0)
                if pct > 3 and wclass and wclass != 'Idle':
                    wait_classes.add(wclass)
            if len(wait_classes) > 3:
                evidence.append(f"涉及 {len(wait_classes)} 个等待类别 ({', '.join(wait_classes)})")
            findings.append({
                'title': '经典模式: 数据库全局过载(多维度资源耗尽)',
                'trigger_problem': 'DB Time过高 + OS过载 + 多维度问题',
                'related_evidence': evidence,
                'root_cause': '数据库活跃会话远超CPU处理能力，多个维度同时出现瓶颈。'
                    '这通常不是单一问题导致，而是负载超出了系统容量。'
                    '需要从最大的瓶颈点开始逐个优化',
                'suggestion': '1. 优先处理占DB Time最高的等待事件\n'
                    '2. 识别并优化Top 3 SQL\n'
                    '3. 评估是否需要硬件扩容(CPU/内存/存储)\n'
                    '4. 实施Resource Manager限制低优先级负载\n'
                    '5. 考虑读写分离或负载均衡到备库'
            })

        return findings


