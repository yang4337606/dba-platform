"""AWR HTML report parser."""
from __future__ import annotations

import re
import json
import logging
from typing import Any

from bs4 import BeautifulSoup, Tag

from .utils import _safe_float, classify_wait_event

logger = logging.getLogger(__name__)


class AWRParser:
    """Parse Oracle AWR HTML reports and extract structured metrics."""

    def parse(self, html_content: str) -> dict[str, Any]:
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
            # New sections (v3 - 7 missing AWR chapters)
            'ash_activity': self._extract_ash_activity(soup),
            'addm_findings': self._extract_addm_findings(soup),
            'sql_plan_changes': self._extract_sql_plan_changes(soup),
            'host_instance_cpu': self._extract_host_instance_cpu(soup),
            'cache_sizes': self._extract_cache_sizes(soup),
            'segment_row_lock_itl': self._extract_segment_row_lock_itl(soup),
        }
        # Enrich top_events with wait_class classification
        for evt in result.get('top_events', []):
            ename = evt.get('event', evt.get('name', ''))
            if ename and not evt.get('wait_class'):
                evt['wait_class'] = classify_wait_event(ename)

        # Check if parsing yielded minimal data (non-standard report format)
        db_info = result.get('db_info', {})
        has_db_info = any(db_info.get(k) for k in ('db_name', 'instance_name', 'db_version'))
        has_metrics = bool(
            result.get('top_events')
            or result.get('load_profile', {}).get('raw')
            or result.get('instance_efficiency')
            or result.get('time_model')
        )
        if not has_db_info and not has_metrics:
            result['_parse_warning'] = (
                'Non-standard AWR report format detected: no database info or metrics could be extracted. '
                'The report may lack standard HTML structure (title, table summary attributes, or section headings).'
            )
            logger.warning("AWR parse yielded empty results – possible non-standard report format")

        return result

    def _find_table_after(self, soup: BeautifulSoup, pattern: str) -> Tag | None:
        """Find the first table element following a header matching pattern.

        Handles Oracle AWR HTML quirks:
        - Section headers as <h3 class="awr">Title</h3>
        - Bare text nodes between <p/> tags (e.g. '<p/>Load Profile<p/>')
        - Table summary attributes
        Avoids matching TOC <a> links or <th>/<td> inside tables which would
        return the wrong table via find_next().
        """
        try:
            # Strategy 1: Match h2/h3/h4 headings (most reliable for AWR)
            for tag in soup.find_all(['h2', 'h3', 'h4']):
                text = tag.get_text(strip=True)
                if text and re.search(pattern, text, re.IGNORECASE):
                    table = tag.find_next('table')
                    if table:
                        return table

            # Strategy 2: Match text in <b>, <span>, <p> tags (NOT inside tables or links)
            for tag in soup.find_all(['b', 'span', 'p']):
                if tag.find_parent('table') or tag.find_parent('a'):
                    continue
                text = tag.get_text(strip=True)
                if text and re.search(pattern, text, re.IGNORECASE):
                    table = tag.find_next('table')
                    if table:
                        return table

            # Strategy 3: Search bare NavigableStrings (text nodes not inside tags)
            from bs4 import NavigableString
            for text_node in soup.find_all(string=re.compile(pattern, re.IGNORECASE)):
                if isinstance(text_node, NavigableString):
                    parent = text_node.parent
                    if parent and parent.name in ('a', 'th', 'td', 'li', 'title', 'style', 'script', 'option'):
                        continue
                    if parent and parent.find_parent('table'):
                        continue
                    table = text_node.find_next('table')
                    if table:
                        return table

            # Strategy 4: Match table summary attribute
            for table in soup.find_all('table'):
                summary = table.get('summary', '')
                if summary and re.search(pattern, summary, re.IGNORECASE):
                    return table

            return None
        except Exception:
            logger.debug("_find_table_after failed", exc_info=True)
            return None

    def _parse_table(self, table: Tag | None) -> list[dict[str, str]]:
        """Parse an HTML table into list of dicts.

        Handles multi-row headers common in AWR reports where row 0 is a
        group header (with colspan) and row 1 contains the actual column names.
        """
        if table is None:
            return []
        try:
            rows = table.find_all('tr')
            if not rows:
                return []

            # Determine the true header row.
            # AWR tables sometimes have a group-header row 0 with colspan that
            # has fewer cells than the actual data. In that case row 1 (if it
            # exists and has more cells) is the real header.
            header_idx = 0
            header_row = rows[0]
            header_cells = header_row.find_all(['th', 'td'])
            headers = [cell.get_text(strip=True) for cell in header_cells]

            if len(rows) > 2:
                row1_cells = rows[1].find_all(['th', 'td'])
                row1_headers = [cell.get_text(strip=True) for cell in row1_cells]
                # If row 1 has more columns than row 0, it's likely the real header
                # (row 0 is a spanning group header).  Also accept when row 0
                # contains a cell with colspan.
                has_colspan = any(cell.get('colspan') for cell in header_cells)
                if len(row1_headers) > len(headers) or (has_colspan and len(row1_headers) >= len(headers)):
                    # Prefer row 1 only if its cells look like headers (contain <th>
                    # or have meaningful text)
                    row1_th_count = len(rows[1].find_all('th'))
                    if row1_th_count > 0 or len(row1_headers) > len(headers):
                        headers = row1_headers
                        header_idx = 1

            if not headers:
                return []
            result = []
            for row in rows[header_idx + 1:]:
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

    def _extract_db_info(self, soup: BeautifulSoup) -> dict[str, str]:
        result = {'db_name': '', 'instance_name': '', 'db_version': '', 'host_name': '', 'platform': ''}
        try:
            # Strategy 1: Parse from <title> tag (most reliable for AWR)
            # Format: "AWR Report for DB: TESTDB, Inst: testdb, Snaps: 2992-3003"
            title_tag = soup.find('title')
            if title_tag:
                title_text = title_tag.get_text(strip=True)
                m = re.search(r'DB:\s*(\S+)', title_text, re.IGNORECASE)
                if m:
                    result['db_name'] = m.group(1).rstrip(',')
                m = re.search(r'Inst:\s*(\S+)', title_text, re.IGNORECASE)
                if m:
                    result['instance_name'] = m.group(1).rstrip(',')

            # Strategy 2: Parse DB info table by summary attribute
            table = None
            for t in soup.find_all('table'):
                summary = (t.get('summary') or '').lower()
                if 'database instance' in summary or 'database info' in summary:
                    table = t
                    break
            if not table:
                table = self._find_table_after(soup, r'Database Instance Information|DB\s*Name')

            if table:
                rows = self._parse_table(table)
                for row in rows:
                    for k, v in row.items():
                        kl = k.lower()
                        if ('db name' in kl or 'db_name' in kl) and v and not result['db_name']:
                            result['db_name'] = v
                        elif ('instance' in kl) and v and not result['instance_name']:
                            result['instance_name'] = v
                        elif ('release' in kl or 'version' in kl) and v and not result['db_version']:
                            result['db_version'] = v

            # Strategy 3: Parse host info table
            host_table = None
            for t in soup.find_all('table'):
                summary = (t.get('summary') or '').lower()
                if 'host' in summary:
                    host_table = t
                    break
            if not host_table:
                host_table = self._find_table_after(soup, r'Host\s+Name')
            if host_table and host_table != table:
                rows = self._parse_table(host_table)
                for row in rows:
                    for k, v in row.items():
                        kl = k.lower()
                        if 'host' in kl and v and not result['host_name']:
                            result['host_name'] = v
                        elif 'platform' in kl and v and not result['platform']:
                            result['platform'] = v

        except Exception:
            logger.debug("_extract_db_info failed", exc_info=True)
            pass
        return result

    def _extract_snap_info(self, soup: BeautifulSoup) -> dict[str, Any]:
        result = {'begin_id': '', 'end_id': '', 'snap_begin': '', 'snap_end': '',
                  'duration': '', 'elapsed_seconds': 0}
        try:
            # Strategy 1: Parse from <title> tag
            # Format: "AWR Report for DB: TESTDB, Inst: testdb, Snaps: 2992-3003"
            title_tag = soup.find('title')
            if title_tag:
                title_text = title_tag.get_text(strip=True)
                m = re.search(r'Snaps?:\s*(\d+)\s*-\s*(\d+)', title_text, re.IGNORECASE)
                if m:
                    result['begin_id'] = m.group(1)
                    result['end_id'] = m.group(2)

            # Strategy 2: Parse snapshot table (find by summary attribute or heading)
            snap_table = None
            for t in soup.find_all('table'):
                summary = (t.get('summary') or '').lower()
                if 'snapshot' in summary or 'snap' in summary:
                    snap_table = t
                    break
            if not snap_table:
                snap_table = self._find_table_after(soup, r'Snap\s*Id|Snapshot')

            if snap_table:
                # AWR snapshot tables have special layout:
                # Row 1: headers (Snap Id, Snap Time, Sessions, ...)
                # Row 2: Begin Snap: | 2992 | 17-Nov-19 00:00:08 | ...
                # Row 3: End Snap: | 3003 | 17-Nov-19 11:00:44 | ...
                # Row 4: Elapsed: | | 660.60 (mins) | ...
                # Row 5: DB Time: | | 0.86 (mins) | ...
                all_rows = snap_table.find_all('tr')
                for row in all_rows:
                    cells = [cell.get_text(strip=True) for cell in row.find_all(['th', 'td'])]
                    row_text = ' '.join(cells).lower()
                    if 'begin' in row_text and 'snap' in row_text:
                        for cell in cells:
                            if re.match(r'^\d+$', cell.strip()):
                                if not result['begin_id']:
                                    result['begin_id'] = cell.strip()
                                    continue
                            # Match standard Oracle date (DD-Mon-YY) or Chinese/corrupted locale dates
                            if re.search(r'\d{1,2}[-/].{1,10}[-/\s]\d{2,4}\s+\d{1,2}:\d{2}', cell):
                                result['snap_begin'] = cell.strip()
                            elif re.search(r'\d{1,2}[-/]\w{3}[-/]\d{2,4}', cell):
                                result['snap_begin'] = cell.strip()
                    elif 'end' in row_text and 'snap' in row_text:
                        for cell in cells:
                            if re.match(r'^\d+$', cell.strip()):
                                if not result['end_id']:
                                    result['end_id'] = cell.strip()
                                    continue
                            if re.search(r'\d{1,2}[-/].{1,10}[-/\s]\d{2,4}\s+\d{1,2}:\d{2}', cell):
                                result['snap_end'] = cell.strip()
                            elif re.search(r'\d{1,2}[-/]\w{3}[-/]\d{2,4}', cell):
                                result['snap_end'] = cell.strip()
                    elif 'elapsed' in row_text:
                        for cell in cells:
                            m = re.search(r'([\d,\.]+)\s*\(?(min|sec|hrs|hour)?', cell, re.IGNORECASE)
                            if m:
                                val = self._safe_float(m.group(1).replace(',', ''))
                                unit = (m.group(2) or '').lower()
                                if 'min' in unit:
                                    result['elapsed_seconds'] = val * 60
                                elif 'hrs' in unit or 'hour' in unit:
                                    result['elapsed_seconds'] = val * 3600
                                else:
                                    result['elapsed_seconds'] = val
                                result['duration'] = cell.strip()
                                break

            # Strategy 3: Fallback regex on separated text
            if not result['begin_id']:
                text = soup.get_text(separator=' ')
                m = re.search(r'Begin\s+Snap[:\s]+(\d+)', text, re.IGNORECASE)
                if m:
                    result['begin_id'] = m.group(1)
                m = re.search(r'End\s+Snap[:\s]+(\d+)', text, re.IGNORECASE)
                if m:
                    result['end_id'] = m.group(1)
            if not result['elapsed_seconds']:
                text = soup.get_text(separator=' ')
                m = re.search(r'Elapsed[:\s]+([\d,\.]+)\s*\(?(min|sec|hrs)?', text, re.IGNORECASE)
                if m:
                    val = self._safe_float(m.group(1).replace(',', ''))
                    unit = (m.group(2) or '').lower()
                    if 'min' in unit:
                        result['elapsed_seconds'] = val * 60
                    elif 'hrs' in unit or 'hour' in unit:
                        result['elapsed_seconds'] = val * 3600
                    else:
                        result['elapsed_seconds'] = val

        except Exception:
            logger.debug("_extract_snap_info failed", exc_info=True)
            pass
        return result

    def _extract_load_profile(self, soup: BeautifulSoup) -> dict[str, Any]:
        try:
            table = self._find_table_after(soup, r'Load Profile')
            rows = self._parse_table(table)
            computed = {}
            # Map common load profile metric names to keys
            metric_map = {
                'db time': 'db_time',
                'db cpu': 'db_cpu',
                'redo size': 'redo_size',
                'logical read': 'logical_reads',
                'physical read': 'physical_reads',
                'hard parse': 'hard_parses',
                'parses': 'parses',
                'execute': 'executes',
                'transaction': 'transactions',
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

    def _extract_top_events(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        """Extract Top Timed Events with %DB Time, Avg Wait, Wait Class."""
        try:
            table = self._find_table_after(soup, r'Top\s+(?:\d+\s+)?(?:Timed|Foreground)\s+Events|Top\s+Timed\s+Events')
            rows = self._parse_table(table)
            events = []
            for row in rows:
                event = {'event': '', 'waits': 0, 'time': 0, 'avg_wait': 0,
                         'pct_db_time': 0, 'wait_class': ''}
                for k, v in row.items():
                    kl = k.lower()
                    if 'event' in kl or kl == 'name':
                        event['event'] = v
                    elif kl == 'waits' or kl == 'wait count':
                        event['waits'] = self._safe_float(v)
                    elif 'avg' in kl and 'wait' in kl:
                        event['avg_wait'] = self._safe_float(v)
                    elif 'db time' in kl:
                        event['pct_db_time'] = self._safe_float(v)
                    elif 'class' in kl:
                        event['wait_class'] = v
                    elif 'total wait' in kl or ('time' in kl and 'db' not in kl
                          and 'avg' not in kl and '%' not in kl and 'out' not in kl):
                        event['time'] = self._safe_float(v)
                if event['event']:
                    events.append(event)
            return events
        except Exception:
            logger.debug("_extract_top_events failed", exc_info=True)
            return []

    def _extract_top_sql(self, soup: BeautifulSoup) -> dict[str, list[dict[str, str]]]:
        """Extract SQL ordered by Elapsed/CPU/Gets/Reads/Executions."""
        result = {}
        sections = [
            ('SQL ordered by Elapsed Time', r'SQL\s+ordered\s+by\s+Elapsed\s+Time'),
            ('SQL ordered by CPU Time', r'SQL\s+ordered\s+by\s+CPU\s+Time'),
            ('SQL ordered by Gets', r'SQL\s+ordered\s+by\s+Gets'),
            ('SQL ordered by Reads', r'SQL\s+ordered\s+by\s+Reads'),
            ('SQL ordered by Executions', r'SQL\s+ordered\s+by\s+Executions'),
            ('SQL ordered by Parse Calls', r'SQL\s+ordered\s+by\s+Parse\s+Calls'),
            ('SQL ordered by Sharable Memory', r'SQL\s+ordered\s+by\s+Sharable\s+Mem'),
            ('SQL ordered by Version Count', r'SQL\s+ordered\s+by\s+Version\s+Count'),
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

    def _extract_io_stats(self, soup: BeautifulSoup) -> list[dict[str, str]]:
        try:
            table = self._find_table_after(soup, r'IOStat|I/O\s*Stat|Tablespace\s+IO\s+Stats')
            return self._parse_table(table)
        except Exception:
            logger.debug("_extract_io_stats failed", exc_info=True)
            return []

    def _extract_memory_stats(self, soup: BeautifulSoup) -> dict[str, Any]:
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

    def _extract_instance_efficiency(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        try:
            table = self._find_table_after(soup, r'Instance\s+Efficiency\s+Percentages|Instance\s+Efficiency')
            result = []
            if table:
                # AWR Instance Efficiency table has a special 4-column layout:
                # <td>Name1:</td><td>Value1</td><td>Name2:</td><td>Value2</td>
                # No header row, just td pairs.
                all_rows = table.find_all('tr')
                for row in all_rows:
                    cells = [cell.get_text(strip=True) for cell in row.find_all(['th', 'td'])]
                    # Process pairs: (name, value, name, value, ...)
                    i = 0
                    while i < len(cells) - 1:
                        name = cells[i].rstrip(':').strip()
                        val_str = cells[i + 1].strip()
                        if name and val_str:
                            val = self._safe_float(val_str)
                            if val > 0:
                                result.append({'metric': name, 'name': name, 'value': val})
                        i += 2
            if not result:
                # Fallback: regex on text
                text = (table.get_text() if table else soup.get_text(separator=' '))
                patterns = [
                    (r'Buffer\s+(?:Nowait|Hit)\s+%[:\s]*([\d\.]+)', 'Buffer Hit %'),
                    (r'Library\s+Hit\s+%[:\s]*([\d\.]+)', 'Library Hit %'),
                    (r'In-memory\s+Sort\s+%[:\s]*([\d\.]+)', 'In-memory Sort %'),
                    (r'Soft\s+Parse\s+%[:\s]*([\d\.]+)', 'Soft Parse %'),
                    (r'Execute\s+to\s+Parse\s+%[:\s]*([\d\.]+)', 'Execute to Parse %'),
                    (r'Latch\s+Hit\s+%[:\s]*([\d\.]+)', 'Latch Hit %'),
                    (r'Parse\s+CPU\s+to\s+Parse\s+Elapsd?\s+%[:\s]*([\d\.]+)', 'Parse CPU to Parse Elapsed %'),
                    (r'Non-Parse\s+CPU\s+%[:\s]*([\d\.]+)', 'Non-Parse CPU %'),
                    (r'Redo\s+NoWait\s+%[:\s]*([\d\.]+)', 'Redo NoWait %'),
                ]
                for pat, name in patterns:
                    m = re.search(pat, text, re.IGNORECASE)
                    if m:
                        result.append({'metric': name, 'name': name, 'value': self._safe_float(m.group(1))})
            return result
        except Exception:
            logger.debug("_extract_instance_efficiency failed", exc_info=True)
            return []

    def _extract_os_stats(self, soup: BeautifulSoup) -> list[dict[str, str]]:
        try:
            table = self._find_table_after(soup, r'Operating\s+System\s+Statistics|OS\s+Statistics')
            return self._parse_table(table)
        except Exception:
            logger.debug("_extract_os_stats failed", exc_info=True)
            return []

    def _extract_rac_stats(self, soup: BeautifulSoup) -> list[dict[str, str]]:
        try:
            table = self._find_table_after(soup, r'RAC\s+Statistics|Global\s+Cache')
            return self._parse_table(table)
        except Exception:
            logger.debug("_extract_rac_stats failed", exc_info=True)
            return []

    def _extract_redo_stats(self, soup: BeautifulSoup) -> dict[str, Any]:
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

    def _extract_parse_stats(self, soup: BeautifulSoup) -> dict[str, Any]:
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

    def _extract_segment_stats(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        """Extract hot segments (tables, indexes)."""
        result = []
        try:
            patterns = [
                r'Segments\s+by\s+Logical\s+Reads',
                r'Segments\s+by\s+Physical\s+Reads',
                r'Segments\s+by\s+Buffer\s+Busy\s+Waits',
                r'Segments\s+by\s+Row\s+Lock\s+Waits',
                r'Segments\s+by\s+ITL\s+Waits',
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

    def _extract_advisories(self, soup: BeautifulSoup) -> dict[str, list[dict[str, str]]]:
        """Extract Buffer Pool, PGA, Shared Pool, SGA Target advisories."""
        result = {}
        try:
            advisory_patterns = {
                'Buffer Pool': r'Buffer\s+Pool\s+Advisory',
                'PGA': r'PGA\s+(?:Memory\s+|Aggregate\s+)?(?:Target\s+)?Advisory',
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

    def _extract_enqueue_activity(self, soup: BeautifulSoup) -> list[dict[str, str]]:
        """Extract Enqueue Activity (lock wait breakdown)."""
        try:
            table = self._find_table_after(soup, r'Enqueue\s+Activity')
            return self._parse_table(table)
        except Exception:
            logger.debug("_extract_enqueue_activity failed", exc_info=True)
            return []

    def _extract_latch_detail(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
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

    def _extract_wait_histogram(self, soup: BeautifulSoup) -> list[dict[str, str]]:
        """Extract Wait Event Histogram (time distribution buckets)."""
        try:
            table = self._find_table_after(soup, r'Wait\s+Event\s+Histogram')
            return self._parse_table(table)
        except Exception:
            logger.debug("_extract_wait_histogram failed", exc_info=True)
            return []

    def _extract_undo_stats(self, soup: BeautifulSoup) -> dict[str, Any]:
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

    def _extract_wait_class_summary(self, soup: BeautifulSoup) -> list[dict[str, str]]:
        """Extract Foreground Wait Class summary (if present in AWR)."""
        try:
            table = self._find_table_after(soup, r'(?:Foreground\s+)?Wait\s+Class(?:es)?')
            rows = self._parse_table(table)
            return rows if rows else []
        except Exception:
            logger.debug("_extract_wait_class_summary failed", exc_info=True)
            return []

    def _extract_temp_stats(self, soup: BeautifulSoup) -> dict[str, Any]:
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

    def _extract_time_model(self, soup: BeautifulSoup) -> dict[str, Any]:
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

    def _extract_io_profile(self, soup: BeautifulSoup) -> list[dict[str, str]]:
        """Extract IO Profile summary (Read/Write IOPS, throughput, latency)."""
        try:
            table = self._find_table_after(soup, r'IO\s+Profile|IOProfile|I/O\s+Profile')
            if table:
                return self._parse_table(table)
            return []
        except Exception:
            logger.debug("_extract_io_profile failed", exc_info=True)
            return []

    def _extract_file_io_stats(self, soup: BeautifulSoup) -> list[dict[str, str]]:
        """Extract individual datafile IO statistics."""
        try:
            table = self._find_table_after(soup, r'File\s+IO\s+Stat|Datafile\s+IO|File\s+I/O')
            if table:
                return self._parse_table(table)
            return []
        except Exception:
            logger.debug("_extract_file_io_stats failed", exc_info=True)
            return []

    def _extract_dictionary_cache_stats(self, soup: BeautifulSoup) -> list[dict[str, str]]:
        """Extract Dictionary Cache (row cache) statistics."""
        try:
            table = self._find_table_after(soup, r'Dictionary\s+Cache\s+Stats|Row\s+Cache')
            if table:
                return self._parse_table(table)
            return []
        except Exception:
            logger.debug("_extract_dictionary_cache_stats failed", exc_info=True)
            return []

    def _extract_library_cache_activity(self, soup: BeautifulSoup) -> list[dict[str, str]]:
        """Extract Library Cache Activity statistics."""
        try:
            table = self._find_table_after(soup, r'Library\s+Cache\s+Activity')
            if table:
                return self._parse_table(table)
            return []
        except Exception:
            logger.debug("_extract_library_cache_activity failed", exc_info=True)
            return []

    def _extract_init_parameters(self, soup: BeautifulSoup) -> list[dict[str, str]]:
        """Extract non-default Initialization Parameters."""
        try:
            table = self._find_table_after(soup, r'init\.ora\s+Parameters|Initialization\s+Parameters|init\s+Parameters')
            if table:
                return self._parse_table(table)
            return []
        except Exception:
            logger.debug("_extract_init_parameters failed", exc_info=True)
            return []

    def _extract_background_wait_events(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
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

    def _extract_service_statistics(self, soup: BeautifulSoup) -> list[dict[str, str]]:
        """Extract Service Statistics."""
        try:
            table = self._find_table_after(soup, r'Service\s+Statistics')
            if table:
                return self._parse_table(table)
            return []
        except Exception:
            logger.debug("_extract_service_statistics failed", exc_info=True)
            return []

    def _extract_instance_recovery_stats(self, soup: BeautifulSoup) -> list[dict[str, str]]:
        """Extract Instance Recovery Statistics."""
        try:
            table = self._find_table_after(soup, r'Instance\s+Recovery\s+Stats')
            if table:
                return self._parse_table(table)
            return []
        except Exception:
            logger.debug("_extract_instance_recovery_stats failed", exc_info=True)
            return []

    # -----------------------------------------------------------------
    # NEW PARSER SECTIONS (v3 - 7 missing AWR chapters)
    # -----------------------------------------------------------------

    def _extract_ash_activity(self, soup: BeautifulSoup) -> dict[str, Any]:
        """Extract ASH (Active Session History) - Top Activity and Activity Over Time."""
        result = {}
        try:
            # Top Activity table
            table = self._find_table_after(soup, r'Top\s+Activity|Active\s+Session\s+History')
            if table:
                result['top_activity'] = self._parse_table(table)
            # Activity Over Time table
            table2 = self._find_table_after(soup, r'Activity\s+Over\s+Time')
            if table2:
                result['activity_over_time'] = self._parse_table(table2)
            # Top Sessions from ASH
            table3 = self._find_table_after(soup, r'Top\s+Sessions')
            if table3:
                result['top_sessions'] = self._parse_table(table3)
            # Top Blocking Sessions
            table4 = self._find_table_after(soup, r'Top\s+Blocking\s+Sessions')
            if table4:
                result['top_blocking_sessions'] = self._parse_table(table4)
        except Exception:
            logger.debug("_extract_ash_activity failed", exc_info=True)
        return result

    def _extract_addm_findings(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        """Extract ADDM Findings and Recommendations."""
        try:
            findings = []
            for pattern in [r'ADDM\s+Findings', r'Findings\s+and\s+Recommendations',
                            r'ADDM\s+(?:Task|Report)']:
                table = self._find_table_after(soup, pattern)
                rows = self._parse_table(table)
                for row in rows:
                    row['_source'] = 'ADDM'
                    findings.append(row)
            # Also try text-based extraction for ADDM findings
            if not findings:
                text = soup.get_text()
                # Look for ADDM finding blocks
                addm_blocks = re.findall(
                    r'Finding\s+\d+[:\s]+(.+?)(?=Finding\s+\d+|Recommendation|$)',
                    text, re.IGNORECASE | re.DOTALL
                )
                for i, block in enumerate(addm_blocks[:10]):
                    findings.append({
                        'finding_id': i + 1,
                        'description': block.strip()[:500],
                        '_source': 'ADDM_text'
                    })
            return findings
        except Exception:
            logger.debug("_extract_addm_findings failed", exc_info=True)
            return []

    def _extract_sql_plan_changes(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        """Extract SQL Plan Changes / Plan Hash Value Changed."""
        try:
            result = []
            for pattern in [r'Plan\s+Hash\s+Value\s+Changed',
                            r'SQL\s+ordered\s+by.*Plan',
                            r'Plan\s+Change']:
                table = self._find_table_after(soup, pattern)
                rows = self._parse_table(table)
                for row in rows:
                    row['_source'] = 'plan_change'
                    result.append(row)
            return result
        except Exception:
            logger.debug("_extract_sql_plan_changes failed", exc_info=True)
            return []

    def _extract_host_instance_cpu(self, soup: BeautifulSoup) -> dict[str, Any]:
        """Extract Host CPU and Instance CPU utilization breakdown."""
        result = {}
        try:
            # Host CPU
            table = self._find_table_after(soup, r'Host\s+CPU')
            if table:
                rows = self._parse_table(table)
                if rows:
                    result['host_cpu'] = rows
                # Also extract from text
                text = table.get_text()
                for pat, key in [
                    (r'%\s*User[:\s]*([\d\.]+)', 'user_pct'),
                    (r'%\s*System[:\s]*([\d\.]+)', 'system_pct'),
                    (r'%\s*WIO[:\s]*([\d\.]+)', 'wio_pct'),
                    (r'%\s*Idle[:\s]*([\d\.]+)', 'idle_pct'),
                    (r'%\s*Busy[:\s]*([\d\.]+)', 'busy_pct'),
                    (r'CPUs[:\s]*(\d+)', 'cpus'),
                    (r'Cores[:\s]*(\d+)', 'cores'),
                    (r'Sockets[:\s]*(\d+)', 'sockets'),
                ]:
                    m = re.search(pat, text, re.IGNORECASE)
                    if m:
                        result[key] = self._safe_float(m.group(1))
            # Instance CPU
            table2 = self._find_table_after(soup, r'Instance\s+CPU')
            if table2:
                rows2 = self._parse_table(table2)
                if rows2:
                    result['instance_cpu'] = rows2
                text2 = table2.get_text()
                for pat, key in [
                    (r'%\s*Total\s+CPU[:\s]*([\d\.]+)', 'instance_total_cpu_pct'),
                    (r'%\s*Busy\s+CPU[:\s]*([\d\.]+)', 'instance_busy_cpu_pct'),
                    (r'DB\s+Time.*?%[:\s]*([\d\.]+)', 'db_time_pct_of_cpu'),
                ]:
                    m = re.search(pat, text2, re.IGNORECASE)
                    if m:
                        result[key] = self._safe_float(m.group(1))
        except Exception:
            logger.debug("_extract_host_instance_cpu failed", exc_info=True)
        return result

    def _extract_cache_sizes(self, soup: BeautifulSoup) -> dict[str, Any]:
        """Extract Cache Sizes at snapshot time."""
        result = {}
        try:
            table = self._find_table_after(soup, r'Cache\s+Sizes')
            if table:
                rows = self._parse_table(table)
                if rows:
                    result['raw'] = rows
                # Also extract specific cache sizes from text
                text = table.get_text()
                for pat, key in [
                    (r'Buffer\s+Cache[:\s]*([\d\.,]+)\s*(MB|GB|M|G)', 'buffer_cache'),
                    (r'Shared\s+Pool\s+Size[:\s]*([\d\.,]+)\s*(MB|GB|M|G)', 'shared_pool'),
                    (r'Large\s+Pool\s+Size[:\s]*([\d\.,]+)\s*(MB|GB|M|G)', 'large_pool'),
                    (r'Java\s+Pool\s+Size[:\s]*([\d\.,]+)\s*(MB|GB|M|G)', 'java_pool'),
                    (r'Streams\s+Pool\s+Size[:\s]*([\d\.,]+)\s*(MB|GB|M|G)', 'streams_pool'),
                    (r'(?:Std\s+Block\s+Size|Standard\s+Block)[:\s]*([\d\.,]+)\s*(K|KB)', 'std_block_size'),
                ]:
                    m = re.search(pat, text, re.IGNORECASE)
                    if m:
                        val = self._safe_float(m.group(1))
                        unit = m.group(2).upper()
                        if unit.startswith('G'):
                            val *= 1024  # Normalize to MB
                        result[key + '_mb'] = val
        except Exception:
            logger.debug("_extract_cache_sizes failed", exc_info=True)
        return result

    def _extract_segment_row_lock_itl(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        """Extract Segments by Row Lock Waits and ITL Waits."""
        result = []
        try:
            for pattern in [r'Segments?\s+by\s+Row\s+Lock\s+Waits',
                            r'Segments?\s+by\s+ITL\s+Waits']:
                table = self._find_table_after(soup, pattern)
                rows = self._parse_table(table)
                for row in rows:
                    row['_source'] = pattern.replace(r'\s+', ' ').replace('\\s+', ' ')
                    result.append(row)
        except Exception:
            logger.debug("_extract_segment_row_lock_itl failed", exc_info=True)
        return result

    def _safe_float(self, val: Any, default: float = 0.0) -> float:
        return _safe_float(val, default)


