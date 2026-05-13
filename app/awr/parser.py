"""AWR HTML report parser."""
import re
import json
import logging
from bs4 import BeautifulSoup

from .utils import _safe_float, classify_wait_event

logger = logging.getLogger(__name__)


class AWRParser:
    """Parse Oracle AWR HTML reports and extract structured metrics."""

    def parse(self, html_content: str) -> dict:
        """Parse AWR HTML and return structured data dict."""
        try:
            soup = BeautifulSoup(html_content, 'lxml')
        except Exception:
            logger.debug("parse lxml fallback to html.parser", exc_info=True)
            soup = BeautifulSoup(html_content, 'html.parser')
        result = {
            # Original 13 sections
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
            # New sections (v2)
            'advisories': self._extract_advisories(soup),
            'enqueue_activity': self._extract_enqueue_activity(soup),
            'latch_detail': self._extract_latch_detail(soup),
            'wait_histogram': self._extract_wait_histogram(soup),
            'undo_stats': self._extract_undo_stats(soup),
            'wait_class_summary': self._extract_wait_class_summary(soup),
            'temp_stats': self._extract_temp_stats(soup),
            'time_model': self._extract_time_model(soup),
            # New sections (Batch 4 - missing AWR chapters)
            'io_profile': self._extract_io_profile(soup),
            'file_io_stats': self._extract_file_io_stats(soup),
            'dictionary_cache_stats': self._extract_dictionary_cache_stats(soup),
            'library_cache_activity': self._extract_library_cache_activity(soup),
            'init_parameters': self._extract_init_parameters(soup),
            'background_wait_events': self._extract_background_wait_events(soup),
            'service_statistics': self._extract_service_statistics(soup),
            'instance_recovery_stats': self._extract_instance_recovery_stats(soup),
        }
        # Enrich top_events with wait_class classification
        for evt in result.get('top_events', []):
            ename = evt.get('event', evt.get('name', ''))
            if ename and not evt.get('wait_class'):
                evt['wait_class'] = classify_wait_event(ename)
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
            logger.debug("_find_table_after failed", exc_info=True)
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
            logger.debug("_parse_table failed", exc_info=True)
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
            logger.debug("_extract_db_info failed", exc_info=True)
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
            logger.debug("_extract_snap_info failed", exc_info=True)
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
            logger.debug("_extract_load_profile failed", exc_info=True)
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
            logger.debug("_extract_top_events failed", exc_info=True)
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
            logger.debug("_extract_top_sql failed", exc_info=True)
            pass
        return result

    def _extract_io_stats(self, soup) -> list:
        try:
            table = self._find_table_after(soup, r'IOStat|I/O\s*Stat|Tablespace\s+IO\s+Stats')
            return self._parse_table(table)
        except Exception:
            logger.debug("_extract_io_stats failed", exc_info=True)
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
            logger.debug("_extract_memory_stats failed", exc_info=True)
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
            logger.debug("_extract_instance_efficiency failed", exc_info=True)
            return []

    def _extract_os_stats(self, soup) -> list:
        try:
            table = self._find_table_after(soup, r'Operating\s+System\s+Statistics|OS\s+Statistics')
            return self._parse_table(table)
        except Exception:
            logger.debug("_extract_os_stats failed", exc_info=True)
            return []

    def _extract_rac_stats(self, soup) -> list:
        try:
            table = self._find_table_after(soup, r'RAC\s+Statistics|Global\s+Cache')
            return self._parse_table(table)
        except Exception:
            logger.debug("_extract_rac_stats failed", exc_info=True)
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
            logger.debug("_extract_redo_stats failed", exc_info=True)
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
            logger.debug("_extract_parse_stats failed", exc_info=True)
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
            logger.debug("_extract_segment_stats failed", exc_info=True)
            pass
        return result

    # -----------------------------------------------------------------
    # NEW PARSER SECTIONS (v2)
    # -----------------------------------------------------------------

    def _extract_advisories(self, soup) -> dict:
        """Extract Buffer Pool, PGA, Shared Pool, SGA Target advisories."""
        result = {}
        try:
            advisory_patterns = {
                'Buffer Pool': r'Buffer\s+Pool\s+Advisory',
                'PGA': r'PGA\s+(?:Aggregate\s+)?(?:Target\s+)?Advisory',
                'Shared Pool': r'Shared\s+Pool\s+Advisory',
                'SGA Target': r'SGA\s+Target\s+Advisory',
            }
            for name, pattern in advisory_patterns.items():
                table = self._find_table_after(soup, pattern)
                rows = self._parse_table(table)
                if rows:
                    result[name] = rows
        except Exception:
            logger.debug("_extract_advisories failed", exc_info=True)
            pass
        return result

    def _extract_enqueue_activity(self, soup) -> list:
        """Extract Enqueue Activity (lock wait breakdown)."""
        try:
            table = self._find_table_after(soup, r'Enqueue\s+Activity')
            return self._parse_table(table)
        except Exception:
            logger.debug("_extract_enqueue_activity failed", exc_info=True)
            return []

    def _extract_latch_detail(self, soup) -> list:
        """Extract Latch Statistics / Latch Sleep Breakdown."""
        result = []
        try:
            for pattern in [r'Latch\s+Activity', r'Latch\s+Sleep\s+Breakdown',
                            r'Latch\s+Miss\s+Sources', r'Latch\s+Statistics']:
                table = self._find_table_after(soup, pattern)
                rows = self._parse_table(table)
                for row in rows:
                    row['_section'] = pattern.replace('\\s+', ' ')
                result.extend(rows)
        except Exception:
            logger.debug("_extract_latch_detail failed", exc_info=True)
            pass
        return result

    def _extract_wait_histogram(self, soup) -> list:
        """Extract Wait Event Histogram (time distribution buckets)."""
        try:
            table = self._find_table_after(soup, r'Wait\s+Event\s+Histogram')
            return self._parse_table(table)
        except Exception:
            logger.debug("_extract_wait_histogram failed", exc_info=True)
            return []

    def _extract_undo_stats(self, soup) -> dict:
        """Extract Undo Segment Statistics / Summary."""
        result = {}
        try:
            table = self._find_table_after(soup, r'Undo\s+Segment\s+(?:Statistics|Summary)')
            rows = self._parse_table(table)
            if rows:
                result['rows'] = rows
            # Try to parse undo usage from text
            text = soup.get_text()
            m = re.search(r'Undo\s+(?:Tablespace|Space)\s+Used[:\s]*([\d\.]+)\s*(%|MB|GB)', text, re.IGNORECASE)
            if m:
                val = self._safe_float(m.group(1))
                unit = m.group(2).strip()
                if unit == '%':
                    result['used_pct'] = val
                else:
                    result['used_size'] = val
                    result['used_unit'] = unit
            # Also check for specific undo metrics in the table
            for row in rows:
                for k, v in row.items():
                    kl = k.lower()
                    if 'unexpired' in kl and 'steal' in kl:
                        result['unexpired_steal_count'] = self._safe_float(v)
                    elif 'tuned' in kl and 'retention' in kl:
                        result['tuned_undo_retention'] = self._safe_float(v)
        except Exception:
            logger.debug("_extract_undo_stats failed", exc_info=True)
            pass
        return result

    def _extract_wait_class_summary(self, soup) -> list:
        """Extract Foreground Wait Class summary (if present in AWR)."""
        try:
            table = self._find_table_after(soup, r'(?:Foreground\s+)?Wait\s+Class(?:es)?')
            rows = self._parse_table(table)
            return rows if rows else []
        except Exception:
            logger.debug("_extract_wait_class_summary failed", exc_info=True)
            return []

    def _extract_temp_stats(self, soup) -> dict:
        """Extract Temp/Sort segment usage statistics."""
        result = {}
        try:
            # Look for Temp tablespace usage
            text = soup.get_text()
            m = re.search(r'Temp\s+(?:Space|Tablespace)\s+Used[:\s]*([\d\.]+)\s*(%|MB|GB)', text, re.IGNORECASE)
            if m:
                val = self._safe_float(m.group(1))
                unit = m.group(2).strip()
                if unit == '%':
                    result['used_pct'] = val
                else:
                    result['used_size'] = val
                    result['used_unit'] = unit
            # Also look for sort-related metrics in Instance Activity
            table = self._find_table_after(soup, r'Instance\s+Activity\s+Stats')
            if table:
                rows = self._parse_table(table)
                for row in rows:
                    stat_name = (row.get('Statistic', row.get('name', ''))).lower()
                    total = self._safe_float(row.get('Total', row.get('value', 0)))
                    if 'sorts (disk)' in stat_name:
                        result['sorts_disk'] = total
                    elif 'sorts (memory)' in stat_name:
                        result['sorts_memory'] = total
                if result.get('sorts_disk', 0) > 0 and result.get('sorts_memory', 0) > 0:
                    total_sorts = result['sorts_disk'] + result['sorts_memory']
                    result['disk_sort_pct'] = (result['sorts_disk'] / total_sorts) * 100
        except Exception:
            logger.debug("_extract_temp_stats failed", exc_info=True)
            pass
        return result

    def _extract_time_model(self, soup) -> dict:
        """Extract Time Model Statistics (DB Time breakdown by component)."""
        result = {}
        try:
            table = self._find_table_after(soup, r'Time\s+Model\s+Statistics')
            rows = self._parse_table(table)
            for row in rows:
                stat_name = row.get('Statistic Name', row.get('Stat Name', row.get('name', '')))
                time_s = self._safe_float(row.get('Time (s)', row.get('time_s', row.get('value', 0))))
                pct = self._safe_float(row.get('% of DB Time', row.get('pct_db_time', 0)))
                if stat_name:
                    safe_key = re.sub(r'[^a-zA-Z0-9]', '_', stat_name.lower()).strip('_')
                    result[safe_key] = {'name': stat_name, 'time_seconds': time_s, 'pct_db_time': pct}
            # Also try text-based extraction for common time model metrics
            if not result:
                text = soup.get_text()
                tm_patterns = {
                    'DB CPU': r'DB\s+CPU[:\s]*([\d\.]+)',
                    'sql execute elapsed time': r'sql\s+execute\s+elapsed\s+time[:\s]*([\d\.]+)',
                    'PL/SQL execution elapsed time': r'PL/SQL\s+execution\s+elapsed\s+time[:\s]*([\d\.]+)',
                    'parse time elapsed': r'parse\s+time\s+elapsed[:\s]*([\d\.]+)',
                    'hard parse elapsed time': r'hard\s+parse\s+elapsed\s+time[:\s]*([\d\.]+)',
                    'connection management call elapsed time': r'connection\s+management\s+call\s+elapsed[:\s]*([\d\.]+)',
                    'sequence load elapsed time': r'sequence\s+load\s+elapsed[:\s]*([\d\.]+)',
                }
                for name, pat in tm_patterns.items():
                    m = re.search(pat, text, re.IGNORECASE)
                    if m:
                        safe_key = re.sub(r'[^a-zA-Z0-9]', '_', name.lower()).strip('_')
                        result[safe_key] = {'name': name, 'time_seconds': self._safe_float(m.group(1)), 'pct_db_time': 0}
        except Exception:
            logger.debug("_extract_time_model failed", exc_info=True)
            pass
        return result

    # --- Batch 4: Missing AWR chapter extractors ---

    def _extract_io_profile(self, soup) -> list:
        """Extract IO Profile summary (Read/Write IOPS, throughput, latency)."""
        try:
            table = self._find_table_after(soup, r'IO\s+Profile|IOProfile|I/O\s+Profile')
            if table:
                return self._parse_table(table)
            return []
        except Exception:
            logger.debug("_extract_io_profile failed", exc_info=True)
            return []

    def _extract_file_io_stats(self, soup) -> list:
        """Extract individual datafile IO statistics."""
        try:
            table = self._find_table_after(soup, r'File\s+IO\s+Stat|Datafile\s+IO|File\s+I/O')
            if table:
                return self._parse_table(table)
            return []
        except Exception:
            logger.debug("_extract_file_io_stats failed", exc_info=True)
            return []

    def _extract_dictionary_cache_stats(self, soup) -> list:
        """Extract Dictionary Cache (row cache) statistics."""
        try:
            table = self._find_table_after(soup, r'Dictionary\s+Cache\s+Stats|Row\s+Cache')
            if table:
                return self._parse_table(table)
            return []
        except Exception:
            logger.debug("_extract_dictionary_cache_stats failed", exc_info=True)
            return []

    def _extract_library_cache_activity(self, soup) -> list:
        """Extract Library Cache Activity statistics."""
        try:
            table = self._find_table_after(soup, r'Library\s+Cache\s+Activity')
            if table:
                return self._parse_table(table)
            return []
        except Exception:
            logger.debug("_extract_library_cache_activity failed", exc_info=True)
            return []

    def _extract_init_parameters(self, soup) -> list:
        """Extract non-default Initialization Parameters."""
        try:
            table = self._find_table_after(soup, r'init\.ora\s+Parameters|Initialization\s+Parameters|init\s+Parameters')
            if table:
                return self._parse_table(table)
            return []
        except Exception:
            logger.debug("_extract_init_parameters failed", exc_info=True)
            return []

    def _extract_background_wait_events(self, soup) -> list:
        """Extract Background Wait Events."""
        try:
            table = self._find_table_after(soup, r'Background\s+Wait\s+Events')
            if table:
                rows = self._parse_table(table)
                for row in rows:
                    ename = row.get('Event', row.get('event', ''))
                    if ename:
                        row['wait_class'] = classify_wait_event(ename)
                return rows
            return []
        except Exception:
            logger.debug("_extract_background_wait_events failed", exc_info=True)
            return []

    def _extract_service_statistics(self, soup) -> list:
        """Extract Service Statistics."""
        try:
            table = self._find_table_after(soup, r'Service\s+Statistics')
            if table:
                return self._parse_table(table)
            return []
        except Exception:
            logger.debug("_extract_service_statistics failed", exc_info=True)
            return []

    def _extract_instance_recovery_stats(self, soup) -> list:
        """Extract Instance Recovery Statistics."""
        try:
            table = self._find_table_after(soup, r'Instance\s+Recovery\s+Stats')
            if table:
                return self._parse_table(table)
            return []
        except Exception:
            logger.debug("_extract_instance_recovery_stats failed", exc_info=True)
            return []

    def _safe_float(self, val, default=0.0) -> float:
        return _safe_float(val, default)


