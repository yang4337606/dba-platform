import re

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
    metrics["sql_plan_statistics"] = parsed_data.get("sql_plan_statistics", {})
    metrics["execution_plans"] = parsed_data.get("execution_plans", {})
    metrics["sql_plan_baselines"] = parsed_data.get("sql_plan_baselines", [])
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

    # --- Phase 1: Activate previously unused parsed data ---

    # PGA/SGA Advisory derived metrics
    pga_adv = parse_pga_sga_advisory(parsed_data.get("pga_advisory", []), "pga")
    sga_adv = parse_pga_sga_advisory(parsed_data.get("sga_advisory", []), "sga")
    metrics["pga_advisory_benefit_pct"] = pga_adv.get("benefit_pct", 0)
    metrics["pga_advisory_current_mb"] = pga_adv.get("current_mb", 0)
    metrics["pga_advisory_estimated_optimal_mb"] = pga_adv.get("optimal_mb", 0)
    metrics["sga_advisory_benefit_pct"] = sga_adv.get("benefit_pct", 0)
    metrics["sga_advisory_current_mb"] = sga_adv.get("current_mb", 0)
    metrics["sga_advisory_estimated_optimal_mb"] = sga_adv.get("optimal_mb", 0)

    # IO Stats by tablespace
    io_analysis = analyze_io_stats(parsed_data.get("io_stats", []))
    metrics["io_stats_hot_tablespace"] = io_analysis.get("hot_tablespace", "")
    metrics["io_stats_avg_read_latency_ms"] = io_analysis.get("avg_read_latency_ms", 0)
    metrics["io_stats_avg_write_latency_ms"] = io_analysis.get("avg_write_latency_ms", 0)
    metrics["io_stats_high_latency_count"] = io_analysis.get("high_latency_count", 0)
    metrics["io_stats_high_latency_tablespaces"] = io_analysis.get("high_latency_tablespaces", [])

    # Foreground Wait Class
    fg_metrics = extract_foreground_metrics(parsed_data.get("foreground_wait_class", []))
    metrics["foreground_db_cpu_pct"] = fg_metrics.get("db_cpu_pct", 0)
    metrics["fg_top_wait_class"] = fg_metrics.get("top_wait_class", "")
    metrics["fg_top_wait_pct"] = fg_metrics.get("top_wait_pct", 0)

    # More Instance Activity derived metrics
    parse_total = find_instance_activity(instance_activity, "parse count (total)", "per_second")
    metrics["parse_total_per_sec"] = parse_total
    hard = metrics.get("hard_parses_per_sec", 0) or 0
    metrics["parse_ratio_hard_pct"] = round(hard * 100 / (parse_total or 1), 1) if parse_total else 0
    metrics["logons_per_sec"] = find_instance_activity(instance_activity, "logons cumulative", "per_second")
    metrics["open_cursors_per_sec"] = find_instance_activity(instance_activity, "opened cursors cumulative", "per_second")
    metrics["session_logical_reads_per_sec"] = find_instance_activity(instance_activity, "session logical reads", "per_second")
    metrics["physical_reads_per_sec"] = find_instance_activity(instance_activity, "physical reads", "per_second")
    redo_writes = find_instance_activity(instance_activity, "redo writes", "per_second")
    metrics["redo_writes_per_sec"] = redo_writes
    redo_size = metrics.get("redo_size_per_sec", 0) or 0
    metrics["avg_redo_write_size"] = round(redo_size / (redo_writes or 1)) if redo_writes else 0

    # Segment physical reads and table scans concentration
    seg_phys = parsed_data.get("segments_physical_reads", [])
    seg_scans = parsed_data.get("segments_table_scans", [])
    metrics["segments_physical_reads_top3"] = [
        {"owner": s.get("owner", ""), "object_name": s.get("object_name", ""), "pct_total": s.get("pct_total", 0)}
        for s in (seg_phys or [])[:3]
    ]
    metrics["segments_table_scans_top3"] = [
        {"owner": s.get("owner", ""), "object_name": s.get("object_name", ""), "pct_total": s.get("pct_total", 0)}
        for s in (seg_scans or [])[:3]
    ]
    top_scan_pct = safe_float((seg_scans[0].get("pct_total", 0) if seg_scans else 0))
    metrics["segment_scan_concentration_pct"] = top_scan_pct

    # Count segments with table scans > 0 (for partition prune failure rule)
    metrics["table_scan_pk_count"] = sum(1 for s in (seg_scans or []) if safe_float(s.get("metric_value", 0)) > 10)

    # Instance Efficiency derived metrics
    ie = parsed_data.get("instance_efficiency", {})
    metrics["buffer_hit_ratio"] = _extract_efficiency_pct(ie, ["Buffer Hit", "Buffer Nowait", "buffer pool hit"])
    metrics["library_cache_hit_ratio"] = _extract_efficiency_pct(ie, ["Library Hit", "Library Cache Hit", "library cache hit"])
    metrics["dict_hit_ratio"] = _extract_efficiency_pct(ie, ["Dictionary Hit", "dict cache hit", "Row Cache Hit"])
    metrics["latch_hit_ratio"] = _extract_efficiency_pct(ie, ["Latch Hit", "latch hit"])
    metrics["soft_parse_ratio"] = _extract_efficiency_pct(ie, ["Soft Parse", "soft parse"])
    metrics["in_memory_sort_ratio"] = _extract_efficiency_pct(ie, ["In-memory Sort", "In-Memory Sort", "sorts (memory)"])
    metrics["execute_without_parse_ratio"] = _extract_efficiency_pct(ie, ["Execute to Parse", "Non-Parse CPU"])
    metrics["redo_nowait_ratio"] = _extract_efficiency_pct(ie, ["Redo NoWait", "redo nowait"])
    metrics["non_parse_cpu_ratio"] = _extract_efficiency_pct(ie, ["Non-Parse CPU"])

    # ============================================================
    # Phase 2: Extract metrics referenced by rules.yaml
    # These were previously missing, causing silent rule failures
    # ============================================================

    # --- Top Events derived: specific wait event percentages ---
    metrics["db_file_sequential_read_avg_ms"] = find_event_value(top_events, "db file sequential read", "avg_wait_ms")
    metrics["log_file_parallel_write_avg_ms"] = find_event_value(top_events, "log file parallel write", "avg_wait_ms")
    metrics["direct_path_read_pct_db_time"] = find_pct(top_events, ["direct path read"])
    metrics["direct_path_read_temp_pct_db_time"] = find_pct(top_events, ["direct path read temp"])
    metrics["direct_path_write_temp_pct_db_time"] = find_pct(top_events, ["direct path write temp"])
    metrics["free_buffer_waits_pct_db_time"] = find_pct(top_events, ["free buffer waits"])
    metrics["px_deq_credit_send_blkd_pct_db_time"] = find_pct(top_events, ["px deq credit: send blkd"])
    metrics["checkpoint_incomplete_pct_db_time"] = find_pct(top_events, ["checkpoint incomplete", "log file switch (checkpoint incomplete)"])

    # --- Enqueue (lock) contention percentages ---
    metrics["enq_tm_contention_pct_db_time"] = find_pct(top_events, ["enq: tm - contention"])
    metrics["enq_tx_row_lock_pct_db_time"] = find_pct(top_events, ["enq: tx - row lock contention"])
    metrics["enq_sq_contention_pct_db_time"] = find_pct(top_events, ["enq: sq - contention"])

    # --- RAC GC specific ---
    metrics["gc_buffer_busy_pct_db_time"] = find_pct(top_events, ["gc buffer busy"])
    metrics["gc_cr_multi_pct_db_time"] = find_pct(top_events, ["gc cr multi block request", "gc cr block"])

    # --- Instance Activity derived: counts and rates ---
    metrics["n1_pattern_sql_count"] = 0  # Computed later from behaviors
    metrics["plan_change_sql_count"] = 0  # Computed later from plan analysis
    metrics["partition_all_count"] = 0  # Computed from execution plans
    metrics["table_scan_pk_count"] = 0  # Computed from segment data
    metrics["sql_with_type_conversion_count"] = 0  # Computed from SQL text analysis

    # Session cursor cache usage (for cursor leak detection)
    metrics["session_cached_cursors_pct"] = 0  # Requires OPEN_CURSORS param which is not in AWR

    # Undo retention violations
    metrics["undo_retention_violations_count"] = find_instance_activity(instance_activity, "undo change vector size", "total")
    # ORA-01555 count (snapshot too old)
    ora_1555 = 0
    for row in top_events:
        if "snapshot too old" in str(row.get("event", "")).lower() or "01555" in str(row.get("event", "")).lower():
            ora_1555 += 1
    metrics["ora_01555_count"] = ora_1555

    # ADG apply lag (if available from event or instance activity)
    metrics["adg_apply_lag_seconds"] = 0  # Requires specific AWR sections not always present

    # Resource Manager CPU quantum percentage
    metrics["resmgr_cpu_quantum_pct_db_time"] = find_pct(top_events, ["resmgr:cpu quantum", "resmgr: cpu quantum"])

    # In-Memory populate percentage (if available)
    metrics["inmemory_populate_pct"] = 0  # Requires V$IM_SEGMENTS, not always in AWR
    # Auto index count (21c+)
    metrics["auto_index_count"] = 0  # Requires DBA_AUTO_INDEX_IND_ACTIONS

    # RAC instance load imbalance
    metrics["instance_load_imbalance_ratio"] = 0  # Requires multi-instance data

    # 12c+ adaptive statistics indicators
    metrics["reoptimization_count"] = find_instance_activity(instance_activity, "reoptimized sql", "total")
    metrics["sql_plan_directives_active_count"] = 0  # Requires DBA_SQL_PLAN_DIRECTIVES, not in AWR

    # --- Compute derived metrics from behaviors (populated after classify_top_sql_behaviors) ---
    # These are set to 0 here and computed in classify_top_sql_behaviors

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
    """Detect workload type using weighted scoring for hybrid identification.

    Returns a dict with:
      - primary: the dominant workload type (str)
      - scores: normalized scores for each workload type (dict)
      - mixed_detail: description when multiple types are significant (str or None)
    For backward compatibility, the dict also behaves as a string via __str__.
    """
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
    commit_pct = metrics.get("commit_pct_db_time", 0) or 0
    db_cpu_pct = metrics.get("db_cpu_pct_db_time", 0) or 0
    aas = metrics.get("aas", 0) or 0

    # Check for Idle first
    if db_cpu_pct < 5 and aas <= 1 and sum(group.get("pct_db_time", 0) for group in semantics.values()) < 5:
        return _WorkloadResult("Idle", {"Idle": 1.0}, None)

    # Weighted scoring for each workload type
    scores = {"OLTP": 0, "OLAP": 0, "Batch": 0, "ETL": 0}

    # --- OLTP signals ---
    if transactions >= 50:
        scores["OLTP"] += 3.0
    elif transactions >= 20:
        scores["OLTP"] += 2.0
    elif transactions >= 5:
        scores["OLTP"] += 1.0

    if executes >= 5000:
        scores["OLTP"] += 2.0
    elif executes >= 1000:
        scores["OLTP"] += 1.0

    if random_read_pct >= 5:
        scores["OLTP"] += 2.0
    elif random_read_pct >= 3:
        scores["OLTP"] += 1.0

    if commit_pct >= 10:
        scores["OLTP"] += 1.5
    elif commit_pct >= 5:
        scores["OLTP"] += 0.5

    if logical_reads >= 100000 and physical_reads < 10000:
        scores["OLTP"] += 1.0  # High logical, low physical = cached OLTP

    # --- OLAP signals ---
    if full_scan_pct >= 10:
        scores["OLAP"] += 3.0
    elif full_scan_pct >= 5:
        scores["OLAP"] += 2.0
    elif full_scan_pct >= 2:
        scores["OLAP"] += 1.0

    if physical_reads >= 100000:
        scores["OLAP"] += 2.0
    elif physical_reads >= 50000:
        scores["OLAP"] += 1.5

    if read_io >= 500:
        scores["OLAP"] += 2.0
    elif read_io >= 300:
        scores["OLAP"] += 1.0

    if temp_pct >= 5:
        scores["OLAP"] += 1.5
    elif temp_pct >= 2:
        scores["OLAP"] += 0.5

    # --- Batch signals ---
    if temp_pct >= 2 and full_scan_pct >= 2:
        scores["Batch"] += 2.0

    if redo >= 500000 and transactions >= 5:
        scores["Batch"] += 2.0

    if write_io >= 20:
        scores["Batch"] += 1.5
    elif write_io >= 10:
        scores["Batch"] += 1.0

    if physical_reads >= 50000 and write_io >= 10:
        scores["Batch"] += 1.0

    # --- ETL signals ---
    if temp_pct >= 5 and write_io >= 10:
        scores["ETL"] += 3.0
    elif temp_pct >= 3 and write_io >= 5:
        scores["ETL"] += 1.5

    if redo >= 500000 and write_io >= 10:
        scores["ETL"] += 2.0

    if redo >= 1000000:
        scores["ETL"] += 1.0

    # Normalize scores
    total = sum(scores.values()) or 1
    normalized = {k: round(v / total, 3) for k, v in scores.items()}

    # Determine primary and check for mixed
    sorted_types = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    primary = sorted_types[0][0] if sorted_types[0][1] > 0 else "Mixed"

    # If top two types are close (within 40% of each other), report as mixed
    mixed_detail = None
    if len(sorted_types) >= 2 and sorted_types[0][1] > 0:
        ratio = sorted_types[1][1] / sorted_types[0][1] if sorted_types[0][1] else 0
        if ratio >= 0.6:
            mixed_detail = f"{sorted_types[0][0]}({normalized[sorted_types[0][0]]:.0%}) + {sorted_types[1][0]}({normalized[sorted_types[1][0]]:.0%})"
            primary = "Mixed"

    # If no scores at all, default to Mixed
    if all(v == 0 for v in scores.values()):
        primary = "Mixed"
        normalized = {"OLTP": 0.25, "OLAP": 0.25, "Batch": 0.25, "ETL": 0.25}

    return _WorkloadResult(primary, normalized, mixed_detail)


