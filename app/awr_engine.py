"""
Oracle AWR Report Parser & Analysis Engine
Parses AWR HTML reports, extracts metrics, and generates analysis.
Includes self-learning knowledge base integration.
"""
import re
import json
from bs4 import BeautifulSoup
from datetime import datetime


class AWRParser:
    """Parse Oracle AWR HTML reports and extract key metrics."""

    def parse(self, html_content):
        """Parse AWR HTML and return structured data."""
        soup = BeautifulSoup(html_content, 'lxml')
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
        }
        return result

    def _find_table_after(self, soup, pattern):
        """Find the first table element following a header matching pattern."""
        for header in soup.find_all(['h2', 'h3', 'h4', 'th', 'td', 'b', 'a']):
            text = header.get_text(strip=True)
            if re.search(pattern, text, re.IGNORECASE):
                table = header.find_next('table')
                if table:
                    return table
        return None

    def _parse_table(self, table):
        """Parse an HTML table into list of dicts."""
        if not table:
            return []
        rows = table.find_all('tr')
        if len(rows) < 2:
            return []
        headers = [th.get_text(strip=True) for th in rows[0].find_all(['th', 'td'])]
        data = []
        for row in rows[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all(['td', 'th'])]
            if cells and len(cells) >= len(headers):
                data.append(dict(zip(headers, cells[:len(headers)])))
            elif cells:
                padded = cells + [''] * (len(headers) - len(cells))
                data.append(dict(zip(headers, padded)))
        return data

    def _extract_db_info(self, soup):
        info = {'db_name': '', 'instance_name': '', 'db_version': '', 'host_name': '', 'platform': ''}
        # Try typical AWR patterns
        text = soup.get_text()
        m = re.search(r'DB\s*Name\s*[:\s]+(\S+)', text)
        if m: info['db_name'] = m.group(1)
        m = re.search(r'Instance\s*Name\s*[:\s]+(\S+)', text)
        if m: info['instance_name'] = m.group(1)
        m = re.search(r'(?:DB\s*)?Version\s*[:\s]+([\d\.]+)', text)
        if m: info['db_version'] = m.group(1)
        m = re.search(r'Host\s*Name\s*[:\s]+(\S+)', text)
        if m: info['host_name'] = m.group(1)
        m = re.search(r'Platform\s*[:\s]+(.+?)(?:\n|$)', text)
        if m: info['platform'] = m.group(1).strip()

        # Also try table-based extraction
        table = self._find_table_after(soup, r'Database\s+Instance|DB\s+Name')
        if table:
            rows = table.find_all('tr')
            for row in rows:
                cells = [td.get_text(strip=True) for td in row.find_all(['td', 'th'])]
                for i, cell in enumerate(cells):
                    if 'DB Name' in cell and i + 1 < len(cells):
                        info['db_name'] = cells[i + 1]
                    elif 'Instance' in cell and 'Name' in cell and i + 1 < len(cells):
                        info['instance_name'] = cells[i + 1]
                    elif 'Version' in cell and i + 1 < len(cells):
                        info['db_version'] = cells[i + 1]
                    elif 'Host' in cell and i + 1 < len(cells):
                        info['host_name'] = cells[i + 1]
        return info

    def _extract_snap_info(self, soup):
        info = {'snap_begin': '', 'snap_end': '', 'duration': '', 'begin_id': '', 'end_id': ''}
        text = soup.get_text()
        m = re.search(r'Begin\s+Snap\s*[:\s]+(\d+)', text)
        if m: info['begin_id'] = m.group(1)
        m = re.search(r'End\s+Snap\s*[:\s]+(\d+)', text)
        if m: info['end_id'] = m.group(1)
        m = re.search(r'Elapsed\s*[:\s]+([\d:\.]+)\s*\(?(?:min|hrs)?', text)
        if m: info['duration'] = m.group(1)

        table = self._find_table_after(soup, r'Snap\s+Id|Snapshot')
        if table:
            rows = table.find_all('tr')
            for row in rows:
                cells = [td.get_text(strip=True) for td in row.find_all(['td', 'th'])]
                cell_text = ' '.join(cells)
                if 'Begin' in cell_text:
                    for c in cells[1:]:
                        if re.match(r'\d', c):
                            if not info['begin_id']: info['begin_id'] = c
                            elif not info['snap_begin']: info['snap_begin'] = c
                elif 'End' in cell_text:
                    for c in cells[1:]:
                        if re.match(r'\d', c):
                            if not info['end_id']: info['end_id'] = c
                            elif not info['snap_end']: info['snap_end'] = c
                elif 'Elapsed' in cell_text or 'Duration' in cell_text:
                    for c in cells[1:]:
                        if c and not info['duration']:
                            info['duration'] = c
        return info

    def _extract_load_profile(self, soup):
        table = self._find_table_after(soup, r'Load\s+Profile')
        return self._parse_table(table)

    def _extract_top_events(self, soup):
        table = self._find_table_after(soup, r'Top\s+\d+\s+(?:Timed\s+)?(?:Foreground\s+)?Events|Wait\s+Events')
        return self._parse_table(table)

    def _extract_top_sql(self, soup):
        results = {}
        for label in ['SQL ordered by Elapsed', 'SQL ordered by CPU', 'SQL ordered by Gets',
                       'SQL ordered by Reads', 'SQL ordered by Executions']:
            table = self._find_table_after(soup, label.replace(' ', r'\s+'))
            if table:
                results[label] = self._parse_table(table)[:20]  # Top 20
        return results

    def _extract_io_stats(self, soup):
        table = self._find_table_after(soup, r'IOStat|I/O\s+Stat|Tablespace\s+IO')
        return self._parse_table(table)

    def _extract_memory_stats(self, soup):
        stats = {}
        for label in ['SGA', 'PGA', 'Memory']:
            table = self._find_table_after(soup, label)
            if table:
                stats[label] = self._parse_table(table)
        return stats

    def _extract_instance_efficiency(self, soup):
        table = self._find_table_after(soup, r'Instance\s+Efficiency')
        return self._parse_table(table)

    def _extract_os_stats(self, soup):
        table = self._find_table_after(soup, r'Operating\s+System|OS\s+Stat')
        return self._parse_table(table)

    def _extract_rac_stats(self, soup):
        table = self._find_table_after(soup, r'RAC\s+Statistics|Global\s+Cache')
        return self._parse_table(table)


