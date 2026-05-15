from app.analyzers.oracle_awr.event_semantics import classify_event_semantics


def extract_awr_metrics(parsed_data):
    metrics = {}

    top_events = parsed_data.get("top_events", [])
    wait_classes = parsed_data.get("wait_classes", [])
    time_model = parsed_data.get("time_model", {})
    load_profile = parsed_data.get("load_profile", {})
    snapshot = parsed_data.get("snapshot", {})
    os_stats = parsed_data.get("os_stats", {})
    instance_activity = parsed_data.get("instance_activity", {})

    metrics["db_cpu_pct_db_time"] = find_db_cpu_pct(top_events, wait_classes, time_model)
    metrics["user_io_pct_db_time"] = find_wait_class_pct(wait_classes, "User I/O")
    metrics["configuration_pct_db_time"] = find_wait_class_pct(wait_classes, "Configuration")
    metrics["commit_pct_db_time"] = find_wait_class_pct(wait_classes, "Commit")
    metrics["concurrency_pct_db_time"] = find_wait_class_pct(wait_classes, "Concurrency")
    metrics["application_pct_db_time"] = find_wait_class_pct(wait_classes, "Application")
    metrics["network_pct_db_time"] = find_wait_class_pct(wait_classes, "Network")
    metrics["system_io_pct_db_time"] = find_wait_class_pct(wait_classes, "System I/O")
    metrics["parse_time_pct_db_time"] = find_time_model_pct(time_model, "parse time elapsed")
    metrics["log_file_switch_checkpoint_incomplete_pct_db_time"] = find_pct(top_events, ["log file switch (checkpoint incomplete)"])
    metrics["log_file_switch_checkpoint_incomplete_time_s"] = find_event_value(top_events, "log file switch (checkpoint incomplete)", "time_s")
    metrics["log_file_switch_checkpoint_incomplete_avg_ms"] = find_event_value(top_events, "log file switch (checkpoint incomplete)", "avg_wait_ms")
    metrics["log_file_sync_pct_db_time"] = find_pct(top_events, ["log file sync"])
    metrics["log_file_sync_avg_ms"] = find_event_value(top_events, "log file sync", "avg_wait_ms")
    metrics["logical_read_blocks_per_sec"] = find_load_profile_value(load_profile, "Logical read (blocks):", "per_second")
    metrics["physical_read_blocks_per_sec"] = find_load_profile_value(load_profile, "Physical read (blocks):", "per_second")
    metrics["read_io_mb_per_sec"] = find_load_profile_value(load_profile, "Read IO (MB):", "per_second")
    metrics["write_io_mb_per_sec"] = find_load_profile_value(load_profile, "Write IO (MB):", "per_second")
    metrics["db_time_minutes"] = find_snapshot_minutes(snapshot, "DB Time:")
    metrics["elapsed_minutes"] = find_snapshot_minutes(snapshot, "Elapsed:")
    metrics["aas"] = calculate_aas(metrics["db_time_minutes"], metrics["elapsed_minutes"])
    metrics["db_cpu_seconds"] = find_time_model_seconds(time_model, "DB CPU")
    metrics["host_cpu_idle_pct"] = calculate_host_idle_pct(os_stats)
    metrics["db_instance_cpu_pct"] = calculate_db_instance_cpu_pct(metrics["db_cpu_seconds"], metrics["elapsed_minutes"], os_stats)
    metrics["cpu_count"] = find_os_stat_value(os_stats, "NUM_CPUS")
    metrics["load_average_begin"] = find_os_stat_value(os_stats, "LOAD")
    metrics["load_average_end"] = find_os_stat_end_value(os_stats, "LOAD")
    metrics["event_semantics"] = classify_event_semantics(top_events)
    metrics["load_intensity"] = detect_load_intensity(metrics)
    metrics["cpu_saturation_risk"] = detect_cpu_saturation_risk(metrics)
    metrics["workload_type"] = detect_workload_type(metrics)
    metrics["waiting_vs_cpu_model"] = detect_waiting_vs_cpu_model(metrics)
    metrics["memory_pressure"] = detect_memory_pressure(parsed_data.get("memory_stats", {}))
    metrics["parse_success"] = parsed_data.get("_parse_success", True)
    metrics["parse_error"] = parsed_data.get("_parse_error", "")

    metrics["top_events"] = normalize_top_events(top_events, metrics)
    metrics["wait_classes"] = wait_classes
    metrics["foreground_wait_class"] = parsed_data.get("foreground_wait_class", [])
    metrics["top_sql_elapsed"] = parsed_data.get("top_sql_elapsed", [])
    metrics["top_sql_cpu"] = parsed_data.get("top_sql_cpu", [])
    metrics["top_sql_gets"] = parsed_data.get("top_sql_gets", [])
    metrics["top_sql_reads"] = parsed_data.get("top_sql_reads", [])
    metrics["top_sql_behaviors"] = classify_top_sql_behaviors(metrics)
    metrics["load_profile"] = load_profile
    metrics["instance_efficiency"] = parsed_data.get("instance_efficiency", {})
    metrics["io_stats"] = parsed_data.get("io_stats", [])
    metrics["os_stats"] = os_stats
    metrics["memory_stats"] = parsed_data.get("memory_stats", {})

    # New parsed sections passthrough
    metrics["segments_logical_reads"] = parsed_data.get("segments_logical_reads", [])
    metrics["segments_physical_reads"] = parsed_data.get("segments_physical_reads", [])
    metrics["segments_table_scans"] = parsed_data.get("segments_table_scans", [])
    metrics["latch_activity"] = parsed_data.get("latch_activity", [])
    metrics["enqueue_activity"] = parsed_data.get("enqueue_activity", [])
    metrics["pga_advisory"] = parsed_data.get("pga_advisory", [])
    metrics["sga_advisory"] = parsed_data.get("sga_advisory", [])
    metrics["instance_activity"] = instance_activity

    # Derived metrics from Instance Activity
    metrics["commits_per_sec"] = find_instance_activity(instance_activity, "user commits", "per_second")
    metrics["rollbacks_per_sec"] = find_instance_activity(instance_activity, "user rollbacks", "per_second")
    metrics["redo_size_per_sec"] = find_instance_activity(instance_activity, "redo size", "per_second")
    metrics["hard_parses_per_sec"] = find_instance_activity(instance_activity, "parse count (hard)", "per_second")
    metrics["sorts_disk"] = find_instance_activity(instance_activity, "sorts (disk)", "total")
    metrics["sorts_disk_per_sec"] = find_instance_activity(instance_activity, "sorts (disk)", "per_second")
    metrics["long_table_scans"] = find_instance_activity(instance_activity, "table scans (long tables)", "total")
    metrics["long_table_scans_per_sec"] = find_instance_activity(instance_activity, "table scans (long tables)", "per_second")
    metrics["continued_row_fetches"] = find_instance_activity(instance_activity, "table fetch continued row", "total")
    metrics["continued_row_per_sec"] = find_instance_activity(instance_activity, "table fetch continued row", "per_second")
    metrics["executes_per_sec"] = find_instance_activity(instance_activity, "execute count", "per_second")
    metrics["user_calls_per_sec"] = find_instance_activity(instance_activity, "user calls", "per_second")

    # Rollback ratio: rollbacks / (commits + rollbacks) * 100
    commits = metrics.get("commits_per_sec", 0) or 0
    rollbacks = metrics.get("rollbacks_per_sec", 0) or 0
    metrics["rollback_ratio"] = round(rollbacks * 100 / (commits + rollbacks), 1) if (commits + rollbacks) else 0

    # Wait class percentages derived from top_events
    top_events = metrics.get("top_events", [])
    elapsed = metrics.get("elapsed_minutes", 1) or 1
    total_time_s = elapsed * 60

    # GC (RAC) percentage
    gc_time_s = sum(
        safe_float(evt.get("time_s", 0))
        for evt in top_events
        if "gc" in str(evt.get("event", "")).lower()
    )
    metrics["gc_pct_db_time"] = round(gc_time_s * 100 / (total_time_s or 1), 1) if gc_time_s else 0

    # Latch percentage
    latch_time_s = sum(
        safe_float(evt.get("time_s", 0))
        for evt in top_events
        if "latch" in str(evt.get("event", "")).lower()
    )
    metrics["latch_pct_db_time"] = round(latch_time_s * 100 / (total_time_s or 1), 1) if latch_time_s else 0

    # Network percentage
    net_time_s = sum(
        safe_float(evt.get("time_s", 0))
        for evt in top_events
        if "sql*net" in str(evt.get("event", "")).lower()
    )
    metrics["net_pct_db_time"] = round(net_time_s * 100 / (total_time_s or 1), 1) if net_time_s else 0

    # TEMP percentage (direct path read/write temp)
    temp_time_s = sum(
        safe_float(evt.get("time_s", 0))
        for evt in top_events
        if "direct path" in str(evt.get("event", "")).lower() and "temp" in str(evt.get("event", "")).lower()
    )
    metrics["temp_pct_db_time"] = round(temp_time_s * 100 / (total_time_s or 1), 1) if temp_time_s else 0

    return metrics


