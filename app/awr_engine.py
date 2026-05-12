"""
Oracle AWR Report Analysis Engine
Modules: Parser -> Scorer -> Correlator -> Baseline -> LLM -> Learning
"""
import re
import json
from datetime import datetime, timedelta
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# BUILTIN RULES
# ---------------------------------------------------------------------------

BUILTIN_RULES = [
    {
        'name': 'db file sequential read 高等待',
        'category': 'wait_event',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 15, "event": "db file sequential read"}],
        'root_cause': '单块读等待过高，通常与索引扫描和随机I/O相关',
        'solution': '1. 检查Top SQL中Buffer Gets最高的SQL\n2. 检查I/O子系统性能(avg read time > 10ms需关注)\n3. 考虑将热点数据缓存到SGA\n4. 检查是否需要创建覆盖索引减少回表',
        'severity': 'high',
    },
    {
        'name': 'db file scattered read 高等待',
        'category': 'wait_event',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 15, "event": "db file scattered read"}],
        'root_cause': '多块读等待过高，通常与全表扫描相关',
        'solution': '1. 检查Top SQL中Physical Reads最高的SQL\n2. 确认是否缺少索引导致全表扫描\n3. 检查统计信息是否过期\n4. 考虑分区表或并行查询优化',
        'severity': 'high',
    },
    {
        'name': 'log file sync 高等待',
        'category': 'wait_event',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 10, "event": "log file sync"}],
        'root_cause': '日志文件同步等待过高，与提交频率和redo写入性能相关',
        'solution': '1. 检查redo log I/O性能(log file parallel write)\n2. 减少不必要的频繁COMMIT\n3. 将redo log放到高速存储\n4. 检查是否有Data Guard同步延迟',
        'severity': 'high',
    },
    {
        'name': 'TX row lock contention',
        'category': 'wait_event',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 10, "event": "enq: TX - row lock contention"}],
        'root_cause': '行锁争用严重，多个会话竞争同一行数据',
        'solution': '1. 定位持锁SQL和阻塞会话\n2. 优化事务粒度，减少长事务\n3. 检查应用逻辑是否存在热点行更新\n4. 考虑使用乐观锁机制',
        'severity': 'high',
    },
    {
        'name': 'latch/mutex 争用',
        'category': 'wait_event',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 10, "event": "latch"}],
        'root_cause': 'Latch或Mutex争用，通常与高并发和shared pool相关',
        'solution': '1. 检查是否存在大量硬解析(cursor: pin S)\n2. 使用绑定变量减少硬解析\n3. 调整cursor_sharing参数\n4. 检查shared pool是否过小',
        'severity': 'high',
    },
    {
        'name': 'CPU 使用率过高',
        'category': 'cpu',
        'conditions': [{"metric": "db_time_ratio", "op": ">", "value": 1.5}, {"metric": "cpu_pct_db_time", "op": ">", "value": 60}],
        'root_cause': 'CPU资源成为瓶颈，DB Time远超CPU Time',
        'solution': '1. 优化Top SQL减少Buffer Gets\n2. 检查是否有低效的PL/SQL循环\n3. 考虑SQL Profile或SQL Plan Baseline\n4. 评估是否需要增加CPU资源',
        'severity': 'high',
    },
    {
        'name': 'SQL 执行效率低',
        'category': 'sql_efficiency',
        'conditions': [{"metric": "buffer_gets_per_exec", "op": ">", "value": 100000}],
        'root_cause': '存在高Buffer Gets的SQL，执行计划可能不优',
        'solution': '1. 检查SQL执行计划是否走全表扫描\n2. 验证统计信息是否最新\n3. 考虑创建合适的索引\n4. 使用SQL Tuning Advisor分析',
        'severity': 'medium',
    },
    {
        'name': 'Buffer Cache 命中率低',
        'category': 'memory',
        'conditions': [{"metric": "buffer_cache_hit_ratio", "op": "<", "value": 95}],
        'root_cause': 'Buffer Cache命中率不足，大量物理读取',
        'solution': '1. 考虑增大db_cache_size\n2. 检查是否有大量全表扫描\n3. 使用KEEP/RECYCLE缓冲池隔离热点对象\n4. 检查是否有不合理的direct path read',
        'severity': 'medium',
    },
    {
        'name': 'I/O 延迟过高',
        'category': 'io',
        'conditions': [{"metric": "avg_read_time", "op": ">", "value": 10}],
        'root_cause': '磁盘I/O响应时间过长',
        'solution': '1. 检查存储阵列性能和队列深度\n2. 确认是否存在I/O热点文件\n3. 考虑将数据文件分散到多个磁盘组\n4. 评估SSD存储升级方案',
        'severity': 'high',
    },
    {
        'name': 'DB Time 远超 CPU Time',
        'category': 'load',
        'conditions': [{"metric": "db_time_ratio", "op": ">", "value": 3.0}],
        'root_cause': 'DB Time是CPU Time的3倍以上，大量时间花在等待',
        'solution': '1. 分析Top Wait Events定位等待瓶颈\n2. 检查I/O等待和锁等待\n3. 分析AAS(Average Active Sessions)趋势\n4. 确认是否存在资源瓶颈',
        'severity': 'high',
    },
    {
        'name': '硬解析比例过高',
        'category': 'parse',
        'conditions': [{"metric": "hard_parse_pct", "op": ">", "value": 10}],
        'root_cause': '硬解析占比过高，消耗大量CPU和shared pool资源',
        'solution': '1. 推动应用使用绑定变量\n2. 设置cursor_sharing=FORCE(临时方案)\n3. 增大shared_pool_size\n4. 检查是否有动态SQL拼接导致的硬解析',
        'severity': 'medium',
    },
    {
        'name': 'GC 等待(RAC)',
        'category': 'rac',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 10, "event": "gc cr block receive time"}],
        'root_cause': 'RAC节点间Global Cache传输延迟过高',
        'solution': '1. 检查RAC互联网络带宽和延迟\n2. 识别热点对象并做实例隔离\n3. 使用服务(Service)将相关SQL路由到同一节点\n4. 检查是否有跨节点锁争用',
        'severity': 'high',
    },
    {
        'name': 'Library Cache 命中率低',
        'category': 'memory',
        'conditions': [{"metric": "library_cache_hit_ratio", "op": "<", "value": 95}],
        'root_cause': 'Library Cache命中率不足，SQL游标频繁失效或被换出',
        'solution': '1. 增大shared_pool_size\n2. 使用绑定变量减少游标数量\n3. Pin住关键的PL/SQL对象\n4. 检查是否有DDL操作导致游标失效',
        'severity': 'medium',
    },
    {
        'name': 'Redo 生成量过大',
        'category': 'redo',
        'conditions': [{"metric": "redo_size_per_sec", "op": ">", "value": 50000000}],
        'root_cause': 'Redo日志生成速度过快，可能影响日志切换和备份',
        'solution': '1. 检查是否有大批量DML操作未分批提交\n2. 评估是否可以使用NOLOGGING操作\n3. 增大redo log文件大小减少日志切换\n4. 确认归档传输带宽是否充足',
        'severity': 'medium',
    },
    {
        'name': '热点段争用',
        'category': 'segment',
        'conditions': [{"metric": "segment_buffer_busy_waits", "op": ">", "value": 1000}],
        'root_cause': '特定段(表/索引)存在热点争用',
        'solution': '1. 对热点表使用ASSM表空间自动段管理\n2. 增加FREELISTS/FREELIST GROUPS\n3. 考虑反转索引或Hash分区减少右侧插入争用\n4. 检查是否需要增大PCTFREE',
        'severity': 'medium',
    },
]