class _WorkloadResult:
    """Workload detection result that behaves as a string for backward compatibility."""

    def __init__(self, primary, scores, mixed_detail):
        self.primary = primary
        self.scores = scores
        self.mixed_detail = mixed_detail

    def __str__(self):
        return self.primary

    def __repr__(self):
        return f"WorkloadResult(primary={self.primary!r}, scores={self.scores})"

    def __eq__(self, other):
        if isinstance(other, str):
            return self.primary == other
        if isinstance(other, _WorkloadResult):
            return self.primary == other.primary
        return NotImplemented

    def __hash__(self):
        return hash(self.primary)

    def __contains__(self, item):
        # Support "OLTP" in workload_type style checks
        return item in self.primary

    def lower(self):
        return self.primary.lower()

    def upper(self):
        return self.primary.upper()


def classify_top_sql_behaviors(metrics):
    behaviors = []
    seen = set()
    for category, rows in (
        ("高耗时 SQL", metrics.get("top_sql_elapsed", [])),
        ("CPU SQL", metrics.get("top_sql_cpu", [])),
        ("高逻辑读 SQL", metrics.get("top_sql_gets", [])),
        ("高物理读 SQL", metrics.get("top_sql_reads", [])),
    ):
        for row in rows[:10]:
            sql_id = row.get("sql_id")
            if not sql_id:
                continue
            key = (sql_id, category)
            if key in seen:
                continue
            seen.add(key)
            text = row.get("sql_text", "")
            text_analysis = analyze_sql_text(text)
            behavior = {
                "sql_id": sql_id,
                "category": category,
                "elapsed_time": row.get("elapsed_time"),
                "cpu_time": row.get("cpu_time"),
                "buffer_gets": row.get("buffer_gets"),
                "physical_reads": row.get("physical_reads"),
                "executions": row.get("executions"),
                "rows_processed": row.get("rows_processed"),
                "sql_text": text,
                "reason": describe_sql_behavior(category, row),
                "text_analysis": text_analysis,
                "efficiency_score": compute_sql_efficiency(row),
            }
            behaviors.append(behavior)

    # Cross-SQL correlation: detect N+1 patterns
    n1_groups = detect_n1_patterns(behaviors)
    for group in n1_groups:
        for beh in behaviors:
            if beh["sql_id"] in group["sql_ids"]:
                beh["n1_pattern"] = group

    # Enrich with execution plan analysis
    plan_stats = metrics.get("sql_plan_statistics", {})
    if plan_stats:
        for beh in behaviors:
            sql_id = beh.get("sql_id", "")
            plan = plan_stats.get(sql_id)
            if plan:
                beh["plan_analysis"] = analyze_execution_plan(plan)

    # Enrich with detailed execution plans (new parser capability)
    exec_plans = metrics.get("execution_plans", {})
    if exec_plans:
        for beh in behaviors:
            sql_id = beh.get("sql_id", "")
            nodes = exec_plans.get(sql_id) or exec_plans.get(f"_plan_{sql_id}", [])
            if nodes:
                pa = beh.get("plan_analysis", {"issues": [], "hints": [], "access_path": "", "join_strategy": ""})
                # Detect partition pruning issues
                for node in nodes:
                    pstart = str(node.get("pstart", "")).upper()
                    pstop = str(node.get("pstop", "")).upper()
                    if pstart == "ALL" or pstop == "ALL":
                        obj = node.get("object_name", "")
                        if obj:
                            pa["issues"].append(f"分区表 {obj} 未触发分区裁剪（Pstart=ALL）")
                    filters = str(node.get("filter_predicates", ""))
                    op = str(node.get("operation", "")).upper()
                    if filters and "TABLE ACCESS" in op and "FULL" in op:
                        pa["issues"].append(f"全表扫描 {node.get('object_name', '')} 后有过滤条件，可能缺少索引")
                    # High cost operations
                    cost = safe_float(node.get("cost"))
                    if cost > 10000 and "TABLE ACCESS" in op and "FULL" in op:
                        pa["issues"].append(f"高代价全表扫描 {node.get('object_name', '')} cost={int(cost)}")
                beh["plan_analysis"] = pa
                beh["execution_plan_nodes"] = len(nodes)

    # Compute behavior-derived metrics and write back to metrics dict
    n1_count = sum(1 for beh in behaviors if beh.get("n1_pattern"))
    metrics["n1_pattern_sql_count"] = n1_count

    plan_changes = sum(1 for beh in behaviors if len(beh.get("plan_analysis", {}).get("issues", [])) > 1)
    metrics["plan_change_sql_count"] = plan_changes

    partition_all = sum(
        1 for nodes in exec_plans.values()
        for node in nodes
        if str(node.get("pstart", "")).upper() == "ALL" or str(node.get("pstop", "")).upper() == "ALL"
    )
    metrics["partition_all_count"] = partition_all

    type_conv_count = sum(1 for beh in behaviors if "implicit_type" in str(beh.get("text_analysis", {}).get("patterns", [])))
    metrics["sql_with_type_conversion_count"] = type_conv_count

    return behaviors