class AWRAnalyzer:
    """Analyze parsed AWR data and generate recommendations."""

    # Built-in knowledge rules for self-learning bootstrap
    BUILTIN_RULES = [
        {
            'category': 'wait_event',
            'title': 'db file sequential read 高等待',
            'pattern': 'db file sequential read',
            'description': 'db file sequential read 是单块读等待事件，通常与索引扫描相关。大量此等待可能表示索引设计不合理或存在大量随机I/O。',
            'solution': '1. 检查Top SQL中是否有全表扫描应改为索引扫描\n2. 检查I/O子系统性能(avg read time > 10ms需关注)\n3. 考虑将热点数据缓存到SGA\n4. 检查是否需要创建覆盖索引减少回表',
            'severity': 'medium',
        },
        {
            'category': 'wait_event',
            'title': 'db file scattered read 高等待',
            'pattern': 'db file scattered read',
            'description': 'db file scattered read 是多块读等待事件，与全表扫描和快速全索引扫描相关。',
            'solution': '1. 检查是否有不必要的全表扫描SQL\n2. 评估db_file_multiblock_read_count参数\n3. 考虑对大表进行分区\n4. 添加合适的索引避免全表扫描',
            'severity': 'medium',
        },
        {
            'category': 'wait_event',
            'title': 'log file sync 高等待',
            'pattern': 'log file sync',
            'description': 'log file sync 等待表示前台进程等待LGWR将redo写入磁盘。高等待通常与频繁提交或redo日志I/O性能差相关。',
            'solution': '1. 检查redo日志文件是否在高性能存储上\n2. 减少不必要的频繁COMMIT\n3. 检查LGWR进程是否有I/O瓶颈\n4. 考虑将redo日志放在独立的高速磁盘组',
            'severity': 'high',
        },
        {
            'category': 'wait_event',
            'title': 'enq: TX - row lock contention',
            'pattern': 'enq.*TX.*row lock|TX.*contention',
            'description': '行锁争用表示多个会话争抢同一行数据的锁，通常与应用设计有关。',
            'solution': '1. 检查应用逻辑是否有不必要的长事务\n2. 优化热点数据的并发访问模式\n3. 检查是否有未提交的事务阻塞其他会话\n4. 考虑使用乐观锁替代悲观锁',
            'severity': 'high',
        },
        {
            'category': 'wait_event',
            'title': 'latch/mutex 争用',
            'pattern': 'latch|mutex|shared pool|library cache',
            'description': 'Latch/Mutex争用通常表示内部内存结构的并发访问冲突，常见于shared pool和library cache。',
            'solution': '1. 检查是否有大量硬解析(使用绑定变量)\n2. 适当增大shared_pool_size\n3. 检查cursor_sharing参数\n4. 排查是否有过多不同SQL文本',
            'severity': 'high',
        },
        {
            'category': 'wait_event',
            'title': 'CPU等待过高',
            'pattern': 'CPU|cpu time|resmgr:cpu',
            'description': 'DB CPU时间占比过高，可能是SQL效率低下导致大量逻辑读，或服务器CPU资源不足。',
            'solution': '1. 优化消耗CPU最多的Top SQL\n2. 检查执行计划是否发生变化\n3. 评估是否需要增加CPU资源\n4. 检查是否有并行执行导致CPU饱和',
            'severity': 'medium',
        },
        {
            'category': 'sql_pattern',
            'title': 'SQL执行效率低下',
            'pattern': 'buffer_gets_per_exec > 100000',
            'description': '单次执行逻辑读超过10万通常表示SQL执行效率低下，需要优化。',
            'solution': '1. 检查执行计划是否走了全表扫描\n2. 添加或优化索引\n3. 重写SQL逻辑\n4. 检查统计信息是否过期',
            'severity': 'high',
        },
        {
            'category': 'memory',
            'title': 'Buffer Cache命中率低',
            'pattern': 'buffer.*hit.*ratio|cache.*hit',
            'description': 'Buffer Cache命中率低于95%表示可能需要增大SGA或优化SQL减少物理读。',
            'solution': '1. 增大db_cache_size\n2. 优化产生大量物理读的SQL\n3. 检查是否有不必要的全表扫描\n4. 评估数据热度分布',
            'severity': 'medium',
        },
        {
            'category': 'io_pattern',
            'title': 'I/O延迟过高',
            'pattern': 'avg.*read.*time|io.*latency',
            'description': '平均单次读取超过10ms可能表示存储子系统存在瓶颈。',
            'solution': '1. 检查存储系统性能和负载\n2. 评估是否需要升级到SSD/NVMe\n3. 优化I/O密集型SQL\n4. 检查ASM磁盘组balance',
            'severity': 'high',
        },
        {
            'category': 'general',
            'title': 'DB Time远大于Elapsed Time',
            'pattern': 'db_time_ratio > 1',
            'description': '当DB Time远大于Elapsed Time时，表示系统存在严重的并发等待，活跃会话数过多。',
            'solution': '1. 检查Top等待事件找出瓶颈\n2. 评估连接池配置是否合理\n3. 检查是否有锁等待\n4. 考虑限制并发会话数',
            'severity': 'critical',
        },
    ]

    def analyze(self, parsed_data, knowledge_entries=None):
        """Run full analysis on parsed AWR data."""
        analysis = {
            'summary': self._generate_summary(parsed_data),
            'performance_score': self._calculate_score(parsed_data),
            'wait_events_analysis': self._analyze_wait_events(parsed_data, knowledge_entries),
            'sql_analysis': self._analyze_sql(parsed_data, knowledge_entries),
            'io_analysis': self._analyze_io(parsed_data, knowledge_entries),
            'memory_analysis': self._analyze_memory(parsed_data, knowledge_entries),
            'recommendations': self._generate_recommendations(parsed_data, knowledge_entries),
        }
        return analysis

    def _generate_summary(self, data):
        db_info = data.get('db_info', {})
        snap_info = data.get('snap_info', {})
        load = data.get('load_profile', [])

        summary = {
            'database': f"{db_info.get('db_name', 'N/A')} ({db_info.get('instance_name', 'N/A')})",
            'version': db_info.get('db_version', 'N/A'),
            'host': db_info.get('host_name', 'N/A'),
            'snap_range': f"#{snap_info.get('begin_id', '?')} - #{snap_info.get('end_id', '?')}",
            'duration': snap_info.get('duration', 'N/A'),
            'top_events_count': len(data.get('top_events', [])),
            'load_metrics': {},
        }

        for item in load:
            for key, val in item.items():
                if key.lower() not in ('', 'per second', 'per transaction'):
                    summary['load_metrics'][key] = val
        return json.dumps(summary, ensure_ascii=False)

    def _calculate_score(self, data):
        """Calculate a 0-100 performance score."""
        score = 85.0  # Start with baseline
        events = data.get('top_events', [])
        efficiency = data.get('instance_efficiency', [])

        # Deduct for high-impact wait events
        critical_waits = ['enq:', 'log file sync', 'latch', 'buffer busy']
        for evt in events:
            evt_name = ' '.join(str(v) for v in evt.values()).lower()
            for cw in critical_waits:
                if cw in evt_name:
                    score -= 5

        # Check efficiency ratios
        for eff in efficiency:
            for key, val in eff.items():
                try:
                    num = float(val.replace('%', '').replace(',', ''))
                    if 'hit' in key.lower() and 'ratio' in key.lower() and num < 95:
                        score -= (95 - num) * 0.5
                except (ValueError, AttributeError):
                    pass

        return max(0, min(100, round(score, 1)))

    def _analyze_wait_events(self, data, knowledge_entries=None):
        events = data.get('top_events', [])
        findings = []
        kb = knowledge_entries or []

        for evt in events:
            evt_text = ' '.join(str(v) for v in evt.values()).lower()
            matched_kb = []

            # Match against knowledge base
            for entry in kb:
                if entry.get('category') == 'wait_event' and entry.get('pattern'):
                    if re.search(entry['pattern'], evt_text, re.IGNORECASE):
                        matched_kb.append(entry)

            # Match against builtin rules
            for rule in self.BUILTIN_RULES:
                if rule['category'] == 'wait_event' and rule.get('pattern'):
                    if re.search(rule['pattern'], evt_text, re.IGNORECASE):
                        if not any(m.get('title') == rule['title'] for m in matched_kb):
                            matched_kb.append(rule)

            findings.append({
                'event': evt,
                'matches': [{'title': m.get('title', ''), 'description': m.get('description', ''),
                             'solution': m.get('solution', ''), 'severity': m.get('severity', 'medium'),
                             'source': m.get('source', 'builtin')} for m in matched_kb]
            })
        return json.dumps(findings, ensure_ascii=False)

    def _analyze_sql(self, data, knowledge_entries=None):
        top_sql = data.get('top_sql', {})
        findings = []
        for category, sqls in top_sql.items():
            for sql in sqls[:10]:
                findings.append({'category': category, 'sql_info': sql})
        return json.dumps(findings, ensure_ascii=False)

    def _analyze_io(self, data, knowledge_entries=None):
        io_stats = data.get('io_stats', [])
        findings = []
        for stat in io_stats:
            findings.append({'stat': stat})
        return json.dumps(findings, ensure_ascii=False)

    def _analyze_memory(self, data, knowledge_entries=None):
        mem = data.get('memory_stats', {})
        eff = data.get('instance_efficiency', [])
        return json.dumps({'memory': mem, 'efficiency': eff}, ensure_ascii=False)

    def _generate_recommendations(self, data, knowledge_entries=None):
        recs = []
        events = data.get('top_events', [])
        kb = knowledge_entries or []
        all_rules = kb + self.BUILTIN_RULES

        for evt in events:
            evt_text = ' '.join(str(v) for v in evt.values()).lower()
            for rule in all_rules:
                if rule.get('pattern') and re.search(rule['pattern'], evt_text, re.IGNORECASE):
                    recs.append({
                        'title': rule.get('title', ''),
                        'severity': rule.get('severity', 'medium'),
                        'solution': rule.get('solution', ''),
                        'source': rule.get('source', 'builtin'),
                    })

        # Deduplicate by title
        seen = set()
        unique_recs = []
        for r in recs:
            if r['title'] not in seen:
                seen.add(r['title'])
                unique_recs.append(r)

        return json.dumps(unique_recs, ensure_ascii=False)

    def learn_from_analysis(self, parsed_data, analysis_result):
        """Extract new knowledge patterns from an analysis. Returns list of potential new KB entries."""
        new_entries = []
        events = parsed_data.get('top_events', [])

        for evt in events:
            evt_text = ' '.join(str(v) for v in evt.values()).lower()
            # Check if any builtin rule matches
            matched = False
            for rule in self.BUILTIN_RULES:
                if rule.get('pattern') and re.search(rule['pattern'], evt_text, re.IGNORECASE):
                    matched = True
                    break

            if not matched and evt_text.strip():
                # This is a new pattern we haven't seen
                new_entries.append({
                    'category': 'wait_event',
                    'title': f"新发现等待事件模式: {evt_text[:80]}",
                    'pattern': re.escape(evt_text[:50]),
                    'description': f"从AWR报告中自动发现的等待事件模式: {evt_text}",
                    'solution': '需要进一步分析此等待事件的具体原因和优化方案。',
                    'severity': 'medium',
                    'source': 'learned',
                    'confidence': 0.3,
                })
        return new_entries