# ---------------------------------------------------------------------------
# AWR PARSER
# ---------------------------------------------------------------------------

class AWRParser:
    """Parse Oracle AWR HTML reports and extract structured metrics."""

    def parse(self, html_content: str) -> dict:
        """Parse AWR HTML and return structured data dict with keys:
        db_info, snap_info, load_profile, top_events, top_sql,
        io_stats, memory_stats, instance_efficiency, os_stats,
        rac_stats, redo_stats, parse_stats, segment_stats"""
        try:
            soup = BeautifulSoup(html_content, 'lxml')
        except Exception:
            soup = BeautifulSoup(html_content, 'html.parser')
        result = {
            'db_info': self._extract_db_info(soup),
            'snap_info': self._extract_snap_info(soup),
            'load_profile': self._extract_load_profile(soup),
            'top_events': self._extract_top_events(soup),
            'top_sql': self._extract_top_sql(soup),
            'io_stats': self._extract_io_stats(soup),
            'memory_stats': self._extract_memory_stats(soup),
            'instance_efficiency': self._extract_instance_efficiency(soup),
            'os_stats': self._extract_os_stats(soup),
            'rac_stats': self._extract_rac_stats(soup),
            'redo_stats': self._extract_redo_stats(soup),
            'parse_stats': self._extract_parse_stats(soup),
            'segment_stats': self._extract_segment_stats(soup),
        }
        return result

    def _find_table_after(self, soup, pattern):
        """Find the first table element following a header matching pattern."""
        try:
            for tag in soup.find_all(['h2', 'h3', 'h4', 'th', 'td', 'b', 'a', 'span', 'p']):
                text = tag.get_text(strip=True)
                if text and re.search(pattern, text, re.IGNORECASE):
                    # Look for next table sibling or in parent
                    table = tag.find_next('table')
                    if table:
                        return table
            return None
        except Exception:
            return None

    def _parse_table(self, table):
        """Parse an HTML table into list of dicts."""
        if table is None:
            return []
        try:
            rows = table.find_all('tr')
            if not rows:
                return []
            # First row provides headers
            header_row = rows[0]
            headers = [cell.get_text(strip=True) for cell in header_row.find_all(['th', 'td'])]
            if not headers:
                return []
            result = []
            for row in rows[1:]:
                cells = row.find_all(['th', 'td'])
                values = [cell.get_text(strip=True) for cell in cells]
                if not values:
                    continue
                row_dict = {}
                for i, header in enumerate(headers):
                    if i < len(values):
                        row_dict[header] = values[i]
                    else:
                        row_dict[header] = ''
                result.append(row_dict)
            return result
        except Exception:
            return []

    def _extract_db_info(self, soup) -> dict:
        result = {'db_name': '', 'instance_name': '', 'db_version': '', 'host_name': '', 'platform': ''}
        try:
            # Try regex on full text
            text = soup.get_text()
            patterns = {
                'db_name': r'DB\s*Name[:\s]*(\S+)',
                'instance_name': r'Instance\s*Name[:\s]*(\S+)',
                'db_version': r'(?:DB\s*)?Version[:\s]*([\d\.]+)',
                'host_name': r'Host\s*Name[:\s]*(\S+)',
                'platform': r'Platform[:\s]*(.+?)(?:\n|$)',
            }
            for key, pat in patterns.items():
                m = re.search(pat, text, re.IGNORECASE)
                if m:
                    result[key] = m.group(1).strip()
            # Try table-based extraction
            table = self._find_table_after(soup, r'Database Instance Information|DB\s*Name')
            if table:
                rows = self._parse_table(table)
                for row in rows:
                    for k, v in row.items():
                        kl = k.lower()
                        if 'db name' in kl and v and not result['db_name']:
                            result['db_name'] = v
                        elif 'instance' in kl and 'name' in kl and v and not result['instance_name']:
                            result['instance_name'] = v
                        elif 'version' in kl and v and not result['db_version']:
                            result['db_version'] = v
                        elif 'host' in kl and v and not result['host_name']:
                            result['host_name'] = v
                        elif 'platform' in kl and v and not result['platform']:
                            result['platform'] = v
                # Also check if headers themselves are the values (AWR format)
                if rows and not result['db_name']:
                    for row in rows:
                        vals = list(row.values())
                        keys = list(row.keys())
                        for i, k in enumerate(keys):
                            kl = k.lower()
                            if 'db name' in kl and i < len(vals):
                                result['db_name'] = vals[i] if vals[i] else result['db_name']
        except Exception:
            pass
        return result

    def _extract_snap_info(self, soup) -> dict:
        result = {'begin_id': '', 'end_id': '', 'snap_begin': '', 'snap_end': '',
                  'duration': '', 'elapsed_seconds': 0}
        try:
            text = soup.get_text()
            # Try regex patterns
            m = re.search(r'Begin\s+Snap[:\s]*(\d+)', text, re.IGNORECASE)
            if m:
                result['begin_id'] = m.group(1)
            m = re.search(r'End\s+Snap[:\s]*(\d+)', text, re.IGNORECASE)
            if m:
                result['end_id'] = m.group(1)
            # Time patterns
            m = re.search(r'Begin\s+Snap\s+Time[:\s]*([\d\-\/\s:]+)', text, re.IGNORECASE)
            if m:
                result['snap_begin'] = m.group(1).strip()
            m = re.search(r'End\s+Snap\s+Time[:\s]*([\d\-\/\s:]+)', text, re.IGNORECASE)
            if m:
                result['snap_end'] = m.group(1).strip()
            m = re.search(r'Elapsed[:\s]*([\d\.]+)\s*\(?(min|sec|hrs)?', text, re.IGNORECASE)
            if m:
                result['duration'] = m.group(0).strip()
                val = self._safe_float(m.group(1))
                unit = m.group(2) if m.group(2) else ''
                if 'min' in unit.lower():
                    result['elapsed_seconds'] = val * 60
                elif 'hrs' in unit.lower() or 'hour' in unit.lower():
                    result['elapsed_seconds'] = val * 3600
                else:
                    result['elapsed_seconds'] = val
            # Try table-based extraction
            table = self._find_table_after(soup, r'Snap\s*Id|Snapshot')
            if table:
                rows = self._parse_table(table)
                for row in rows:
                    for k, v in row.items():
                        kl = k.lower()
                        if 'begin' in kl and 'snap' in kl and v and not result['begin_id']:
                            # could be snap id
                            num = re.search(r'(\d+)', v)
                            if num:
                                result['begin_id'] = num.group(1)
                        elif 'end' in kl and 'snap' in kl and v and not result['end_id']:
                            num = re.search(r'(\d+)', v)
                            if num:
                                result['end_id'] = num.group(1)
                        elif 'elapsed' in kl and v:
                            result['duration'] = v
                            # Try to parse elapsed time in format HH:MM:SS or minutes
                            time_match = re.search(r'(\d+):(\d+):(\d+)', v)
                            if time_match:
                                h, m_val, s = int(time_match.group(1)), int(time_match.group(2)), int(time_match.group(3))
                                result['elapsed_seconds'] = h * 3600 + m_val * 60 + s
                            else:
                                result['elapsed_seconds'] = self._safe_float(v)
            # Also look for snap IDs in a different format
            if not result['begin_id']:
                snap_ids = re.findall(r'Snap\s*Id\s*[\s:]*(\d+)', text, re.IGNORECASE)
                if len(snap_ids) >= 2:
                    result['begin_id'] = snap_ids[0]
                    result['end_id'] = snap_ids[1]
                elif len(snap_ids) == 1:
                    result['begin_id'] = snap_ids[0]
        except Exception:
            pass
        return result

    def _extract_load_profile(self, soup) -> list:
        try:
            table = self._find_table_after(soup, r'Load Profile')
            rows = self._parse_table(table)
            computed = {}
            # Map common load profile metric names to keys
            metric_map = {
                'db time': 'db_time',
                'db cpu': 'db_cpu',
                'redo size': 'redo_size',
                'logical reads': 'logical_reads',
                'physical reads': 'physical_reads',
                'hard parses': 'hard_parses',
                'parses': 'parses',
                'executes': 'executes',
                'transactions': 'transactions',
            }
            for row in rows:
                # The first column is usually the metric name, second is "Per Second"
                row_keys = list(row.keys())
                row_vals = list(row.values())
                if len(row_keys) < 2:
                    continue
                metric_name = row_vals[0] if row_vals[0] else row_keys[0]
                # Per Second value is typically the second column
                per_sec_val = row_vals[1] if len(row_vals) > 1 else ''
                # Also check: sometimes metric name IS the first key
                name_lower = metric_name.lower().strip()
                # Check for "Per Second" column header
                per_sec_col = None
                for k in row_keys:
                    if 'per sec' in k.lower() or 'per second' in k.lower():
                        per_sec_col = k
                        break
                if per_sec_col:
                    per_sec_val = row.get(per_sec_col, '')
                for pattern, key in metric_map.items():
                    if pattern in name_lower:
                        computed[key] = self._safe_float(per_sec_val)
                        break
            return {'raw': rows, 'computed': computed}
        except Exception:
            return {'raw': [], 'computed': {}}

    def _extract_top_events(self, soup) -> list:
        """Extract Top Timed Events with %DB Time, Avg Wait, Wait Class."""
        try:
            table = self._find_table_after(soup, r'Top\s+(?:5|10)\s+(?:Timed|Foreground)\s+Events|Top\s+Timed\s+Events')
            rows = self._parse_table(table)
            events = []
            for row in rows:
                event = {'event': '', 'waits': 0, 'time': 0, 'avg_wait': 0,
                         'pct_db_time': 0, 'wait_class': ''}
                for k, v in row.items():
                    kl = k.lower()
                    if 'event' in kl or 'name' in kl:
                        event['event'] = v
                    elif 'waits' in kl or 'total wait' in kl:
                        event['waits'] = self._safe_float(v)
                    elif 'time' in kl and 'db' not in kl and 'avg' not in kl and '%' not in kl:
                        event['time'] = self._safe_float(v)
                    elif 'avg' in kl and 'wait' in kl:
                        event['avg_wait'] = self._safe_float(v)
                    elif '%' in kl or 'db time' in kl or 'pct' in kl:
                        event['pct_db_time'] = self._safe_float(v)
                    elif 'class' in kl:
                        event['wait_class'] = v
                if event['event']:
                    events.append(event)
            return events
        except Exception:
            return []

    def _extract_top_sql(self, soup) -> dict:
        """Extract SQL ordered by Elapsed/CPU/Gets/Reads/Executions."""
        result = {}
        sections = [
            ('SQL ordered by Elapsed Time', r'SQL\s+ordered\s+by\s+Elapsed\s+Time'),
            ('SQL ordered by CPU Time', r'SQL\s+ordered\s+by\s+CPU\s+Time'),
            ('SQL ordered by Gets', r'SQL\s+ordered\s+by\s+Gets'),
            ('SQL ordered by Reads', r'SQL\s+ordered\s+by\s+Reads'),
            ('SQL ordered by Executions', r'SQL\s+ordered\s+by\s+Executions'),
        ]
        try:
            for name, pattern in sections:
                table = self._find_table_after(soup, pattern)
                rows = self._parse_table(table)
                result[name] = rows[:15]
        except Exception:
            pass
        return result

    def _extract_io_stats(self, soup) -> list:
        try:
            table = self._find_table_after(soup, r'IOStat|I/O\s*Stat|Tablespace\s+IO\s+Stats')
            return self._parse_table(table)
        except Exception:
            return []

    def _extract_memory_stats(self, soup) -> dict:
        result = {}
        try:
            sga_table = self._find_table_after(soup, r'SGA')
            if sga_table:
                result['SGA'] = self._parse_table(sga_table)
            pga_table = self._find_table_after(soup, r'PGA')
            if pga_table:
                result['PGA'] = self._parse_table(pga_table)
            bp_table = self._find_table_after(soup, r'Buffer\s+Pool\s+Statistics|Buffer\s+Pool\s+Advisory')
            if bp_table:
                result['Buffer Pool'] = self._parse_table(bp_table)
        except Exception:
            pass
        return result

    def _extract_instance_efficiency(self, soup) -> list:
        try:
            table = self._find_table_after(soup, r'Instance\s+Efficiency\s+Percentages|Instance\s+Efficiency')
            rows = self._parse_table(table)
            if rows:
                return rows
            # If standard table parse didn't work, try extracting from text
            if table:
                result = []
                text = table.get_text()
                patterns = [
                    (r'Buffer\s+(?:Nowait|Hit)\s+%[:\s]*([\d\.]+)', 'Buffer Hit %'),
                    (r'Library\s+Hit\s+%[:\s]*([\d\.]+)', 'Library Hit %'),
                    (r'In-memory\s+Sort\s+%[:\s]*([\d\.]+)', 'In-memory Sort %'),
                    (r'Soft\s+Parse\s+%[:\s]*([\d\.]+)', 'Soft Parse %'),
                    (r'Execute\s+to\s+Parse\s+%[:\s]*([\d\.]+)', 'Execute to Parse %'),
                    (r'Latch\s+Hit\s+%[:\s]*([\d\.]+)', 'Latch Hit %'),
                    (r'Parse\s+CPU\s+to\s+Parse\s+Elapsed\s+%[:\s]*([\d\.]+)', 'Parse CPU to Parse Elapsed %'),
                    (r'Non-Parse\s+CPU\s+%[:\s]*([\d\.]+)', 'Non-Parse CPU %'),
                ]
                for pat, name in patterns:
                    m = re.search(pat, text, re.IGNORECASE)
                    if m:
                        result.append({'metric': name, 'value': self._safe_float(m.group(1))})
                return result
            return []
        except Exception:
            return []

    def _extract_os_stats(self, soup) -> list:
        try:
            table = self._find_table_after(soup, r'Operating\s+System\s+Statistics|OS\s+Statistics')
            return self._parse_table(table)
        except Exception:
            return []

    def _extract_rac_stats(self, soup) -> list:
        try:
            table = self._find_table_after(soup, r'RAC\s+Statistics|Global\s+Cache')
            return self._parse_table(table)
        except Exception:
            return []

    def _extract_redo_stats(self, soup) -> dict:
        """Extract Redo size, log file sync, log file parallel write stats."""
        result = {'redo_size_per_sec': 0, 'log_switches': 0}
        try:
            # Try to get from load profile
            lp_table = self._find_table_after(soup, r'Load Profile')
            lp_rows = self._parse_table(lp_table)
            for row in lp_rows:
                row_vals = list(row.values())
                if not row_vals:
                    continue
                name = row_vals[0].lower() if row_vals[0] else ''
                if 'redo size' in name:
                    # Per Second is usually second column
                    per_sec_val = row_vals[1] if len(row_vals) > 1 else '0'
                    # Check for "Per Second" header
                    for k, v in row.items():
                        if 'per sec' in k.lower():
                            per_sec_val = v
                            break
                    result['redo_size_per_sec'] = self._safe_float(per_sec_val)
                    break
            # Try to find log switches
            text = soup.get_text()
            m = re.search(r'Log\s+switches\s*[:\(]?\s*(\d+)', text, re.IGNORECASE)
            if m:
                result['log_switches'] = int(m.group(1))
            # Also look for redo-related tables
            redo_table = self._find_table_after(soup, r'Redo')
            if redo_table:
                redo_rows = self._parse_table(redo_table)
                if redo_rows:
                    result['redo_table'] = redo_rows
        except Exception:
            pass
        return result

    def _extract_parse_stats(self, soup) -> dict:
        """Extract Hard Parse %, Parse Calls, Execute to Parse ratio."""
        result = {'total_parses_per_sec': 0, 'hard_parses_per_sec': 0,
                  'hard_parse_pct': 0, 'execute_to_parse_pct': 0}
        try:
            # Get from load profile
            lp_table = self._find_table_after(soup, r'Load Profile')
            lp_rows = self._parse_table(lp_table)
            for row in lp_rows:
                row_vals = list(row.values())
                if not row_vals:
                    continue
                name = row_vals[0].lower() if row_vals[0] else ''
                per_sec_val = row_vals[1] if len(row_vals) > 1 else '0'
                for k, v in row.items():
                    if 'per sec' in k.lower():
                        per_sec_val = v
                        break
                if 'hard parse' in name:
                    result['hard_parses_per_sec'] = self._safe_float(per_sec_val)
                elif 'parses' in name and 'hard' not in name:
                    result['total_parses_per_sec'] = self._safe_float(per_sec_val)
            # Calculate hard parse percentage
            if result['total_parses_per_sec'] > 0:
                result['hard_parse_pct'] = (result['hard_parses_per_sec'] / result['total_parses_per_sec']) * 100
            # Check instance efficiency for execute to parse
            ie_table = self._find_table_after(soup, r'Instance\s+Efficiency')
            if ie_table:
                text = ie_table.get_text()
                m = re.search(r'Execute\s+to\s+Parse\s+%[:\s]*([\d\.]+)', text, re.IGNORECASE)
                if m:
                    result['execute_to_parse_pct'] = self._safe_float(m.group(1))
                # Also check Parse CPU to Parse Elapsed
                m = re.search(r'Parse\s+CPU\s+to\s+Parse\s+Elapsed\s+%[:\s]*([\d\.]+)', text, re.IGNORECASE)
                if m:
                    result['parse_cpu_to_elapsed_pct'] = self._safe_float(m.group(1))
        except Exception:
            pass
        return result

    def _extract_segment_stats(self, soup) -> list:
        """Extract hot segments (tables, indexes)."""
        result = []
        try:
            patterns = [
                r'Segments\s+by\s+Logical\s+Reads',
                r'Segments\s+by\s+Physical\s+Reads',
                r'Segments\s+by\s+Buffer\s+Busy\s+Waits',
            ]
            for pattern in patterns:
                table = self._find_table_after(soup, pattern)
                rows = self._parse_table(table)
                for row in rows:
                    row['_source'] = pattern.replace(r'\s+', ' ').replace('\\s+', ' ')
                    result.append(row)
        except Exception:
            pass
        return result

    def _safe_float(self, val, default=0.0) -> float:
        """Safely convert a string to float."""
        try:
            if val is None:
                return default
            s = str(val).strip()
            if not s:
                return default
            s = s.replace(',', '').replace('%', '').replace(' ', '')
            multiplier = 1
            if s.upper().endswith('G'):
                multiplier = 1e9
                s = s[:-1]
            elif s.upper().endswith('M'):
                multiplier = 1e6
                s = s[:-1]
            elif s.upper().endswith('K'):
                multiplier = 1000
                s = s[:-1]
            return float(s) * multiplier
        except (ValueError, TypeError):
            return default


