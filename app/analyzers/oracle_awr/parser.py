import os
import re
from typing import Any

from bs4 import BeautifulSoup


SECTION_PATTERNS = {
    "load_profile": r"Load Profile",
    "time_model": r"Time Model Statistics",
    "foreground_wait_class": r"Foreground Wait Class",
    "wait_classes": r"Wait Classes",
    "instance_efficiency": r"Instance Efficiency",
    "top_sql_elapsed": r"SQL ordered by Elapsed Time",
    "top_sql_cpu": r"SQL ordered by CPU Time",
    "top_sql_gets": r"SQL ordered by Gets",
    "top_sql_reads": r"SQL ordered by Reads",
    "io_stats": r"(Tablespace IO Stats|Tablespace IO)",
    "os_stats": r"Operating System Statistics|OS Statistics",
    "memory_stats": r"Memory Statistics|SGA Target Advisory|PGA Memory Advisory",
    "segments_logical_reads": r"Segments by Logical Reads",
    "segments_physical_reads": r"Segments by Physical Reads",
    "segments_table_scans": r"Segments by Table Scans",
    "latch_activity": r"Latch Activity",
    "enqueue_activity": r"Enqueue Activity",
    "pga_advisory": r"PGA Aggr Target Stats",
    "sga_advisory": r"SGA Target Advisory",
    "instance_activity": r"Key Instance Activity Stats",
    "sql_plan_statistics": r"SQL Plan Statistics",
    "sql_plans_by_elapsed": r"SQL Plans sorted by Elapsed",
    "execution_plan": r"Execution Plan|Explain Plan|SQL Execution Plan",
    "plan_hash_value": r"Plan Hash Value|SQL Plan Baseline",
    "sql_workarea": r"SQL Work Area|Workarea Memory",
}

_TOP_EVENTS_PATTERNS = [
    r"Foreground Events by Total Wait Time",
    r"Top \d+ Foreground Events",
    r"Foreground Wait Events",
    r"Top \d+ Timed",
    r"Top Timed",
    r"Top Events",
]


def parse_awr(input_data) -> dict[str, Any]:
    html = _decode_input(input_data)
    soup = BeautifulSoup(html, "lxml")

    top_events_rows = _find_events_table(soup)
    wait_classes = _wait_classes(_section_rows(soup, SECTION_PATTERNS["wait_classes"]))
    foreground_wc = _foreground_wait_class(_section_rows(soup, SECTION_PATTERNS["foreground_wait_class"]))

    top_events = _top_events(top_events_rows)
    top_events = _enrich_events_wait_class(top_events, wait_classes, foreground_wc)

    parsed = {
        "db_info": _extract_db_info(soup),
        "snapshot": _extract_snapshot(soup),
        "load_profile": _rows_to_mapping(_section_rows(soup, SECTION_PATTERNS["load_profile"])),
        "time_model": _time_model(_section_rows(soup, SECTION_PATTERNS["time_model"])),
        "top_events": top_events,
        "wait_classes": wait_classes,
        "foreground_wait_class": foreground_wc,
        "instance_efficiency": _rows_to_mapping(_section_rows(soup, SECTION_PATTERNS["instance_efficiency"])),
        "top_sql_elapsed": _top_sql(_section_rows(soup, SECTION_PATTERNS["top_sql_elapsed"])),
        "top_sql_cpu": _top_sql(_section_rows(soup, SECTION_PATTERNS["top_sql_cpu"])),
        "top_sql_gets": _top_sql(_section_rows(soup, SECTION_PATTERNS["top_sql_gets"])),
        "top_sql_reads": _top_sql(_section_rows(soup, SECTION_PATTERNS["top_sql_reads"])),
        "io_stats": _section_rows(soup, SECTION_PATTERNS["io_stats"]),
        "os_stats": _rows_to_mapping(_section_rows(soup, SECTION_PATTERNS["os_stats"])),
        "memory_stats": _rows_to_mapping(_section_rows(soup, SECTION_PATTERNS["memory_stats"])),
        "segments_logical_reads": _segment_statistics(_section_rows(soup, SECTION_PATTERNS["segments_logical_reads"])),
        "segments_physical_reads": _segment_statistics(_section_rows(soup, SECTION_PATTERNS["segments_physical_reads"])),
        "segments_table_scans": _segment_statistics(_section_rows(soup, SECTION_PATTERNS["segments_table_scans"])),
        "latch_activity": _latch_activity(_section_rows(soup, SECTION_PATTERNS["latch_activity"])),
        "enqueue_activity": _enqueue_activity(_section_rows(soup, SECTION_PATTERNS["enqueue_activity"])),
        "pga_advisory": _section_rows(soup, SECTION_PATTERNS["pga_advisory"]),
        "sga_advisory": _section_rows(soup, SECTION_PATTERNS["sga_advisory"]),
        "instance_activity": _instance_activity(_section_rows(soup, SECTION_PATTERNS["instance_activity"])),
        "sql_plan_statistics": _sql_plan_statistics(soup),
        "execution_plans": _parse_execution_plans(soup),
        "sql_plan_baselines": _parse_plan_baselines(soup),
    }

    if not parsed["wait_classes"]:
        parsed["wait_classes"] = _wait_classes_from_events(parsed["top_events"])

    parsed["_parse_success"] = _has_diagnostic_content(parsed)
    if not parsed["_parse_success"]:
        parsed["_parse_error"] = "未解析出有效 AWR 诊断内容，请确认上传的是 Oracle AWR HTML 原始报告，而不是损坏文件、同步盘占位文件或加密缓存文件。"

    return parsed