def analyze_sql_text(text):
    """Analyze SQL text for common anti-patterns and generate diagnostics."""
    if not text:
        return {"patterns": [], "diagnostics": []}

    upper = text.upper().strip()
    patterns = []
    diagnostics = []

    # SELECT * detection
    if re.search(r'\bSELECT\s+\*\s', upper + ' '):
        patterns.append("select_star")
        diagnostics.append("使用了 SELECT *，建议只选取必要列以减少逻辑读和网络传输")

    # Missing WHERE clause
    if not re.search(r'\bWHERE\b', upper) and re.search(r'\bSELECT\b', upper):
        if not re.search(r'\b(DUAL|V\$|DBA_|ALL_|USER_|GV\$)\b', upper):
            patterns.append("no_where")
            diagnostics.append("缺少 WHERE 条件，可能导致全表扫描")

    # Large IN list
    in_match = re.search(r'\bIN\s*\((\s*\d+\s*(?:,\s*\d+\s*){5,})\)', upper)
    if in_match:
        patterns.append("large_in_list")
        count = in_match.group(1).count(',') + 1
        diagnostics.append(f"IN 列表包含 {count} 个值，建议使用临时表或绑定变量集合")

    # LIKE '%...'
    if re.search(r"LIKE\s+'%", upper):
        patterns.append("leading_wildcard")
        diagnostics.append("LIKE 以通配符开头（'%...'），无法使用索引")

    # Implicit type conversion (string literal in numeric context)
    if re.search(r"=\s*'[0-9]+'", text):
        patterns.append("implicit_conversion")
        diagnostics.append("可能存在隐式类型转换，字符串字面量用于数值比较")

    # ORDER BY without LIMIT (in subqueries or main query)
    if re.search(r'\bORDER\s+BY\b', upper) and not re.search(r'\b(ROWNUM|FETCH\s+FIRST|LIMIT|ROWNUM\s*<=)\b', upper):
        patterns.append("sort_no_limit")
        diagnostics.append("存在 ORDER BY 但无行数限制，大结果集排序会消耗大量 TEMP 和 CPU")

    # Cartesian JOIN (no join condition between tables)
    from_count = len(re.findall(r'\b(FROM|JOIN)\b', upper))
    where_join = len(re.findall(r'\b\w+\.\w+\s*=\s*\w+\.\w+\b', upper))
    if from_count >= 2 and where_join == 0 and not re.search(r'\bCROSS\s+JOIN\b', upper):
        patterns.append("possible_cartesian")
        diagnostics.append("可能存在笛卡尔积（多表无关联条件），请检查 JOIN 条件")

    # Function on indexed column in WHERE
    if re.search(r'\bWHERE\b.*\b(TO_CHAR|TO_DATE|TO_NUMBER|NVL|DECODE|TRUNC|UPPER|LOWER|SUBSTR)\s*\(', upper):
        patterns.append("function_on_column")
        diagnostics.append("WHERE 条件中对列使用了函数，可能导致索引失效")

    # DISTINCT (often indicates missing proper join or data model issue)
    if re.search(r'\bSELECT\s+DISTINCT\b', upper):
        patterns.append("select_distinct")
        diagnostics.append("使用了 DISTINCT，可能是 JOIN 产生了重复行或查询逻辑可以优化")

    # NOT IN (often better rewritten as LEFT JOIN / NOT EXISTS)
    if re.search(r'\bNOT\s+IN\s*\(', upper):
        patterns.append("not_in")
        diagnostics.append("使用了 NOT IN，如果子查询包含 NULL 可能导致结果异常，建议改用 NOT EXISTS 或 LEFT JOIN")

    # OR conditions on different columns (causes index放弃)
    or_count = len(re.findall(r'\bOR\b', upper))
    if or_count >= 2 and re.search(r'\bWHERE\b', upper):
        patterns.append("multiple_or")
        diagnostics.append(f"WHERE 中有 {or_count} 个 OR 条件，可能导致优化器放弃索引改用全表扫描")

    # UNION without ALL (potential unnecessary sort/distinct)
    if re.search(r'\bUNION\b(?!\s+ALL\b)', upper) and 'UNION' in upper:
        patterns.append("union_no_all")
        diagnostics.append("使用了 UNION（而非 UNION ALL），如不需去重建议改用 UNION ALL 避免排序开销")

    # Subquery in WHERE (potential correlated subquery)
    if re.search(r'\bWHERE\b.*\bIN\s*\(\s*SELECT\b', upper):
        patterns.append("subquery_in_where")
        diagnostics.append("WHERE 中包含子查询，如果是关联子查询可能逐行执行，考虑改写为 JOIN")

    # NVL/COALESCE on indexed column
    if re.search(r'\b(NVL|COALESCE|DECODE)\s*\(\s*\w+\.\w+', upper):
        patterns.append("nvl_on_column")
        diagnostics.append("对列使用了 NVL/COALESCE/DECODE，可能导致该列上的索引无法使用")

    # BETWEEN for date range (check for TO_DATE conversion)
    if re.search(r'\bBETWEEN\b.*\bTO_DATE\b', upper):
        patterns.append("date_between")
        diagnostics.append("日期范围查询使用了 BETWEEN + TO_DATE，确保日期格式与列存储格式一致")

    # UPDATE/DELETE without WHERE (dangerous)
    if re.search(r'\b(UPDATE|DELETE)\s+(?!.*\bWHERE\b)', upper) and not re.search(r'\bWHERE\b', upper):
        patterns.append("dml_no_where")
        diagnostics.append("UPDATE/DELETE 缺少 WHERE 条件，将影响全表数据")

    return {"patterns": patterns, "diagnostics": diagnostics}