def find_pct(rows, names):
    for row in rows:
        name = str(row.get("event", "")).lower()
        for target in names:
            if target.lower() in name:
                return safe_float(row.get("pct_db_time"))
    return 0


def find_db_cpu_pct(top_events, wait_classes, time_model):
    values = [
        find_pct(top_events, ["DB CPU"]),
        find_wait_class_pct(wait_classes, "DB CPU"),
        find_time_model_pct(time_model, "DB CPU"),
    ]
    return max(values)


def find_wait_class_pct(rows, wait_class):
    for row in rows:
        name = str(row.get("wait_class", "")).lower()
        if wait_class.lower() in name:
            return safe_float(row.get("pct_db_time"))
    return 0


def find_time_model_pct(time_model, name):
    for key, value in time_model.items():
        if name.lower() in str(key).lower():
            if isinstance(value, dict):
                return safe_float(value.get("pct_db_time"))
            return safe_float(value)
    return 0


def find_time_model_seconds(time_model, name):
    for key, value in time_model.items():
        if name.lower() in str(key).lower():
            if isinstance(value, dict):
                return safe_float(value.get("time_s"))
            return 0
    return 0


def find_event_value(rows, event_name, field):
    for row in rows:
        name = str(row.get("event", "")).lower()
        if event_name.lower() in name:
            return safe_float(row.get(field))
    return 0