def _decode_input(input_data) -> str:
    if isinstance(input_data, (str, os.PathLike)):
        path = str(input_data)
        if path.lower().endswith((".html", ".htm")) and os.path.isfile(path):
            with open(path, "rb") as f:
                return _decode_input(f.read())
    if isinstance(input_data, bytes):
        for encoding in ("utf-8", "gb18030", "latin-1", "gbk", "gb2312", "big5", "utf-16"):
            try:
                decoded = input_data.decode(encoding)
                if "<html" in decoded.lower() or "<table" in decoded.lower() or "<!doctype" in decoded.lower():
                    return decoded
            except (UnicodeDecodeError, LookupError):
                continue
        return input_data.decode("utf-8", errors="ignore")
    text = str(input_data or "")
    # Handle text format AWR (SQL*Plus output)
    if text and "<" not in text and "table" not in text.lower():
        # May be plain text AWR — wrap in minimal HTML
        if any(marker in text for marker in ["DB Time", "Elapsed", "Load Profile", "Top Timed"]):
            text = _wrap_text_awr(text)
    return text


def _wrap_text_awr(text):
    """Wrap plain-text AWR (SQL*Plus output) into parseable HTML tables."""
    lines = text.split("\n")
    html_parts = ["<html><body>"]
    current_section = ""
    in_table = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_table:
                html_parts.append("</table>")
                in_table = False
            continue

        # Detect section headers
        if stripped.startswith("---") or stripped.startswith("==="):
            if in_table:
                html_parts.append("</table>")
                in_table = False
            continue

        # Detect pipe-delimited table rows (common in text AWR)
        if "|" in stripped:
            cells = [c.strip() for c in stripped.split("|") if c.strip()]
            if len(cells) >= 2:
                if not in_table:
                    # Check if this is a header row
                    is_header = any(kw in stripped.lower() for kw in ["event", "class", "sql_id", "name", "%db time", "time(s)", "per second", "per sec"])
                    html_parts.append(f'<table summary="{current_section}"><tr>')
                    for cell in cells:
                        tag = "th" if is_header else "td"
                        html_parts.append(f"<{tag}>{cell}</{tag}>")
                    html_parts.append("</tr>")
                    in_table = True
                else:
                    html_parts.append("<tr>")
                    for cell in cells:
                        html_parts.append(f"<td>{cell}</td>")
                    html_parts.append("</tr>")
                    in_table = True
            continue

        # Detect space-delimited table rows (SQL*Plus output)
        # Must have at least 2 columns separated by 2+ spaces
        if re.match(r'\S.*\s{2,}\S', stripped) and not stripped.startswith("-"):
            # Skip separator lines and non-data lines
            if all(c in "-=" for c in stripped.replace(" ", "")):
                continue
            cells = [c.strip() for c in re.split(r'\s{2,}', stripped) if c.strip()]
            if len(cells) >= 2:
                if not in_table:
                    is_header = any(kw in stripped.lower() for kw in ["event", "class", "sql_id", "name", "%db", "time(s)", "per second", "elapsed", "load profile", "snap"])
                    html_parts.append(f'<table summary="{current_section}"><tr>')
                    for cell in cells:
                        tag = "th" if is_header else "td"
                        html_parts.append(f"<{tag}>{cell}</{tag}>")
                    html_parts.append("</tr>")
                    if not is_header:
                        in_table = True
                else:
                    html_parts.append("<tr>")
                    for cell in cells:
                        html_parts.append(f"<td>{cell}</td>")
                    html_parts.append("</tr>")
            continue

        # Detect section names
        if stripped and len(stripped) > 5 and not stripped[0].isdigit():
            if any(kw in stripped for kw in ["Load Profile", "Time Model", "Wait Class", "Top ", "Instance Efficiency",
                                               "SQL ordered", "Segment", "Latch", "Enqueue", "PGA", "SGA",
                                               "Operating System", "Memory", "IO Stats", "Key Instance",
                                               "Foreground"]):
                current_section = stripped
                if in_table:
                    html_parts.append("</table>")
                    in_table = False
                html_parts.append(f"<h3>{stripped}</h3>")

    if in_table:
        html_parts.append("</table>")
    html_parts.append("</body></html>")
    return "\n".join(html_parts)


