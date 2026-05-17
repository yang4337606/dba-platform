EVENT_SEMANTICS = {
    # ============================================================
    # 完整等待事件语义库 v2.1
    # 按真实生产案例分类，每类包含常见事件名模式和语义描述
    # ============================================================

    "redo_pipeline": [
        "log buffer space",
        "log file sync",
        "log file parallel write",
        "log file switch",
        "log file switch (checkpoint",
        "log file switch (archiving",
        "log file switch (clearing",
        "log file switch completion",
        "checkpoint incomplete",
        "log file sequential read",
        "log file single write",
        "lgwr wait for",
        "lgrd wakeup",
        "rfs write",
        "rfs write sync",
    ],
    "temp_pressure": [
        "direct path read temp",
        "direct path write temp",
        "local write wait",
        "temp file segmented read",
        "temp file init write",
        "sort segment",
        "memory sort",
    ],
    "oltp_random_read": [
        "db file sequential read",
        "db file scattered read (small)",
        "gc cr current block lost",
    ],
    "full_scan": [
        "db file scattered read",
        "direct path read",
        "db file parallel read",
        "fet$",
    ],
    "hot_block": [
        "buffer busy waits",
        "read by other session",
        "gc buffer busy",
        "gc cr block busy",
        "gc current block busy",
        "buffer busy",
    ],
    "hot_object": [
        "enq: tx - row lock contention",
        "enq: tm - contention",
        "enq: tx - allocate extent",
        "enq: hw - contention",
        "enq: tt - contention",
        "enq: tx - index contention",
        "enq: st - contention",
        "enq: tm - index contention",
        "enq: us - contention",
        "row lock contention",
        "latch:",
        "cursor: pin s wait on x",
        "cursor: pin s wait on h",
        "cursor: pin x",
        "library cache lock",
        "library cache pin",
    ],
    "lock_contention": [
        "enq: tx",
        "enq: tm",
        "enq: hw",
        "enq: tt",
        "enq: st",
        "enq: us",
        "enq: ta",
        "enq: ci",
        "enq: dl",
        "enq: ff",
        "enq: fr",
        "enq: sc",
        "enq: sq",
        "row lock contention",
        "library cache lock",
        "library cache pin",
        "cursor: pin s wait on x",
    ],
    "parse_pressure": [
        "library cache",
        "cursor mutex",
        "cursor: pin",
        "hard parse",
        "shared pool",
        "parsing schema",
        "enq: ki",
        "object queue",
    ],
    "network_wait": [
        "sql*net message",
        "sql*net more data",
        "sql*net break/reset",
        "sql*net vector",
        "sql*net from client",
        "sql*net to client",
        "sql*net from dblink",
        "sql*net to dblink",
        "sql*net more data from",
        "sql*net more data to",
    ],
    "storage_io": [
        "db file sequential read",
        "db file scattered read",
        "direct path read",
        "direct path write",
        "log file parallel write",
        "log file sequential read",
        "control file",
        "control file sequential read",
        "control file single write",
        "control file parallel write",
        "db file parallel write",
        "db file single write",
        "file identify",
        "file open",
        "datafile init write",
    ],
    "rac_global_cache": [
        "gc ",
        "global cache",
        "gc cr",
        "gc current",
        "gc buffer",
        "gc grant",
        "gc quiesce",
        "gc cr block",
        "gc current block",
        "gc cr current block",
        "gc buffer busy",
        "gcs",
    ],
    "rac_gc_network": [
        "gc cr request",
        "gc current request",
        "gc cr multi block request",
        "gc current multi block request",
        "gc cr grant",
        "gc current grant",
        "gc cr grant cached",
        "gc current grant cached",
        "gc dm",
        "gcs_dmeter",
    ],
    "parallel_query": [
        "px deq",
        "px qref",
        "px send",
        "px receive",
        "px deq credit",
        "px deq: execute reply",
        "px deq: table q",
        "px deq: join ack",
        "px deq: kdi",
        "parallel query",
        "parallel query",
        "p0",
        "p1",
        "p2",
        "p3",
        "p4",
        "p5",
    ],
    "pga_memory": [
        "direct path read",
        "direct path write",
        "pga memory",
        "pga memory operation",
        "workarea memory",
        "workarea:",
        "sql area",
    ],
    "lob_operations": [
        "lob",
        "lob read",
        "lob write",
        "lob trim",
        "lob cleanup",
        "dbms_lock.sleep",
        "enq: hw - contention",
        "kdl",
        "kdcp",
        "kds",
        "kdi",
    ],
    "scheduler_resource": [
        "resmgr:",
        "resmgr:cpu quantum",
        "resmgr:pq",
        "resmgr: internal",
        "resmgr: active",
    ],
    "flashback_log": [
        "flashback log",
        "flashback buf free",
        "flashback log file sync",
        "recovery read",
        "recovery buffer",
    ],
    "adg_transport": [
        "rfs",
        "rfs write",
        "rfs write sync",
        "rfs open",
        "rfs close",
        "rfs dispatch",
        "rfs idle",
        "archive log",
        "redo transport",
        "gap",
        "gap fetch",
        "redofmt",
        "redomm",
        "managed standby",
        "log apply",
        "apply read",
    ],
    "undo_management": [
        "enq: tx - allocate",
        "undo segment",
        "enq: us",
        "enq: tx - application",
        "enq: tx - contention",
        "snapshot too old",
        "ora-01555",
        "ora-30036",
        "rollback",
        "transaction",
    ],

    # ============================================================
    # 生产高频案例新增语义组
    # ============================================================

    # --- Cursor/游标相关 ---
    "cursor_management": [
        "cursor: mutex s",
        "cursor: mutex x",
        "cursor: pin s",
        "cursor: pin s wait on x",
        "cursor: pin x",
        "cursor: pin x wait on s",
        "open cursor",
        "close cursor",
        "dml lock",
    ],

    # --- 分区/DDL 操作 ---
    "partition_ddl": [
        "enq: tx - index contention",
        "enq: tm - contention",
        "drop segment",
        "create segment",
        "space:",
        "space transaction",
        "segment",
        "ass",
    ],

    # --- Commit/同步写 ---
    "commit_sync": [
        "log file sync",
        "log buffer space",
        "log file sequential read",
        "log file parallel write",
        "lgwr",
        "commit batch",
        "commit cleanout",
        "cache cleanout",
        "write complete waits",
    ],

    # --- Java/JDBC 应用 ---
    "jdbc_connection": [
        "sql*net message from client",
        "sql*net message to client",
        "sql*net more data from client",
        "sql*net more data to client",
        "execution of java",
        "jobq",
        "joeq",
    ],

    # --- OLAP/DSS 大查询 ---
    "olap_large_query": [
        "direct path read temp",
        "direct path write temp",
        "db file scattered read",
        "sort",
        "hash",
        "bitmap",
        "buffer latch",
        "cache buffers lru",
    ],

    # --- 数据库健壮性 ---
    "database_health": [
        "background",
        "pmon",
        "smon",
        "dbwr",
        "lgwr",
        "ckpt",
        "arc",
        "mmnl",
        "mmon",
        "arcf",
        "arcc",
        "dbrf",
    ],

    # --- 归档/备份 ---
    "archive_backup": [
        "archive",
        " archival",
        "backup",
        "copy",
        "rman",
        "duplicate",
        "restore",
        "recover",
    ],

    # --- 统计信息收集 ---
    "stats_gathering": [
        "statspack",
        "statistics",
        "gather",
        "analyze",
        "auto",
        "jobq",
    ],

    # --- 物化视图/复制 ---
    "mview_replication": [
        "mv refresh",
        "materialized",
        "rep",
        "replication",
        "sync",
        "quiesce",
    ],

    # --- 索引维护 ---
    "index_maintenance": [
        "index",
        "index rebalance",
        "index split",
        "bitmap",
        "bitmap merge",
        "bbitmap",
    ],

    # --- Buffer Cache 活动 ---
    "buffer_cache_activity": [
        "cache buffers lru",
        "cache buffers chains",
        "cache buffer",
        "buffer lookup",
        "dirty",
        "free buffer",
    ],

    # --- Shared Pool 内存 ---
    "shared_pool_memory": [
        "shared pool",
        "library cache",
        "row cache",
        "dictionary",
        "enq: ki",
        "kgl",
        "kgc",
    ],

    # --- 日志切换频率 ---
    "log_switch_frequency": [
        "log file switch",
        "log file switch (checkpoint incomplete)",
        "log file switch (archiving needed)",
        "log file switch (clearing",
        "log file switch completion",
        "checkpoint",
    ],

    # --- 表访问 ---
    "table_access": [
        "table scan",
        "table fetch",
        "table fetch continued",
        "cluster",
        "table access",
        "index",
        "index fast full",
        "index full scan",
        "index unique scan",
        "index range scan",
    ],

    # --- 连接/会话建立 ---
    "connection_session": [
        "session connect",
        "sql*net ",
        "authentication",
        "os",
        "disk",
    ],

    # --- 并行 DDL ---
    "parallel_ddl": [
        "pq ",
        "px ",
        "parallel",
        "slave",
        "coordinator",
        "qc",
    ],

    # --- 12c+ 新特性 ---
    "twelve_c_new_features": [
        "in memory",
        "auto dop",
        "adaptive",
        "json",
        "flex",
        "pdb",
        "container",
    ],

    # --- 云/RAC扩展 ---
    "cloud_rac_extended": [
        "asm",
        "css",
        "cssd",
        "gipc",
        "skgxp",
        "net",
        "tcp",
        "sd",
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