def compute_sql_efficiency(row):
    """Compute an efficiency score (0-100) for a SQL statement."""
    score = 100
    executions = safe_float(row.get("executions"))
    gets = safe_float(row.get("buffer_gets"))
    reads = safe_float(row.get("physical_reads"))
    elapsed = safe_float(row.get("elapsed_time"))
    rows = safe_float(row.get("rows_processed"))

    if not executions:
        return 0  # No execution data

    gets_per_exec = gets / executions if gets else 0
    reads_per_exec = reads / executions if reads else 0
    elapsed_per_exec = elapsed / executions if elapsed else 0

    # Gets/Exec penalty
    if gets_per_exec >= 100000:
        score -= 40
    elif gets_per_exec >= 10000:
        score -= 25
    elif gets_per_exec >= 1000:
        score -= 10

    # Reads/Exec penalty
    if reads_per_exec >= 10000:
        score -= 30
    elif reads_per_exec >= 1000:
        score -= 15

    # Elapsed/Exec penalty
    if elapsed_per_exec >= 60:
        score -= 30
    elif elapsed_per_exec >= 10:
        score -= 15
    elif elapsed_per_exec >= 1:
        score -= 5

    # Row source efficiency: rows returned per get
    if gets and rows:
        rows_per_get = rows / gets
        if rows_per_get < 0.001:
            score -= 15  # Very low return rate

    return max(0, min(100, score))


