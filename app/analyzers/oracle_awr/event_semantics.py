EVENT_SEMANTICS = {
    "redo_pipeline": [
        "log buffer space",
        "log file sync",
        "log file parallel write",
        "log file switch",
        "checkpoint incomplete",
        "log file sequential read",
        "log file single write",
    ],
    "temp_pressure": [
        "direct path write temp",
        "direct path read temp",
        "local write wait",
    ],
    "oltp_random_read": [
        "db file sequential read",
    ],
    "full_scan": [
        "db file scattered read",
        "direct path read",
    ],
    "hot_block": [
        "buffer busy waits",
        "read by other session",
        "gc buffer busy",
        "gc cr block busy",
        "gc current block busy",
    ],
    "hot_object": [
        "enq: tx - row lock contention",
        "enq: tm - contention",
        "row lock contention",
        "latch:",
        "cursor: pin s wait on x",
    ],
    "lock_contention": [
        "enq: tx",
        "row lock contention",
        "library cache lock",
        "cursor: pin s wait on x",
        "enq: hw",
        "enq: st",
        "enq: ta",
    ],
    "parse_pressure": [
        "library cache",
        "cursor mutex",
        "cursor: pin",
        "hard parse",
        "shared pool",
    ],
    "network_wait": [
        "sql*net message",
        "sql*net more data",
        "sql*net break/reset",
        "sql*net vector",
    ],
    "storage_io": [
        "db file sequential read",
        "db file scattered read",
        "direct path read",
        "direct path write",
        "log file parallel write",
        "control file",
        "db file parallel write",
        "db file single write",
    ],
    "rac_global_cache": [
        "gc ",
        "global cache",
        "gc cr",
        "gc current",
        "gc buffer",
        "gc grant",
        "gc quiesce",
    ],
    "rac_gc_network": [
        "gc cr request",
        "gc current request",
        "gc cr multi block request",
        "gc current multi block request",
        "gc cr grant",
        "gc current grant",
    ],
    "parallel_query": [
        "px deq",
        "px qref",
        "px send",
        "px receive",
        "px deq credit",
        "px deq: execute reply",
        "px deq: table q",
        "parallel query",
    ],
    "pga_memory": [
        "direct path read",
        "direct path write",
        "pga memory",
        "workarea memory",
    ],
    "lob_operations": [
        "lob",
        "dbms_lock.sleep",
        "enq: hw - contention",
    ],
    "scheduler_resource": [
        "resmgr:",
        "resmgr:cpu quantum",
        "resmgr:pq",
    ],
    "flashback_log": [
        "flashback log",
        "flashback buf free",
        "flashback log file sync",
    ],
    "adg_transport": [
        "rfs",
        "archive log",
        "redo transport",
        "gap",
    ],
    "undo_management": [
        "enq: tx - allocate",
        "undo segment",
        "enq: us",
        "snapshot too old",
        "ora-01555",
    ],
    "checkpoint_tuning": [
        "checkpoint completed",
        "log file switch (checkpoint incomplete)",
        "log file switch completion",
        "db file parallel write",
    ],
}


SEMANTIC_DISPLAY_NAMES = {
    "redo_pipeline": "Redo/LGWR 写入链路",
    "temp_pressure": "TEMP/PGA 压力",
    "oltp_random_read": "OLTP 随机读",
    "full_scan": "全表扫描/直接路径读",
    "hot_block": "热点块/读竞争",
    "hot_object": "热点对象/锁或闩锁竞争",
    "lock_contention": "锁争用",
    "parse_pressure": "Parse/Library Cache 压力",
    "network_wait": "网络等待",
    "storage_io": "存储 I/O 链路",
    "rac_global_cache": "RAC Global Cache 等待",
    "rac_gc_network": "RAC GC 网络传输",
    "parallel_query": "并行查询",
    "pga_memory": "PGA/内存操作",
    "lob_operations": "LOB 大对象操作",
    "scheduler_resource": "资源管理器/调度",
    "flashback_log": "Flashback 日志",
    "adg_transport": "ADG Redo 传输",
    "undo_management": "Undo 管理",
    "checkpoint_tuning": "Checkpoint 调优",
}


def classify_event_semantics(events):
    semantic_groups = {
        key: {"pct_db_time": 0.0, "time_s": 0.0, "events": []}
        for key in EVENT_SEMANTICS
    }

    for event in events:
        event_name = str(event.get("event", "")).lower()
        matched = False
        for semantic, patterns in EVENT_SEMANTICS.items():
            if any(pattern in event_name for pattern in patterns):
                semantic_groups[semantic]["pct_db_time"] += safe_float(event.get("pct_db_time"))
                semantic_groups[semantic]["time_s"] += safe_float(event.get("time_s"))
                semantic_groups[semantic]["events"].append(event)
                matched = True
                break  # Each event matches only the first semantic group

    return semantic_groups


def safe_float(value):
    if value is None:
        return 0.0
    try:
        text = str(value).replace(",", "").replace("%", "").strip()
        number = ""
        for char in text:
            if char.isdigit() or char in ".-":
                number += char
            elif number:
                break
        return float(number) if number else 0.0
    except Exception:
        return 0.0