def _extract_db_info(soup: BeautifulSoup) -> dict[str, str]:
    info = {}
    title = soup.find("title")
    text = title.get_text(" ", strip=True) if title else soup.get_text(" ", strip=True)[:500]
    pairs = {
        "db_name": r"DB:\s*([^,\s]+)",
        "instance_name": r"Inst:\s*([^,\s]+)",
        "snap_range": r"Snaps:\s*([^,\s]+)",
    }
    for key, pattern in pairs.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            info[key] = match.group(1)
    return info


def _extract_snapshot(soup: BeautifulSoup) -> dict[str, Any]:
    rows = _section_rows(soup, r"Snap Id|Snapshot")
    return {"rows": rows[:5]} if rows else {}


def _section_rows(soup: BeautifulSoup, pattern: str) -> list[dict[str, str]]:
    table = _find_table(soup, pattern)
    return _parse_table(table)


def _find_table(soup: BeautifulSoup, pattern: str):
    regex = re.compile(pattern, re.IGNORECASE)

    # Search in table summaries
    for table in soup.find_all("table"):
        summary = table.get("summary") or ""
        if regex.search(summary):
            return table

    # Search in headers (h1-h4, b, p, span)
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "b", "p", "span"]):
        if tag.find_parent("table"):
            continue
        text = tag.get_text(" ", strip=True)
        if text and regex.search(text):
            table = tag.find_next("table")
            if table:
                return table

    # Search in text nodes
    for text_node in soup.find_all(string=regex):
        parent = text_node.parent
        if parent and (parent.name in {"a", "td", "th"} or parent.find_parent("table")):
            continue
        table = text_node.find_next("table")
        if table:
            return table

    # Fallback: search in anchor names and id attributes
    for anchor in soup.find_all("a", attrs={"name": regex}):
        table = anchor.find_next("table")
        if table:
            return table

    return None


def _find_events_table(soup: BeautifulSoup) -> list[dict[str, str]]:
    """Find the best events table rows, preferring those with Wait Class column."""
    for pattern in _TOP_EVENTS_PATTERNS:
        table = _find_table(soup, pattern)
        if table is None:
            continue
        rows = _parse_table(table)
        if not rows:
            continue
        # Check if any row has wait_class or wait class related column
        has_wait_class = any(
            "wait_class" in row or "wait class" in " ".join(row.keys()).lower()
            for row in rows[:3]
        )
        if has_wait_class:
            return rows
    # Fallback: try each pattern again without wait_class check
    for pattern in _TOP_EVENTS_PATTERNS:
        table = _find_table(soup, pattern)
        if table is not None:
            rows = _parse_table(table)
            if rows:
                return rows
    return []