def find_load_profile_value(load_profile, name, field):
    for key, row in load_profile.items():
        if name.lower() == str(key).lower() and isinstance(row, dict):
            return safe_float(row.get(field))
    return 0


def find_snapshot_minutes(snapshot, label):
    for row in snapshot.get("rows", []):
        if str(row.get("col_0", "")).lower() == label.lower():
            return safe_float(row.get("snap_time"))
    return 0


def find_instance_activity(instance_activity, name, field):
    """Find a value from instance activity stats by stat name."""
    data = instance_activity.get(name.lower(), {})
    if isinstance(data, dict):
        return safe_float(data.get(field))
    return safe_float(data)


def calculate_aas(db_time_minutes, elapsed_minutes):
    if not elapsed_minutes:
        return 0
    return round(db_time_minutes / elapsed_minutes, 2)


def find_os_stat_value(os_stats, name):
    row = os_stats.get(name)
    if isinstance(row, dict):
        return safe_float(row.get("value"))
    return safe_float(row)


def find_os_stat_end_value(os_stats, name):
    row = os_stats.get(name)
    if isinstance(row, dict):
        return safe_float(row.get("end_value"))
    return 0


def calculate_host_idle_pct(os_stats):
    idle = find_os_stat_value(os_stats, "AVG_IDLE_TIME")
    busy = find_os_stat_value(os_stats, "AVG_BUSY_TIME")
    if not idle and not busy:
        # Some AWR versions use different field names
        idle = find_os_stat_value(os_stats, "IDLE_TIME")
        busy = find_os_stat_value(os_stats, "BUSY_TIME")
    if not idle and not busy:
        # Try %Idle from Instance CPU section
        idle = find_os_stat_value(os_stats, "IDLE")
    total = idle + busy
    if not total:
        return 0
    return round(idle * 100 / total, 2)