# ---------------------------------------------------------------------------
# METRIC SCORER
# ---------------------------------------------------------------------------

class MetricScorer:
    """Score AWR metrics against configurable thresholds."""

    # Default thresholds: {metric_key: (warning_threshold, serious_threshold, unit, direction)}
    # direction: 'higher_worse' means higher value = worse, 'lower_worse' means lower = worse
    DEFAULT_THRESHOLDS = {
        'aas_per_cpu': (0.7, 1.0, 'ratio', 'higher_worse'),
        'top_event_pct_db_time': (15.0, 30.0, '%DB Time', 'higher_worse'),
        'db_file_sequential_read_avg_wait': (10.0, 20.0, 'ms', 'higher_worse'),
        'db_file_scattered_read_avg_wait': (10.0, 20.0, 'ms', 'higher_worse'),
        'log_file_sync_avg_wait': (5.0, 15.0, 'ms', 'higher_worse'),
        'hard_parse_pct': (10.0, 30.0, '%', 'higher_worse'),
        'buffer_gets_per_exec': (10000, 100000, 'gets', 'higher_worse'),
        'disk_reads_per_exec': (100, 1000, 'reads', 'higher_worse'),
        'buffer_cache_hit_ratio': (95.0, 90.0, '%', 'lower_worse'),
        'library_cache_hit_ratio': (99.0, 95.0, '%', 'lower_worse'),
        'db_time_ratio': (1.0, 3.0, 'ratio', 'higher_worse'),
        'avg_read_time': (10.0, 20.0, 'ms', 'higher_worse'),
        'redo_size_per_sec': (50_000_000, 200_000_000, 'bytes', 'higher_worse'),
        'gc_cr_block_receive_time': (1.0, 3.0, 'ms', 'higher_worse'),
    }

    def __init__(self, custom_thresholds=None):
        self.thresholds = dict(self.DEFAULT_THRESHOLDS)
        if custom_thresholds:
            self.thresholds.update(custom_thresholds)

    def score_metric(self, metric_key: str, value: float) -> dict:
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

    def _safe_float(self, val, default=0.0):
        """Safely convert a value to float."""
        try:
            if val is None:
                return default
            return float(val)
        except (ValueError, TypeError):
            return default

    def _get_problem_type(self, metric_key):
        """Map metric key to problem type category."""
        if metric_key in ('db_file_sequential_read_avg_wait', 'db_file_scattered_read_avg_wait', 'avg_read_time'):
            return 'io'
        elif metric_key in ('log_file_sync_avg_wait', 'top_event_pct_db_time'):
            return 'wait_event'
        elif metric_key in ('buffer_gets_per_exec', 'disk_reads_per_exec'):
            return 'sql'
        elif metric_key in ('buffer_cache_hit_ratio', 'library_cache_hit_ratio'):
            return 'memory'
        elif metric_key in ('hard_parse_pct',):
            return 'parse'
        elif metric_key in ('redo_size_per_sec',):
            return 'redo'
        elif metric_key in ('gc_cr_block_receive_time',):
            return 'rac'
        elif metric_key in ('db_time_ratio', 'aas_per_cpu'):
            return 'load'
        return 'other'

    def _get_problem_title(self, metric_key, value, unit):
        """Generate Chinese title for a problem."""
        titles = {
            'aas_per_cpu': f'平均活跃会话/CPU比率过高 ({value}{unit})',
            'top_event_pct_db_time': f'Top等待事件占比过高 ({value}{unit})',
            'db_file_sequential_read_avg_wait': f'db file sequential read 平均等待过高 ({value}{unit})',
            'db_file_scattered_read_avg_wait': f'db file scattered read 平均等待过高 ({value}{unit})',
            'log_file_sync_avg_wait': f'log file sync 平均等待过高 ({value}{unit})',
            'hard_parse_pct': f'硬解析比例过高 ({value}{unit})',
            'buffer_gets_per_exec': f'SQL逻辑读过高 ({value}{unit})',
            'disk_reads_per_exec': f'SQL物理读过高 ({value}{unit})',
            'buffer_cache_hit_ratio': f'Buffer Cache 命中率过低 ({value}{unit})',
            'library_cache_hit_ratio': f'Library Cache 命中率过低 ({value}{unit})',
            'db_time_ratio': f'DB Time远超CPU Time ({value}{unit})',
            'avg_read_time': f'I/O平均读取延迟过高 ({value}{unit})',
            'redo_size_per_sec': f'Redo生成量过大 ({value}{unit})',
            'gc_cr_block_receive_time': f'RAC GC等待过高 ({value}{unit})',
        }
        return titles.get(metric_key, f'{metric_key} 异常 ({value}{unit})')

    def score_all(self, parsed_data: dict, report=None) -> list:
        """Score all extracted metrics. Returns list of problem dicts."""
        if not parsed_data:
            return []

        problems = []
        scored_metrics = {}  # metric_key -> value

        # 1. load_profile computed values
        try:
            load_profile = parsed_data.get('load_profile')
            if load_profile and isinstance(load_profile, dict):
                computed = load_profile.get('computed', {})
                if computed:
                    db_time = self._safe_float(computed.get('db_time'))
                    db_cpu = self._safe_float(computed.get('db_cpu'))
                    if db_cpu > 0:
                        db_time_ratio = db_time / db_cpu
                        scored_metrics['db_time_ratio'] = db_time_ratio

                    hard_parses = self._safe_float(computed.get('hard_parses'))
                    parses = self._safe_float(computed.get('parses'))
                    if parses > 0:
                        hard_parse_pct = hard_parses / parses * 100
                        scored_metrics['hard_parse_pct'] = hard_parse_pct

                    redo_size = computed.get('redo_size')
                    if redo_size is not None:
                        scored_metrics['redo_size_per_sec'] = self._safe_float(redo_size)
        except Exception:
            pass

        # 2. top_events
        try:
            top_events = parsed_data.get('top_events', [])
            if top_events and isinstance(top_events, list):
                # Score top 1 event pct_db_time
                if len(top_events) > 0:
                    first_event = top_events[0]
                    pct_val = self._safe_float(first_event.get('pct_db_time'))
                    if pct_val > 0:
                        scored_metrics['top_event_pct_db_time'] = pct_val

                # Score specific events by avg_wait
                for event in top_events:
                    event_name = (event.get('name') or event.get('event') or '').strip().lower()
                    avg_wait = self._safe_float(event.get('avg_wait'))
                    if event_name == 'db file sequential read' and avg_wait > 0:
                        scored_metrics['db_file_sequential_read_avg_wait'] = avg_wait
                    elif event_name == 'db file scattered read' and avg_wait > 0:
                        scored_metrics['db_file_scattered_read_avg_wait'] = avg_wait
                    elif event_name == 'log file sync' and avg_wait > 0:
                        scored_metrics['log_file_sync_avg_wait'] = avg_wait
        except Exception:
            pass

        # 3. top_sql
        try:
            top_sql = parsed_data.get('top_sql', {})
            if top_sql and isinstance(top_sql, dict):
                # SQL ordered by Gets
                sql_by_gets = top_sql.get('SQL ordered by Gets') or top_sql.get('sql_by_gets') or []
                if sql_by_gets and len(sql_by_gets) > 0:
                    top_entry = sql_by_gets[0]
                    gets_per_exec = self._safe_float(
                        top_entry.get('gets_per_exec') or top_entry.get('gets/exec')
                    )
                    if gets_per_exec > 0:
                        scored_metrics['buffer_gets_per_exec'] = gets_per_exec

                # SQL ordered by Reads
                sql_by_reads = top_sql.get('SQL ordered by Reads') or top_sql.get('sql_by_reads') or []
                if sql_by_reads and len(sql_by_reads) > 0:
                    top_entry = sql_by_reads[0]
                    reads_per_exec = self._safe_float(
                        top_entry.get('reads_per_exec') or top_entry.get('reads/exec')
                    )
                    if reads_per_exec > 0:
                        scored_metrics['disk_reads_per_exec'] = reads_per_exec
        except Exception:
            pass

        # 4. instance_efficiency
        try:
            instance_eff = parsed_data.get('instance_efficiency', [])
            if instance_eff:
                if isinstance(instance_eff, list):
                    for item in instance_eff:
                        name = (item.get('name') or item.get('stat_name') or '').strip()
                        val = self._safe_float(item.get('value') or item.get('pct'))
                        if 'Buffer Hit' in name or 'Buffer Cache Hit' in name:
                            scored_metrics['buffer_cache_hit_ratio'] = val
                        elif 'Library Hit' in name or 'Library Cache Hit' in name:
                            scored_metrics['library_cache_hit_ratio'] = val
                elif isinstance(instance_eff, dict):
                    for name, val in instance_eff.items():
                        fval = self._safe_float(val)
                        if 'Buffer Hit' in name or 'Buffer Cache Hit' in name:
                            scored_metrics['buffer_cache_hit_ratio'] = fval
                        elif 'Library Hit' in name or 'Library Cache Hit' in name:
                            scored_metrics['library_cache_hit_ratio'] = fval
        except Exception:
            pass

        # 5. rac_stats
        try:
            rac_stats = parsed_data.get('rac_stats', [])
            if rac_stats and isinstance(rac_stats, list):
                for stat in rac_stats:
                    name = (stat.get('name') or stat.get('stat_name') or '').strip().lower()
                    if 'gc cr block receive time' in name:
                        val = self._safe_float(stat.get('value') or stat.get('avg_wait'))
                        if val > 0:
                            scored_metrics['gc_cr_block_receive_time'] = val
        except Exception:
            pass

        # 6. AAS/CPU
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
            pass

        # Now score all collected metrics and build problem list
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
                pass

        return problems