def detect_n1_patterns(behaviors):
    """Detect N+1 query patterns: same SQL text with very high execution counts."""
    groups = []
    text_groups = {}
    for beh in behaviors:
        text = (beh.get("sql_text") or "").strip()
        if not text or len(text) < 20:
            continue
        # Normalize: remove literals for fingerprinting
        fingerprint = re.sub(r"'[^']*'", "?", text)
        fingerprint = re.sub(r"\b\d+\b", "?", fingerprint)
        fingerprint = fingerprint[:200]  # Use first 200 chars as fingerprint
        text_groups.setdefault(fingerprint, []).append(beh)

    for fp, group in text_groups.items():
        if len(group) < 2:
            continue
        total_execs = sum(safe_float(b.get("executions")) for b in group)
        if total_execs >= 1000:
            sql_ids = list(set(b["sql_id"] for b in group if b.get("sql_id")))
            if len(sql_ids) >= 1:
                groups.append({
                    "sql_ids": sql_ids,
                    "total_executions": total_execs,
                    "pattern": "n_plus_1",
                    "diagnosis": f"检测到相似 SQL 模式共 {len(group)} 条，总执行 {int(total_execs)} 次，可能存在 N+1 查询问题",
                })
    return groups


def analyze_execution_plan(plan):
    """Analyze execution plan operations to infer access path issues."""
    result = {"issues": [], "hints": [], "access_path": "", "join_strategy": ""}

    operations = plan.get("operations", [])
    if not operations:
        return result

    has_full_scan = False
    has_index_scan = False
    has_nested_loop = False
    has_hash_join = False
    has_merge_join = False
    has_sort = False
    has_filter = False
    high_cost_ops = []
    table_access_by_index = False

    for op in operations:
        op_name = str(op.get("operation", "")).upper()
        obj = str(op.get("object_name", ""))
        cost = safe_float(op.get("cost"))

        # Full table scan
        if "TABLE ACCESS" in op_name and "FULL" in op_name:
            has_full_scan = True
            if cost > 1000:
                high_cost_ops.append(f"全表扫描 {obj} (cost={int(cost)})")
                result["issues"].append(f"全表扫描 {obj}，cost={int(cost)}，可能缺少索引或统计信息过期")

        # Index operations
        if "INDEX" in op_name:
            has_index_scan = True
            if "FAST FULL SCAN" in op_name:
                result["issues"].append(f"INDEX FAST FULL SCAN {obj}，可能索引过大或需要覆盖索引")
            if "RANGE SCAN" in op_name and cost > 500:
                result["issues"].append(f"INDEX RANGE SCAN {obj} cost={int(cost)}，范围扫描代价高，可能索引选择性差")

        # Table access by index rowid
        if "TABLE ACCESS" in op_name and "BY INDEX" in op_name:
            table_access_by_index = True
            if cost > 1000:
                high_cost_ops.append(f"索引回表 {obj} (cost={int(cost)})")

        # Join strategies
        if "NESTED LOOPS" in op_name:
            has_nested_loop = True
        if "HASH JOIN" in op_name:
            has_hash_join = True
        if "MERGE JOIN" in op_name:
            has_merge_join = True

        # Sort operations
        if "SORT" in op_name:
            has_sort = True
            if "TEMP" in op_name or "DISK" in str(op):
                result["issues"].append("排序操作溢出到磁盘，PGA sort area 可能不足")

        # Filter
        if "FILTER" in op_name and cost > 500:
            pass  # Reserved for future filter-related diagnostics

        # Partition operations
        if "PARTITION" in op_name and "ALL" in op_name:
            result["issues"].append("全分区扫描（PARTITION ALL），可能缺少分区裁剪")

    # Access path summary
    if has_full_scan and not has_index_scan:
        result["access_path"] = "全表扫描为主"
        result["hints"].append("考虑为高频查询添加索引")
    elif table_access_by_index:
        result["access_path"] = "索引回表访问"
    elif has_index_scan:
        result["access_path"] = "索引访问为主"

    # Join strategy summary
    if has_nested_loop and has_hash_join:
        result["join_strategy"] = "混合 (Nested Loop + Hash Join)"
    elif has_nested_loop:
        result["join_strategy"] = "Nested Loop"
    elif has_hash_join:
        result["join_strategy"] = "Hash Join"
    elif has_merge_join:
        result["join_strategy"] = "Merge Join"

    # Cross-analysis
    if has_nested_loop and has_full_scan:
        result["hints"].append("Nested Loop 内层有全表扫描，考虑改为 Hash Join 或添加索引")
    if has_sort and has_full_scan:
        result["hints"].append("排序+全表扫描组合，考虑添加索引消除排序")
    if high_cost_ops:
        result["hints"].append(f"高代价操作: {'; '.join(high_cost_ops[:3])}")

    return result