def _parse_table(table) -> list[dict[str, str]]:
    if table is None:
        return []

    rows = table.find_all("tr")
    if not rows:
        return []

    header_index = _find_header_index(rows)
    headers = [_clean(cell.get_text(" ", strip=True)) for cell in rows[header_index].find_all(["th", "td"])]
    headers = [_normalize_header(header, index) for index, header in enumerate(headers)]
    parsed = []

    for row in rows[header_index + 1:]:
        cells = [_clean(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"])]
        if not cells or all(not cell for cell in cells):
            continue
        item = {}
        for index, value in enumerate(cells):
            header = headers[index] if index < len(headers) else f"col_{index}"
            item[header] = value
        parsed.append(item)

    return parsed


def _find_header_index(rows) -> int:
    best_index = 0
    best_score = -1
    for index, row in enumerate(rows[:4]):
        cells = row.find_all(["th", "td"])
        text = " ".join(cell.get_text(" ", strip=True) for cell in cells).lower()
        score = len(row.find_all("th")) * 3 + len(cells)
        if any(token in text for token in ("event", "wait", "sql", "db time", "per second", "%")):
            score += 5
        if score > best_score:
            best_score = score
            best_index = index
    return best_index


def _normalize_header(header: str, index: int) -> str:
    normalized = re.sub(r"\s+", "_", header.strip().lower())
    normalized = normalized.replace("%", "pct").replace("/", "_per_")
    normalized = re.sub(r"[^a-z0-9_]+", "", normalized).strip("_")
    return normalized or f"col_{index}"


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _rows_to_mapping(rows: list[dict[str, str]]) -> dict[str, Any]:
    mapping = {}
    for row in rows:
        values = list(row.values())
        if len(values) >= 2:
            mapping[values[0]] = values[1] if len(values) == 2 else row
    return mapping


def _first_value(row: dict[str, str], candidates: list[str], default: str = "") -> str:
    normalized_items = [(key.lower(), value) for key, value in row.items()]
    for candidate in candidates:
        for normalized, value in normalized_items:
            if candidate == normalized:
                return value
    for key, value in row.items():
        normalized = key.lower()
        for candidate in candidates:
            if candidate in normalized:
                return value
    return default


def _top_events(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    events = []
    for row in rows:
        event = _first_value(row, ["event"], "")
        if not event:
            values = list(row.values())
            event = values[0] if values else ""
        if not event:
            continue
        events.append(
            {
                "event": event,
                "wait_class": _first_value(row, ["wait_class", "wait class"], ""),
                "waits": _first_value(row, ["waits"], ""),
                "time_s": _first_value(row, ["total_wait_time_s", "time_s", "time_secs", "time"], ""),
                "avg_wait_ms": _first_value(row, ["avg_wait", "avg_ms"], ""),
                "pct_db_time": _first_value(row, ["pct_db_time", "db_time"], ""),
            }
        )
    return events


def _wait_classes(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    classes = []
    for row in rows:
        wait_class = _first_value(row, ["wait_class", "class"], "")
        if not wait_class:
            values = list(row.values())
            wait_class = values[0] if values else ""
        if not wait_class:
            continue
        classes.append(
            {
                "wait_class": wait_class,
                "waits": _first_value(row, ["waits"], ""),
                "time_s": _first_value(row, ["time_s", "time_secs", "time"], ""),
                "pct_db_time": _first_value(row, ["pct_db_time", "db_time"], ""),
            }
        )
    return classes


def _foreground_wait_class(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Parse Foreground Wait Class table (Statistic Name, Time (s), % of DB Time)."""
    classes = []
    for row in rows:
        name = _first_value(row, ["wait_class", "statistic_name", "name", "class"], "")
        if not name:
            values = list(row.values())
            name = values[0] if values else ""
        if not name:
            continue
        classes.append(
            {
                "wait_class": name,
                "time_s": _first_value(row, ["time_s", "time", "time_secs"], ""),
                "pct_db_time": _first_value(row, ["pct_db_time", "pct_of_db_time", "db_time"], ""),
            }
        )
    return classes


def _enrich_events_wait_class(events: list[dict[str, Any]], wait_classes: list[dict[str, Any]], foreground_wc: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Enrich events with wait_class from wait class tables when missing."""
    # Use a built-in mapping for common Oracle wait events
    builtin_map = {
        "log file sync": "Commit",
        "log file sequential read": "System I/O",
        "log file parallel write": "System I/O",
        "log file switch": "Configuration",
        "log file switch (checkpoint incomplete)": "Configuration",
        "log buffer space": "Commit",
        "db file sequential read": "User I/O",
        "db file scattered read": "User I/O",
        "direct path read": "User I/O",
        "direct path read temp": "User I/O",
        "direct path write": "User I/O",
        "direct path write temp": "User I/O",
        "db file parallel read": "User I/O",
        "control file sequential read": "System I/O",
        "control file parallel write": "System I/O",
        "db cpu": "DB CPU",
        "db file parallel write": "System I/O",
        "buffer busy waits": "Concurrency",
        "read by other session": "Concurrency",
        "latch: shared pool": "Concurrency",
        "latch: cache buffers chains": "Concurrency",
        "latch: row cache objects": "Concurrency",
        "library cache": "Concurrency",
        "library cache lock": "Concurrency",
        "library cache load lock": "Concurrency",
        "cursor: pin s wait on X": "Concurrency",
        "cursor: pin s": "Concurrency",
        "cursor: pin x": "Concurrency",
        "cursor: mutex s": "Concurrency",
        "cursor: mutex x": "Concurrency",
        "enq: tx - row lock contention": "Application",
        "enq: tx - index contention": "Concurrency",
        "enq: tx - allocate itl entry": "Concurrency",
        "enq: tm - contention": "Application",
        "enq: hw - contention": "Configuration",
        "enq: sq - contention": "Configuration",
        "enq: cf - contention": "Configuration",
        "enq: ko - fast object checkpoint": "Application",
        "enq: ro - fast object reuse": "Application",
        "enq: mn - contention": "Application",
        "enq: fb - contention": "Configuration",
        "enq: cr - block range reuse ckpt": "Configuration",
        "sql*net message from client": "Idle",
        "sql*net message to client": "Network",
        "sql*net message from dblink": "Network",
        "sql*net message to dblink": "Network",
        "sql*net more data from client": "Network",
        "sql*net more data to client": "Network",
        "sql*net more data from dblink": "Network",
        "sql*net more data to dblink": "Network",
        "sql*net break/reset to client": "Network",
        "tcp socket (kgas)": "Network",
        "gc buffer busy": "Cluster",
        "gc cr request": "Cluster",
        "gc current request": "Cluster",
        "disk file operations i/o": "User I/O",
        "undo segment extension": "Configuration",
        "sorts (memory)": "DB CPU",
        "sorts (disk)": "User I/O",
    }

    for event in events:
        if event.get("wait_class"):
            continue
        event_name = str(event.get("event", "")).lower()
        if event_name in builtin_map:
            event["wait_class"] = builtin_map[event_name]
        else:
            # Try partial match
            for pattern, cls in builtin_map.items():
                if pattern in event_name:
                    event["wait_class"] = cls
                    break
    return events


def _wait_classes_from_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    totals = {}
    for event in events:
        wait_class = event.get("wait_class")
        if not wait_class:
            continue
        totals[wait_class] = totals.get(wait_class, 0) + _safe_float(event.get("pct_db_time"))
    return [{"wait_class": name, "pct_db_time": value} for name, value in totals.items()]


def _time_model(rows: list[dict[str, str]]) -> dict[str, Any]:
    model = {}
    for row in rows:
        stat = _first_value(row, ["stat_name", "statistic", "name"], "")
        if not stat:
            values = list(row.values())
            stat = values[0] if values else ""
        if not stat:
            continue
        model[stat] = {
            "time_s": _first_value(row, ["time_s", "seconds"], ""),
            "pct_db_time": _first_value(row, ["pct_db_time", "db_time"], ""),
        }
    return model


def _top_sql(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    sql_rows = []
    for row in rows:
        sql_id = _first_value(row, ["sql_id", "sqlid"], "")
        if not sql_id:
            continue
        sql_rows.append(
            {
                "sql_id": sql_id,
                "elapsed_time": _first_value(row, ["elapsed", "elapsed_time", "elapsed_time_s"], ""),
                "cpu_time": _first_value(row, ["cpu", "cpu_time", "cpu_time_s"], ""),
                "buffer_gets": _first_value(row, ["buffer_gets", "gets", "buffer_gets_s"], ""),
                "physical_reads": _first_value(row, ["physical_reads", "reads", "physical_reads_s"], ""),
                "executions": _first_value(row, ["executions", "execs"], ""),
                "rows_processed": _first_value(row, ["rows_processed", "rows"], ""),
                "sql_text": _first_value(row, ["sql_text", "text"], ""),
                "pct_total": _first_value(row, ["pcttotal", "pct_total"], ""),
                "pct_cpu": _first_value(row, ["pctcpu", "pct_cpu"], ""),
                "pct_io": _first_value(row, ["pctio", "pct_io"], ""),
                "raw": row,
            }
        )
    return sql_rows


def _segment_statistics(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Parse Segment Statistics tables by column header names instead of position."""
    segments = []
    if not rows:
        return segments
    # Detect column names from first row keys
    sample_keys = list(rows[0].keys()) if rows else []

    def find_col(keys, candidates):
        for c in candidates:
            for k in keys:
                if c in k:
                    return k
        return None

    owner_k = find_col(sample_keys, ["owner"])
    ts_k = find_col(sample_keys, ["tablespace"])
    obj_k = find_col(sample_keys, ["object_name", "object"])
    sub_k = find_col(sample_keys, ["subobject"])
    type_k = find_col(sample_keys, ["obj_type", "objtype", "type"])
    metric_k = find_col(sample_keys, ["logical_reads", "physical_reads", "physical_read_requests",
                                       "unoptimized_reads", "optimized_reads", "direct_physical_reads",
                                       "physical_writes", "physical_write_requests", "direct_physical_writes",
                                       "table_scans", "segment"])
    pct_k = find_col(sample_keys, ["pcttotal", "pct_total", "pct"])

    for row in rows:
        segments.append({
            "owner": row.get(owner_k, "") if owner_k else "",
            "tablespace": row.get(ts_k, "") if ts_k else "",
            "object_name": row.get(obj_k, "") if obj_k else "",
            "subobject_name": row.get(sub_k, "") if sub_k else "",
            "obj_type": row.get(type_k, "") if type_k else "",
            "metric_value": row.get(metric_k, "") if metric_k else "",
            "pct_total": row.get(pct_k, "") if pct_k else "",
        })
    return segments


def _latch_activity(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Parse Latch Activity table, filtering out noise."""
    latches = []
    for row in rows:
        latch_name = _first_value(row, ["latch_name", "name"], "")
        if not latch_name:
            values = list(row.values())
            latch_name = values[0] if values else ""
        if not latch_name:
            continue
        miss_pct = _safe_float(_first_value(row, ["pct_get_miss", "pct get miss"], "0"))
        wait_time = _safe_float(_first_value(row, ["wait_time_s", "wait time_s", "wait time (s)"], "0"))
        if miss_pct < 0.5 and wait_time < 0.5:
            continue
        latches.append({
            "latch_name": latch_name,
            "get_requests": _first_value(row, ["get_requests", "get requests"], ""),
            "pct_get_miss": _first_value(row, ["pct_get_miss", "pct get miss"], ""),
            "avg_slps_per_miss": _first_value(row, ["avg_slps_per_miss", "avg slps _per_miss"], ""),
            "wait_time_s": _first_value(row, ["wait_time_s", "wait time_s", "wait time (s)"], ""),
            "nowait_requests": _first_value(row, ["nowait_requests", "nowait requests"], ""),
            "pct_nowait_miss": _first_value(row, ["pct_nowait_miss", "pct nowait miss"], ""),
        })
    return latches


def _enqueue_activity(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Parse Enqueue Activity table."""
    enqueues = []
    for row in rows:
        eq_type = _first_value(row, ["enqueue_type_request_reason", "class", "type"], "")
        if not eq_type:
            values = list(row.values())
            eq_type = values[0] if values else ""
        if not eq_type:
            continue
        enqueues.append({
            "enqueue_type": eq_type,
            "requests": _first_value(row, ["requests"], ""),
            "succ_gets": _first_value(row, ["succ_gets", "succ gets"], ""),
            "failed_gets": _first_value(row, ["failed_gets", "failed gets"], ""),
            "waits": _first_value(row, ["waits"], ""),
            "wt_time_s": _first_value(row, ["wt_time_s", "wt time_s", "wt time (s)"], ""),
            "av_wt_time_ms": _first_value(row, ["av_wt_timems", "av wt timems", "av_wt_timems"], ""),
        })
    return enqueues


def _instance_activity(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    """Parse Instance Activity Stats into a name -> {total, per_second, per_trans} mapping."""
    activity = {}
    for row in rows:
        name = _first_value(row, ["statistic_name", "statistic", "name"], "")
        if not name:
            values = list(row.values())
            name = values[0] if values else ""
        if not name:
            continue
        activity[name.lower()] = {
            "total": _first_value(row, ["total", "value"], ""),
            "per_second": _first_value(row, ["per_second", "per second", "persec"], ""),
            "per_trans": _first_value(row, ["per_trans", "per trans", "pertran"], ""),
        }
    return activity


def _safe_float(value) -> float:
    if value is None:
        return 0
    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except Exception:
        return 0


def _has_diagnostic_content(parsed: dict[str, Any]) -> bool:
    return bool(
        parsed.get("top_events")
        or parsed.get("wait_classes")
        or parsed.get("time_model")
        or parsed.get("top_sql_elapsed")
        or parsed.get("load_profile")
    )


def _sql_plan_statistics(soup: BeautifulSoup) -> dict[str, list[dict[str, Any]]]:
    """Parse SQL Plan Statistics section. Returns dict keyed by sql_id."""
    plans = {}

    # Try multiple patterns for plan statistics tables
    plan_patterns = [
        r"SQL Plan Statistics",
        r"SQL Plans sorted by Elapsed",
        r"Plan Statistics",
    ]

    for pattern in plan_patterns:
        tables = []
        regex = re.compile(pattern, re.IGNORECASE)
        for table in soup.find_all("table"):
            summary = table.get("summary") or ""
            if regex.search(summary):
                tables.append(table)
            else:
                # Check preceding headers
                prev = table.find_previous(["h1", "h2", "h3", "h4", "b", "p"])
                if prev and regex.search(prev.get_text("", strip=True)):
                    tables.append(table)

        for table in tables:
            rows = _parse_table(table)
            if not rows:
                continue

            for row in rows:
                sql_id = _first_value(row, ["sql_id", "sqlid", "sql id"], "")
                if not sql_id:
                    continue

                plan_hash = _first_value(row, ["plan_hash_value", "plan_hash", "plan hash"], "")
                operation = _first_value(row, ["operation", "operation_name", "op"], "")
                object_name = _first_value(row, ["object_name", "object", "name"], "")
                cost = _first_value(row, ["cost", "optimizer_cost"], "")
                cardinality = _first_value(row, ["cardinality", "card", "rows"], "")
                bytes_val = _first_value(row, ["bytes"], "")
                time_val = _first_value(row, ["time", "elapsed"], "")
                cpu_cost = _first_value(row, ["cpu_cost", "cpu cost"], "")
                io_cost = _first_value(row, ["io_cost", "io cost"], "")

                if sql_id not in plans:
                    plans[sql_id] = {
                        "sql_id": sql_id,
                        "plan_hash_value": plan_hash,
                        "operations": [],
                    }

                if operation:
                    plans[sql_id]["operations"].append({
                        "operation": operation,
                        "object_name": object_name,
                        "cost": cost,
                        "cardinality": cardinality,
                        "bytes": bytes_val,
                        "time": time_val,
                        "cpu_cost": cpu_cost,
                        "io_cost": io_cost,
                    })

                # Update plan_hash if found
                if plan_hash and not plans[sql_id]["plan_hash_value"]:
                    plans[sql_id]["plan_hash_value"] = plan_hash

    # Also extract SQL text from "Complete List of SQL Text" if available
    _enrich_sql_text(soup, plans)

    return plans


def _enrich_sql_text(soup, plans):
    """Try to extract full SQL text for planned SQL statements."""
    sql_text_pattern = re.compile(r"Complete List of SQL Text|SQL Text", re.IGNORECASE)
    for table in soup.find_all("table"):
        summary = table.get("summary") or ""
        prev = table.find_previous(["h1", "h2", "h3", "h4", "b", "p"])
        header_text = prev.get_text("", strip=True) if prev else ""
        if sql_text_pattern.search(summary) or sql_text_pattern.search(header_text):
            rows = _parse_table(table)
            for row in rows:
                sql_id = _first_value(row, ["sql_id", "sqlid"], "")
                text = _first_value(row, ["sql_text", "sql_text", "text"], "")
                if sql_id and text and sql_id in plans:
                    plans[sql_id]["full_sql_text"] = text[:2000]
            break


def _parse_execution_plans(soup: BeautifulSoup) -> dict[str, list[dict[str, Any]]]:
    """Parse hierarchical execution plans from AWR reports.

    Handles 'Execution Plan', 'Explain Plan', and indented plan tree tables.
    Returns dict keyed by sql_id -> list of plan nodes with depth info.
    """
    all_plans = {}

    # Search for execution plan sections
    ep_patterns = [
        r"Execution Plan",
        r"Explain Plan",
        r"SQL Execution Plan",
    ]

    for pattern in ep_patterns:
        regex = re.compile(pattern, re.IGNORECASE)
        tables = []
        for table in soup.find_all("table"):
            summary = table.get("summary") or ""
            if regex.search(summary):
                tables.append(table)
            else:
                prev = table.find_previous(["h1", "h2", "h3", "h4", "b", "p"])
                if prev and regex.search(prev.get_text("", strip=True)):
                    tables.append(table)

        for table in tables:
            rows = _parse_table(table)
            if not rows:
                continue

            # Try to determine sql_id from preceding context or table data
            sql_id = ""
            for row in rows[:3]:
                sql_id = _first_value(row, ["sql_id", "sqlid"], "")
                if sql_id:
                    break
            if not sql_id:
                # Use hash of first few rows as a pseudo-id
                sql_id = f"_plan_{id(table) & 0xFFFF:04x}"

            plan_nodes = _extract_plan_nodes(rows)
            if plan_nodes:
                if sql_id not in all_plans:
                    all_plans[sql_id] = []
                all_plans[sql_id].extend(plan_nodes)

    # Also search for plan tables by summary containing "plan" or "explain"
    for table in soup.find_all("table"):
        summary = (table.get("summary") or "").lower()
        if not any(kw in summary for kw in ("plan", "explain", "execut")):
            continue
        rows = _parse_table(table)
        if not rows:
            continue

        # Check if rows look like execution plan data
        sample_keys = set()
        for row in rows[:3]:
            sample_keys.update(k.lower() for k in row.keys())

        plan_indicators = {"operation", "options", "object_name", "cost", "cardinality", "id"}
        if not (plan_indicators & sample_keys):
            continue

        sql_id = ""
        for row in rows[:3]:
            sql_id = _first_value(row, ["sql_id", "sqlid"], "")
            if sql_id:
                break
        if not sql_id:
            sql_id = f"_plan_{id(table) & 0xFFFF:04x}"

        plan_nodes = _extract_plan_nodes(rows)
        if plan_nodes:
            if sql_id not in all_plans:
                all_plans[sql_id] = []
            all_plans[sql_id].extend(plan_nodes)

    return all_plans


def _extract_plan_nodes(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Extract plan nodes from table rows, detecting depth from indentation."""
    nodes = []
    for row in rows:
        operation = _first_value(row, ["operation", "operation_name", "op", "name"], "")
        if not operation:
            values = list(row.values())
            operation = values[0] if values else ""

        # Skip header-like or empty rows
        if not operation or operation.lower() in ("operation", "id", "---", "optimizer"):
            continue

        # Detect depth from leading whitespace/indentation
        depth = 0
        raw_op = operation
        leading_spaces = len(operation) - len(operation.lstrip())
        if leading_spaces > 0:
            depth = leading_spaces // 2

        node = {
            "id": _first_value(row, ["id"], ""),
            "operation": raw_op.strip(),
            "options": _first_value(row, ["options", "opt"], ""),
            "object_owner": _first_value(row, ["object_owner", "owner"], ""),
            "object_name": _first_value(row, ["object_name", "object", "name"], ""),
            "object_type": _first_value(row, ["object_type", "type"], ""),
            "cost": _first_value(row, ["cost", "optimizer_cost"], ""),
            "cardinality": _first_value(row, ["cardinality", "card", "rows", "est_rows"], ""),
            "bytes": _first_value(row, ["bytes"], ""),
            "time": _first_value(row, ["time", "elapsed"], ""),
            "cpu_cost": _first_value(row, ["cpu_cost", "cpu cost"], ""),
            "io_cost": _first_value(row, ["io_cost", "io cost"], ""),
            "pstart": _first_value(row, ["pstart", "partition_start"], ""),
            "pstop": _first_value(row, ["pstop", "partition_stop"], ""),
            "temp_space": _first_value(row, ["temp_space", "temp"], ""),
            "filter_predicates": _first_value(row, ["filter_predicates", "filter", "filters"], ""),
            "access_predicates": _first_value(row, ["access_predicates", "access", "predicates"], ""),
            "depth": depth,
        }
        nodes.append(node)

    return nodes


def _parse_plan_baselines(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """Parse SQL Plan Baseline information if present in the AWR."""
    baselines = []
    patterns = [
        r"SQL Plan Baseline",
        r"Plan Hash Value",
        r"Plan baseline",
    ]

    for pattern in patterns:
        regex = re.compile(pattern, re.IGNORECASE)
        for table in soup.find_all("table"):
            summary = table.get("summary") or ""
            prev = table.find_previous(["h1", "h2", "h3", "h4", "b", "p"])
            header_text = prev.get_text("", strip=True) if prev else ""
            if not (regex.search(summary) or regex.search(header_text)):
                continue

            rows = _parse_table(table)
            if not rows:
                continue

            for row in rows:
                plan_hash = _first_value(row, ["plan_hash_value", "plan_hash", "plan hash value"], "")
                sql_id = _first_value(row, ["sql_id", "sqlid"], "")
                plan_name = _first_value(row, ["plan_name", "baseline plan name", "name"], "")
                enabled = _first_value(row, ["enabled", "accepted"], "")
                origin = _first_value(row, ["origin"], "")
                executions = _first_value(row, ["executions", "execs"], "")

                if plan_hash or plan_name:
                    baselines.append({
                        "sql_id": sql_id,
                        "plan_hash_value": plan_hash,
                        "plan_name": plan_name,
                        "enabled": enabled,
                        "origin": origin,
                        "executions": executions,
                    })
            break

    return baselines