# ---------------------------------------------------------------------------
# CORRELATION ANALYZER
# ---------------------------------------------------------------------------

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

    def analyze(self, parsed_data: dict, problems: list) -> list:
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
        return findings

    def _check_io_sql_correlation(self, parsed_data: dict, problems: list) -> list:
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

    def _check_cpu_sql_correlation(self, parsed_data: dict, problems: list) -> list:
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

    def _check_redo_commit_correlation(self, parsed_data: dict, problems: list) -> list:
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

    def _check_parse_correlation(self, parsed_data: dict, problems: list) -> list:
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

    def _check_rac_correlation(self, parsed_data: dict, problems: list) -> list:
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

    def _check_memory_correlation(self, parsed_data: dict, problems: list) -> list:
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


# ---------------------------------------------------------------------------
# BASELINE COMPARER
# ---------------------------------------------------------------------------

class BaselineComparer:
    """Compare current metrics against historical baselines."""

    def compare(self, report, parsed_data: dict, db_session) -> list:
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

    def update_baseline(self, report, parsed_data: dict, db_session):
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

    def _calculate_deviation(self, current: float, avg: float, max_val: float) -> dict:
        """Calculate how much current deviates from baseline."""
        if not avg or avg == 0:
            return {'deviation_pct': 0, 'is_anomaly': False}
        deviation_pct = (current - avg) / avg * 100
        is_anomaly = deviation_pct > 50 or (max_val and current > max_val * 1.2)
        return {'deviation_pct': round(deviation_pct, 1), 'is_anomaly': bool(is_anomaly)}

    def _extract_key_metrics(self, parsed_data: dict) -> dict:
        """Extract key metrics from parsed data for baseline comparison."""
        metrics = {}
        try:
            load_profile = parsed_data.get('load_profile', {})
            if isinstance(load_profile, dict):
                computed = load_profile.get('computed', {})
                if computed.get('db_time') and computed.get('db_cpu'):
                    db_cpu = computed['db_cpu']
                    if db_cpu > 0:
                        metrics['db_time_ratio'] = round(computed['db_time'] / db_cpu, 2)
            parse_stats = parsed_data.get('parse_stats', {}) or {}
            if parse_stats.get('hard_parse_pct'):
                metrics['hard_parse_pct'] = parse_stats['hard_parse_pct']
            top_events = parsed_data.get('top_events', []) or []
            for event in top_events[:5]:
                pct = event.get('pct_db_time', 0)
                avg_wait = event.get('avg_wait', 0)
                ename = event.get('event', '')
                if ename and pct:
                    safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', ename.lower()).strip('_')
                    metrics[f'{safe_name}_pct_db_time'] = float(pct)
                    if avg_wait:
                        metrics[f'{safe_name}_avg_wait'] = float(avg_wait)
        except Exception:
            pass
        return metrics