def describe_sql_behavior(category, row):
    executions = safe_float(row.get("executions"))
    elapsed = safe_float(row.get("elapsed_time"))
    gets = safe_float(row.get("buffer_gets"))
    reads = safe_float(row.get("physical_reads"))

    parts = []

    if category == "高逻辑读 SQL":
        if executions and gets:
            gets_per_exec = gets / executions
            if gets_per_exec >= 100000:
                parts.append(f"Buffer Gets 极高（{int(gets_per_exec)}/exec），可能存在全表扫描或低效执行计划。")
            elif gets_per_exec >= 10000:
                parts.append(f"Buffer Gets 较高（{int(gets_per_exec)}/exec），可能是 CPU 和逻辑读压力来源。")
            else:
                parts.append("Buffer Gets 较高，可能是 CPU 和逻辑读压力来源。")
        else:
            parts.append("Buffer Gets 较高，可能是 CPU 和逻辑读压力来源。")
    elif category == "高物理读 SQL":
        if executions and reads:
            reads_per_exec = reads / executions
            if reads_per_exec >= 10000:
                parts.append(f"Physical Reads 极高（{int(reads_per_exec)}/exec），可能存在全表扫描或缺少索引。")
            elif reads_per_exec >= 1000:
                parts.append(f"Physical Reads 较高（{int(reads_per_exec)}/exec），可能是 I/O 压力或访问路径问题来源。")
            else:
                parts.append("Physical Reads 较高，可能是 I/O 压力或访问路径问题来源。")
        else:
            parts.append("Physical Reads 较高，可能是 I/O 压力或访问路径问题来源。")
    elif category == "CPU SQL":
        parts.append("CPU Time 较高，可能存在计算、函数、排序、Hash Join 或执行计划问题。")
    else:
        # 高耗时 SQL
        if not executions:
            parts.append("无执行记录（可能失败或挂起），需检查 SQL 状态。")
        elif executions >= 100000:
            gets_hint = f"，Gets/Exec: {int(gets/executions)}" if gets and executions else ""
            parts.append(f"执行次数很高（{int(executions)} 次），可能是高频 SQL 放大整体负载{gets_hint}。")
        elif elapsed and executions and elapsed / max(executions, 1) >= 10:
            parts.append(f"单次执行耗时较高（{elapsed/max(executions,1):.1f}s/exec），可能是大查询或复杂执行计划。")
        else:
            parts.append("位于 Top SQL 前列，是解释 DB Time 的优先排查入口。")

    # Append SQL text analysis hints
    text_analysis = analyze_sql_text(row.get("sql_text", ""))
    for diag in text_analysis.get("diagnostics", []):
        parts.append(diag)

    return " | ".join(parts)