class LLMIntegration:
    """Interface for external LLM analysis enhancement."""

    def __init__(self, provider='none', api_key='', api_url='', model=''):
        self.provider = provider
        self.api_key = api_key
        self.api_url = api_url
        self.model = model

    def enhance_analysis(self, parsed_data, basic_analysis):
        """Send data to LLM for enhanced analysis."""
        if self.provider == 'none' or not self.api_key:
            return None

        import requests as req

        prompt = self._build_prompt(parsed_data, basic_analysis)

        try:
            if self.provider == 'openai':
                return self._call_openai(prompt)
            elif self.provider == 'deepseek':
                return self._call_deepseek(prompt)
            elif self.provider == 'custom':
                return self._call_custom(prompt)
        except Exception as e:
            return f"LLM分析失败: {str(e)}"

        return None

    def _build_prompt(self, parsed_data, basic_analysis):
        return f"""你是Oracle数据库高级DBA专家。请分析以下AWR报告数据，给出专业的性能分析和优化建议。

## 数据库信息
{json.dumps(parsed_data.get('db_info', {}), ensure_ascii=False, indent=2)}

## 快照信息
{json.dumps(parsed_data.get('snap_info', {}), ensure_ascii=False, indent=2)}

## 负载概况
{json.dumps(parsed_data.get('load_profile', [])[:10], ensure_ascii=False, indent=2)}

## Top等待事件
{json.dumps(parsed_data.get('top_events', [])[:15], ensure_ascii=False, indent=2)}

## 基础分析结果
性能评分: {basic_analysis.get('performance_score', 'N/A')}

请从以下维度给出分析:
1. **整体健康评估** - 数据库当前运行状态
2. **关键瓶颈** - 最需要关注的性能问题
3. **等待事件分析** - 主要等待事件的原因和影响
4. **SQL优化建议** - 针对Top SQL的优化方向
5. **系统资源** - I/O、内存、CPU使用建议
6. **优先行动项** - 按优先级排列的具体优化步骤

请用中文回答，给出具体可操作的建议。"""

    def _call_openai(self, prompt):
        import requests as req
        url = self.api_url or 'https://api.openai.com/v1/chat/completions'
        headers = {'Authorization': f'Bearer {self.api_key}', 'Content-Type': 'application/json'}
        data = {
            'model': self.model or 'gpt-4o',
            'messages': [{'role': 'user', 'content': prompt}],
            'temperature': 0.3,
            'max_tokens': 4000,
        }
        resp = req.post(url, headers=headers, json=data, timeout=120)
        resp.raise_for_status()
        return resp.json()['choices'][0]['message']['content']

    def _call_deepseek(self, prompt):
        import requests as req
        url = self.api_url or 'https://api.deepseek.com/v1/chat/completions'
        headers = {'Authorization': f'Bearer {self.api_key}', 'Content-Type': 'application/json'}
        data = {
            'model': self.model or 'deepseek-chat',
            'messages': [{'role': 'user', 'content': prompt}],
            'temperature': 0.3,
            'max_tokens': 4000,
        }
        resp = req.post(url, headers=headers, json=data, timeout=120)
        resp.raise_for_status()
        return resp.json()['choices'][0]['message']['content']

    def _call_custom(self, prompt):
        import requests as req
        if not self.api_url:
            return "自定义LLM未配置API地址"
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
        data = {
            'model': self.model or 'default',
            'messages': [{'role': 'user', 'content': prompt}],
            'temperature': 0.3,
        }
        resp = req.post(self.api_url, headers=headers, json=data, timeout=120)
        resp.raise_for_status()
        result = resp.json()
        if 'choices' in result:
            return result['choices'][0]['message']['content']
        return json.dumps(result, ensure_ascii=False)