# ---------------------------------------------------------------------------
# LLM INTEGRATION
# ---------------------------------------------------------------------------

class LLMIntegration:
    """Interface for LLM-enhanced analysis with structured output."""

    def __init__(self, provider='none', api_key='', api_url='', model=''):
        self.provider = provider
        self.api_key = api_key
        self.api_url = api_url
        self.model = model

    def enhance_analysis(self, parsed_data: dict, problems: list, correlations: list) -> dict:
        """Send structured data to LLM for deep analysis.
        Returns dict with: summary, problems, learned_patterns, raw_response"""
        if self.provider == 'none' or not self.api_key:
            return None
        try:
            prompt = self._build_prompt(parsed_data, problems, correlations)
            response_text = self._call_api(prompt)
            result = self._parse_llm_response(response_text)
            result['raw_response'] = response_text
            return result
        except Exception as e:
            return {'error': str(e), 'summary': '', 'problems': [], 'learned_patterns': []}

    def _build_prompt(self, parsed_data: dict, problems: list, correlations: list) -> str:
        """Build structured prompt for LLM."""
        db_info = parsed_data.get('db_info', {}) or {}
        snap_info = parsed_data.get('snap_info', {}) or {}
        load_profile = parsed_data.get('load_profile', {})
        if isinstance(load_profile, dict):
            computed = load_profile.get('computed', {})
        else:
            computed = {}

        prompt_parts = []
        prompt_parts.append("\u4f60\u662f\u4e00\u4e2aOracle DBA\u4e13\u5bb6\uff0c\u8bf7\u5206\u6790\u4ee5\u4e0bAWR\u62a5\u544a\u6570\u636e\u5e76\u7ed9\u51fa\u8bca\u65ad\u5efa\u8bae\u3002")
        prompt_parts.append("")
        prompt_parts.append(f"\u6570\u636e\u5e93\u4fe1\u606f: DB Name={db_info.get('db_name', 'N/A')}, "
                           f"Instance={db_info.get('instance_name', 'N/A')}, "
                           f"Version={db_info.get('db_version', 'N/A')}, "
                           f"Host={db_info.get('host_name', 'N/A')}")
        prompt_parts.append(f"\u5feb\u7167\u4fe1\u606f: Begin={snap_info.get('begin_id', 'N/A')}, "
                           f"End={snap_info.get('end_id', 'N/A')}, "
                           f"Duration={snap_info.get('duration', 'N/A')}")
        prompt_parts.append("")
        prompt_parts.append("\u5173\u952e\u8d1f\u8f7d\u6307\u6807:")
        for k, v in computed.items():
            prompt_parts.append(f"  - {k}: {v}")
        prompt_parts.append("")
        prompt_parts.append("\u53d1\u73b0\u7684\u95ee\u9898:")
        for i, p in enumerate(problems[:10], 1):
            prompt_parts.append(f"  {i}. [{p.get('level', 'warning')}] {p.get('title', 'N/A')} - {p.get('evidence', '')}")
        prompt_parts.append("")
        prompt_parts.append("\u5173\u8054\u5206\u6790:")
        for i, c in enumerate(correlations[:5], 1):
            prompt_parts.append(f"  {i}. {c.get('title', 'N/A')}: {c.get('root_cause', '')}")
        prompt_parts.append("")
        prompt_parts.append("\u8bf7\u4ee5\u4e0b\u9762\u7684JSON\u683c\u5f0f\u8f93\u51fa\u5206\u6790\u7ed3\u679c\uff0c\u4e0d\u8981\u5305\u542b\u4efb\u4f55markdown\u6807\u8bb0:")
        prompt_parts.append('{"summary": "\u603b\u4f53\u5206\u6790\u6458\u8981", "problems": [{"title": "", "severity": "", "root_cause": "", "evidence": [], "suggestion": []}], "learned_patterns": [{"pattern_name": "", "conditions": [{"metric": "", "op": "", "value": 0}], "solution": ""}]}')
        prompt_parts.append("")
        prompt_parts.append("\u6ce8\u610f: \u53ea\u8f93\u51fa\u5408\u6cd5\u7684JSON\uff0c\u4e0d\u8981\u7528```\u5305\u88f9\u3002")
        return "\n".join(prompt_parts)

    def _parse_llm_response(self, response_text: str) -> dict:
        """Parse LLM response, trying to extract JSON."""
        if not response_text:
            return {'summary': '', 'problems': [], 'learned_patterns': []}
        # Try direct JSON parse
        try:
            return json.loads(response_text)
        except (json.JSONDecodeError, TypeError):
            pass
        # Try to find JSON between ``` markers
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except (json.JSONDecodeError, TypeError):
                pass
        # Try to find JSON between first { and last }
        first_brace = response_text.find('{')
        last_brace = response_text.rfind('}')
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            try:
                return json.loads(response_text[first_brace:last_brace + 1])
            except (json.JSONDecodeError, TypeError):
                pass
        return {'summary': response_text, 'problems': [], 'learned_patterns': []}

    def _call_api(self, prompt: str) -> str:
        """Call LLM API (supports openai, deepseek, custom)."""
        import requests
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}'
        }
        if self.provider == 'openai':
            url = self.api_url or 'https://api.openai.com/v1/chat/completions'
            model = self.model or 'gpt-4o'
        elif self.provider == 'deepseek':
            url = self.api_url or 'https://api.deepseek.com/v1/chat/completions'
            model = self.model or 'deepseek-chat'
        elif self.provider == 'custom':
            url = self.api_url
            model = self.model or 'default'
        else:
            raise ValueError(f"Unsupported LLM provider: {self.provider}")
        payload = {
            'model': model,
            'temperature': 0.3,
            'messages': [{'role': 'user', 'content': prompt}]
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        return data['choices'][0]['message']['content']


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