def calculate_db_instance_cpu_pct(db_cpu_seconds, elapsed_minutes, os_stats):
    cpus = find_os_stat_value(os_stats, "NUM_CPUS")
    if not db_cpu_seconds or not elapsed_minutes or not cpus:
        return 0
    return round(db_cpu_seconds * 100 / (elapsed_minutes * 60 * cpus), 1)


def normalize_top_events(top_events, metrics):
    normalized = list(top_events)
    db_cpu_pct = metrics.get("db_cpu_pct_db_time", 0)
    db_cpu_seconds = metrics.get("db_cpu_seconds", 0)
    if db_cpu_pct and not any("db cpu" in str(item.get("event", "")).lower() for item in normalized):
        normalized.insert(
            0,
            {
                "event": "DB CPU",
                "wait_class": "DB CPU",
                "waits": "",
                "time_s": db_cpu_seconds,
                "avg_wait_ms": "",
                "pct_db_time": db_cpu_pct,
            },
        )
    return normalized


def detect_memory_pressure(memory_stats):
    text = " ".join(f"{key} {value}" for key, value in memory_stats.items()).lower()
    if not text:
        return 0
    pressure_tokens = ["low memory", "memory pressure", "pga limit", "resize", "free memory"]
    return 1 if any(token in text for token in pressure_tokens) else 0


def detect_load_intensity(metrics):
    aas = metrics.get("aas", 0) or 0
    cpu_count = metrics.get("cpu_count", 0) or 0
    if aas <= 1:
        return "低负载"
    if cpu_count and aas > cpu_count:
        return "极高负载"
    if aas >= 16:
        return "高负载"
    if aas >= 4:
        return "中负载"
    return "低负载"


def detect_cpu_saturation_risk(metrics):
    aas = metrics.get("aas", 0) or 0
    cpu_count = metrics.get("cpu_count", 0) or 0
    db_cpu = metrics.get("db_cpu_pct_db_time", 0) or 0
    return bool(cpu_count and aas > cpu_count and db_cpu >= 40)


def detect_workload_type(metrics):
    logical_reads = metrics.get("logical_read_blocks_per_sec", 0) or 0
    physical_reads = metrics.get("physical_read_blocks_per_sec", 0) or 0
    read_io = metrics.get("read_io_mb_per_sec", 0) or 0
    write_io = metrics.get("write_io_mb_per_sec", 0) or 0
    redo = find_load_profile_value(metrics.get("load_profile", {}), "Redo size (bytes):", "per_second")
    executes = find_load_profile_value(metrics.get("load_profile", {}), "Executes (SQL):", "per_second")
    transactions = find_load_profile_value(metrics.get("load_profile", {}), "Transactions:", "per_second")
    semantics = metrics.get("event_semantics", {})

    full_scan_pct = semantics.get("full_scan", {}).get("pct_db_time", 0)
    temp_pct = semantics.get("temp_pressure", {}).get("pct_db_time", 0)
    random_read_pct = semantics.get("oltp_random_read", {}).get("pct_db_time", 0)

    if metrics.get("db_cpu_pct_db_time", 0) < 5 and metrics.get("aas", 0) <= 1 and sum(group.get("pct_db_time", 0) for group in semantics.values()) < 5:
        return "Idle"
    if temp_pct >= 5 and write_io >= 10:
        return "ETL"
    if redo >= 500000 and write_io >= 10:
        return "ETL"
    if temp_pct >= 2 and full_scan_pct >= 2:
        return "Batch"
    if physical_reads >= 50000 or read_io >= 300 or full_scan_pct >= 5:
        return "OLAP"
    if transactions >= 20 or executes >= 1000 or random_read_pct >= 3:
        return "OLTP"
    if redo >= 500000 and transactions >= 5:
        return "Batch"
    return "Mixed"