def _extract_efficiency_pct(ie, names):
    """Extract a percentage value from instance_efficiency dict, trying multiple name variants."""
    if not ie:
        return 0
    for name in names:
        for key, val in ie.items():
            if name.lower() in str(key).lower():
                return safe_float(val)
    return 0


def parse_pga_sga_advisory(rows, kind):
    """Extract benefit percentage and sizes from PGA/SGA advisory table."""
    result = {"benefit_pct": 0, "current_mb": 0, "optimal_mb": 0}
    if not rows:
        return result

    # Advisory rows typically have: size_factor, size_mb, estd_extra_% (or similar)
    best_benefit = 0
    best_size = 0
    current_size = 0
    for row in rows:
        size_mb = safe_float(row.get("size_mb") or row.get("pga_target_for_estimate") or row.get("sga_size") or 0)
        benefit = safe_float(row.get("estd_extra_pct") or row.get("estd_over_alloc_count") or row.get("estd_pct_of_db_time_for_reads") or 0)
        factor = safe_float(row.get("size_factor") or row.get("pga_target_factor") or row.get("sga_size_factor") or 0)

        # The row with factor ~1.0 is the current size
        if 0.9 <= factor <= 1.1 and size_mb > 0:
            current_size = size_mb

        if benefit > best_benefit:
            best_benefit = benefit
            best_size = size_mb

    result["current_mb"] = current_size
    result["optimal_mb"] = best_size
    result["benefit_pct"] = round(best_benefit, 1)
    return result