def classify_top_sql_behaviors(metrics):
    behaviors = []
    seen = set()
    for category, rows in (
        ("高耗时 SQL", metrics.get("top_sql_elapsed", [])),
        ("CPU SQL", metrics.get("top_sql_cpu", [])),
        ("高逻辑读 SQL", metrics.get("top_sql_gets", [])),
        ("高物理读 SQL", metrics.get("top_sql_reads", [])),
    ):
        for row in rows[:5]:
            sql_id = row.get("sql_id")
            if not sql_id:
                continue
            key = (sql_id, category)
            if key in seen:
                continue
            seen.add(key)
            behaviors.append(
                {
                    "sql_id": sql_id,
                    "category": category,
                    "elapsed_time": row.get("elapsed_time"),
                    "cpu_time": row.get("cpu_time"),
                    "buffer_gets": row.get("buffer_gets"),
                    "physical_reads": row.get("physical_reads"),
                    "executions": row.get("executions"),
                    "sql_text": row.get("sql_text", ""),
                    "reason": describe_sql_behavior(category, row),
                }
            )
    return behaviors


def describe_sql_behavior(category, row):
    executions = safe_float(row.get("executions"))
    elapsed = safe_float(row.get("elapsed_time"))
    gets = safe_float(row.get("buffer_gets"))
    reads = safe_float(row.get("physical_reads"))

    if category == "高逻辑读 SQL":
        if executions and gets:
            gets_per_exec = gets / executions
            if gets_per_exec >= 100000:
                return f"Buffer Gets 极高（{int(gets_per_exec)}/exec），可能存在全表扫描或低效执行计划。"
            if gets_per_exec >= 10000:
                return f"Buffer Gets 较高（{int(gets_per_exec)}/exec），可能是 CPU 和逻辑读压力来源。"
        return "Buffer Gets 较高，可能是 CPU 和逻辑读压力来源。"
    if category == "高物理读 SQL":
        if executions and reads:
            reads_per_exec = reads / executions
            if reads_per_exec >= 10000:
                return f"Physical Reads 极高（{int(reads_per_exec)}/exec），可能存在全表扫描或缺少索引。"
            if reads_per_exec >= 1000:
                return f"Physical Reads 较高（{int(reads_per_exec)}/exec），可能是 I/O 压力或访问路径问题来源。"
        return "Physical Reads 较高，可能是 I/O 压力或访问路径问题来源。"
    if category == "CPU SQL":
        return "CPU Time 较高，可能存在计算、函数、排序、Hash Join 或执行计划问题。"

    # 高耗时 SQL
    if not executions:
        return "无执行记录（可能失败或挂起），需检查 SQL 状态。"
    if executions >= 100000:
        gets_hint = f"，Gets/Exec: {int(gets/executions)}" if gets and executions else ""
        return f"执行次数很高（{int(executions)} 次），可能是高频 SQL 放大整体负载{gets_hint}。"
    if elapsed and executions and elapsed / max(executions, 1) >= 10:
        return f"单次执行耗时较高（{elapsed/max(executions,1):.1f}s/exec），可能是大查询或复杂执行计划。"
    return "位于 Top SQL 前列，是解释 DB Time 的优先排查入口。"


def detect_waiting_vs_cpu_model(metrics):
    db_cpu = metrics.get("db_cpu_pct_db_time", 0) or 0
    wait_pct = sum(
        metrics.get(name, 0) or 0
        for name in (
            "user_io_pct_db_time",
            "configuration_pct_db_time",
            "commit_pct_db_time",
            "concurrency_pct_db_time",
            "application_pct_db_time",
            "network_pct_db_time",
            "system_io_pct_db_time",
        )
    )
    semantic_wait_pct = sum(
        group.get("pct_db_time", 0) or 0
        for group in (metrics.get("event_semantics") or {}).values()
    )
    wait_pct = max(wait_pct, semantic_wait_pct)
    if db_cpu < 20 and wait_pct >= 20:
        return "waiting_dominant"
    if db_cpu >= 40 and db_cpu >= wait_pct:
        return "cpu_dominant"
    return "mixed"


def safe_float(value):
    if value is None:
        return 0
    try:
        text = str(value).replace(",", "").replace("%", "").strip()
        number = ""
        for char in text:
            if char.isdigit() or char in ".-":
                number += char
            elif number:
                break
        return float(number) if number else 0
    except Exception:
        return 0