def analyze_io_stats(rows):
    """Analyze IO stats by tablespace to find hot spots and latency."""
    result = {"hot_tablespace": "", "avg_read_latency_ms": 0, "avg_write_latency_ms": 0,
              "high_latency_count": 0, "high_latency_tablespaces": []}
    if not rows:
        return result

    total_read_latency = 0
    total_write_latency = 0
    read_count = 0
    write_count = 0
    max_wait = 0
    hot_ts = ""
    high_latency = []

    for row in rows:
        ts_name = row.get("tablespace_name") or row.get("name") or ""
        read_lat = safe_float(row.get("av_rd_ms") or row.get("avg_read_latency_ms") or 0)
        write_lat = safe_float(row.get("av_wr_ms") or row.get("avg_write_latency_ms") or 0)
        total_wait = read_lat + write_lat

        if read_lat > 0:
            total_read_latency += read_lat
            read_count += 1
        if write_lat > 0:
            total_write_latency += write_lat
            write_count += 1

        if total_wait > max_wait:
            max_wait = total_wait
            hot_ts = ts_name

        if read_lat > 10:
            high_latency.append({"tablespace": ts_name, "read_latency_ms": round(read_lat, 1)})

    result["hot_tablespace"] = hot_ts
    result["avg_read_latency_ms"] = round(total_read_latency / read_count, 1) if read_count else 0
    result["avg_write_latency_ms"] = round(total_write_latency / write_count, 1) if write_count else 0
    result["high_latency_count"] = len(high_latency)
    result["high_latency_tablespaces"] = high_latency[:10]
    return result


def extract_foreground_metrics(rows):
    """Extract key metrics from foreground wait class data."""
    result = {"db_cpu_pct": 0, "top_wait_class": "", "top_wait_pct": 0}
    if not rows:
        return result

    top_pct = 0
    top_class = ""
    for row in rows:
        name = str(row.get("wait_class", "")).strip()
        pct = safe_float(row.get("pct_db_time") or row.get("pct") or 0)
        if "db cpu" in name.lower():
            result["db_cpu_pct"] = pct
        if pct > top_pct:
            top_pct = pct
            top_class = name

    result["top_wait_class"] = top_class
    result["top_wait_pct"] = round(top_pct, 1)
    return result


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
