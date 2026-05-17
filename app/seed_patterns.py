"""
Oracle DBA 专家知识种子数据

基于资深 DBA 经验沉淀的诊断模式，涵盖 AWR 报告中最常见的性能问题场景。
每个模式包含：精确的触发条件（含具体阈值）、根因分析和解决方案。
"""

BUILTIN_PATTERNS = [
    # ==================== CPU 类 ====================
    {
        "name": "高逻辑读驱动 CPU 瓶颈",
        "conditions": "DB CPU 占 DB Time > 60%，Top SQL 中 Buffer Gets 远大于 Physical Reads（比率>10:1），logical_read_blocks_per_sec > 50000",
        "solution": "1) 分析 SQL ordered by Gets，找到 Gets/Exec 最高的 SQL；2) 检查执行计划是否走了全表扫描或低效索引；3) 添加复合索引覆盖查询列；4) 检查是否有多余的 JOIN 或子查询可合并",
        "confidence": 0.92,
    },
    {
        "name": "硬解析导致 CPU 过载",
        "conditions": "DB CPU 占比 > 40%，parse_time_pct_db_time > 15%，hard_parses_per_sec > 100，或 Top Events 出现 latch: shared pool / cursor: pin S wait on X",
        "solution": "1) 检查应用是否使用绑定变量（V$SQL 中 literal SQL 是否大量存在）；2) 设置 cursor_sharing=FORCE 作为临时方案；3) 增大 shared_pool_size；4) 使用 SPM 或 SQL Profile 固定执行计划",
        "confidence": 0.90,
    },
    {
        "name": "并行查询 CPU 风暴",
        "conditions": "DB CPU 异常高，但 Top SQL 的 Executions 很低（<10）而 CPU Time 极高，或出现 PX Deq Credit: send blkd 等待事件",
        "solution": "1) 检查是否误用了 parallel hint 或表级 degree 设置；2) 对 OLTP 系统禁用并行：ALTER TABLE ... NOPARALLEL；3) 设置 parallel_max_servers 限制并行度；4) 检查资源管理器是否限制了并行",
        "confidence": 0.85,
    },

    # ==================== I/O 类 ====================
    {
        "name": "全表扫描引发物理读风暴",
        "conditions": "physical_read_blocks_per_sec > 30000，Top Events 中 db file scattered read 占比高，Top SQL 的 Physical Reads >> Buffer Gets",
        "solution": "1) 找到全表扫描的 SQL（SQL ordered by Reads），检查执行计划；2) 缺少索引则添加；3) 如果是大表的小范围查询走了全表扫描，检查统计信息是否过期（DBMS_STATS.GATHER_TABLE_STATS）；4) 考虑使用分区表",
        "confidence": 0.92,
    },
    {
        "name": "直接路径读（绕过 Buffer Cache）",
        "conditions": "Top Events 出现 direct path read 或 direct path read temp，伴随大量 physical reads，AAS > CPU 核数 * 0.5",
        "solution": "1) 检查是否是并行查询引起的直接路径读；2) 如果是排序溢出（direct path read temp），增大 PGA_AGGREGATE_TARGET；3) 对小结果集的查询禁用并行；4) 检查 _serial_direct_read 参数（11g+ 可能默认走直接路径读）",
        "confidence": 0.85,
    },
    {
        "name": "存储 I/O 延迟过高",
        "conditions": "db file sequential read 的 Avg Wait > 10ms，db file scattered read 的 Avg Wait > 20ms，或 log file parallel write > 5ms",
        "solution": "1) 检查存储层面的 IOPS 和延迟（iostat / SAN 监控）；2) 排查是否共享存储有争用；3) 考虑将 redo/数据文件分离到不同磁盘组；4) 检查 ASM/文件系统的 I/O 调度策略；5) 如果是云环境，升级存储 IOPS 配额",
        "confidence": 0.88,
    },

    # ==================== Redo/Commit 类 ====================
    {
        "name": "log file sync 提交瓶颈",
        "conditions": "Top Events 中 log file sync 占 DB Time > 15%，commit_pct_db_time > 15%，commits_per_sec > 500",
        "solution": "1) 检查 redo log 是否放在慢存储上（应放 SSD/高速盘）；2) 增大 redo log 文件大小（减少切换频率）；3) 增加 log buffer；4) 应用层面减少提交频率（批量提交）；5) 检查 log file parallel write 延迟",
        "confidence": 0.90,
    },
    {
        "name": "redo log 切换风暴",
        "conditions": "Top Events 出现 log file switch (checkpoint incomplete) 或 log file switch (archiving needed)，redo size 非常高",
        "solution": "1) 增大 redo log 文件大小（建议每个 1-4GB）；2) 增加 redo log 组数量（至少 3-4 组）；3) 检查归档是否跟上（如果是归档模式）；4) 优化 DBWR 写出速度；5) 检查 FAST_START_MTTR_TARGET 设置",
        "confidence": 0.88,
    },

    # ==================== 锁/并发类 ====================
    {
        "name": "Enqueue 锁竞争热点",
        "conditions": "Top Events 出现 enq: TX - row lock contention 或 enq: TM - contention，等待时间显著",
        "solution": "1) TX 锁：检查长事务和热点行更新，优化事务粒度减少锁持有时间；2) TM 锁：检查是否缺少外键索引（导致子表全表锁定）；3) 使用 SELECT ... FOR UPDATE SKIP LOCKED 跳过锁等待；4) 考虑乐观并发控制",
        "confidence": 0.90,
    },
    {
        "name": "Latch 热点争用",
        "conditions": "Top Events 出现 latch: cache buffers chains / latch: shared pool / latch: redo allocation，Miss% > 1% 或 Wait Time > 0",
        "solution": "1) cache buffers chains：通常是热块问题，检查是否有高并发访问的索引/表，考虑 hash 分区或反向索引；2) shared pool：检查是否大量硬解析，使用绑定变量；3) redo allocation：增大 log buffer 或优化提交频率",
        "confidence": 0.88,
    },

    # ==================== 内存类 ====================
    {
        "name": "PGA 内存不足导致排序溢出",
        "conditions": "Top Events 出现 direct path write temp / direct path read temp，sorts (disk) > 0 且占比较高，或 PGA Advisory 显示 PGA Target 估计值远高于当前设置",
        "solution": "1) 增大 PGA_AGGREGATE_TARGET（建议物理内存的 20-40%）；2) 检查 Top SQL 是否有大排序操作（ORDER BY / GROUP BY / DISTINCT）；3) 优化 SQL 减少排序数据量；4) 检查 HASH_AREA_SIZE / SORT_AREA_SIZE（手动管理时）",
        "confidence": 0.88,
    },
    {
        "name": "Buffer Cache 命中率过低",
        "conditions": "physical_read_blocks_per_sec 与 logical_read_blocks_per_sec 比值 > 10%，或 Buffer Hit Ratio < 90%，大量 db file sequential read",
        "solution": "1) 增大 DB_CACHE_SIZE；2) 检查是否有大查询把热数据挤出缓存（使用 KEEP buffer pool 隔离热表）；3) 检查是否存在全表扫描频繁冲刷缓存；4) 使用 Buffer Cache Advisory 确定最优大小",
        "confidence": 0.85,
    },

    # ==================== SQL 执行计划类 ====================
    {
        "name": "执行计划突变（Plan Change）",
        "conditions": "某 SQL_ID 的 CPU Time 或 Elapsed Time 突然增大（与历史均值偏差 > 3 倍），但 SQL 文本未变",
        "solution": "1) 对比新旧执行计划（DBA_HIST_SQL_PLAN / V$SQL_PLAN）；2) 检查统计信息收集时间（可能统计信息更新导致计划变化）；3) 使用 SQL Plan Baseline 固定好的计划（DBMS_SPM.LOAD_PLANS_FROM_CURSOR_CACHE）；4) 检查是否有绑定变量窥探（Bind Peeking）问题",
        "confidence": 0.90,
    },
    {
        "name": "N+1 查询模式",
        "conditions": "Top SQL 中有多条 SQL_ID 的 SQL 文本结构相同（仅绑定变量不同），Executions 非常高（>10000），单次 Gets/Exec 很低（<100），但总 Gets 极高",
        "solution": "1) 这是典型的 N+1 查询，应用层在循环中逐条查询；2) 改写为批量查询（IN 子句或 JOIN）；3) 使用 BULK COLLECT / FORALL（PL/SQL）；4) 考虑使用物化视图或缓存层",
        "confidence": 0.88,
    },

    # ==================== RAC 类 ====================
    {
        "name": "RAC GC 网络瓶颈",
        "conditions": "Top Events 出现 gc buffer busy acquire/release / gc cr/current multi block request，等待时间显著，跨实例 AAS 不均衡",
        "solution": "1) 检查实例间互联网络（Interconnect）延迟和带宽（V$CLUSTER_INTERCONNECTS）；2) 优化数据分布减少跨实例访问（Service 绑定）；3) 检查 sequence cache 大小（减少跨实例争用）；4) 考虑增大 DB_FILES 和调整 undo 表空间",
        "confidence": 0.85,
    },

    # ==================== 综合场景类 ====================
    {
        "name": "批量任务与在线事务争用",
        "conditions": "AAS 在特定时段突然飙升，Load Profile 显示 executes_per_sec 大幅增加，同时出现 latch/enqueue 等待，负载类型为 Batch",
        "solution": "1) 分离批处理和 OLTP 负载到不同时段或不同实例；2) 使用 Resource Manager 限制批处理的 CPU 和并行度；3) 批处理使用 direct path 操作减少对 buffer cache 的冲击；4) 考虑使用 ADG（Active Data Guard）分流报表查询",
        "confidence": 0.85,
    },
    {
        "name": "统计信息过期导致全库性能下降",
        "conditions": "多个 SQL 的执行计划同时变化（Plan Change），整体 DB Time 上升，但应用无变更，发生在统计信息自动收集窗口之后",
        "solution": "1) 检查 DBA_TAB_STATISTICS 的 LAST_ANALYZED 时间；2) 对关键表锁定统计信息（DBMS_STATS.LOCK_TABLE_STATS）；3) 使用 SQL Plan Management 计划基线保护；4) 调整统计信息收集窗口避免高峰时段",
        "confidence": 0.88,
    },
    {
        "name": "连接风暴导致 shared pool 耗尽",
        "conditions": "Top Events 出现 latch: shared pool 或 library cache lock/pin，同时 sessions 数量异常高，SQL 执行效率骤降",
        "solution": "1) 使用连接池（如 DRCP / UCP / HikariCP）限制数据库连接数；2) 增大 shared_pool_size；3) 检查应用是否有连接泄漏；4) 设置 SESSIONS 和 PROCESSES 参数合理上限",
        "confidence": 0.85,
    },
    {
        "name": "LOB 大对象操作阻塞",
        "conditions": "Top Events 出现 enq: HW - contention 或 enq: TX - index contention，segment statistics 显示 LOB 段的高水位线争用",
        "solution": "1) 启用 LOB CACHE（ALTER TABLE ... MODIFY LOB(...) (CACHE)）；2) 使用 SecureFile LOB 替代 BasicFile；3) 预分配 LOB 空间减少高水位线推进；4) 分区大表的 LOB 列",
        "confidence": 0.82,
    },
    {
        "name": "临时表空间不足",
        "conditions": "Top Events 出现 direct path write temp / direct path read temp，或 ORA-01652 错误，temporary tablespace 使用率接近 100%",
        "solution": "1) 增大临时表空间大小；2) 检查哪些 SQL 产生大量排序/哈希操作；3) 优化 SQL 减少 temp 使用（避免 SELECT DISTINCT、大表笛卡尔积）；4) PGA_AGGREGATE_TARGET 设为自动管理",
        "confidence": 0.85,
    },

    # ==================== 高频真实案例（来自生产经验） ====================

    # --- 绑定变量窥探 (Bind Peeking) ---
    {
        "name": "绑定变量窥探导致计划抖动",
        "conditions": "某 SQL_ID 的 Elapsed Time 在不同时段差异巨大（>10倍），Executions 正常，SQL 文本使用绑定变量，但执行计划可能在全表扫描和索引访问之间切换",
        "solution": "1) 检查 V$SQL 中 IS_BIND_SENSITIVE=Y 和 IS_BIND_AWARE=N 的 SQL；2) 启用 Adaptive Cursor Sharing（默认 11g+）；3) 使用 SQL Plan Baseline 固定最优计划；4) 对倾斜数据列使用直方图统计",
        "confidence": 0.88,
    },

    # --- 高频 COMMIT 的 Java/Spring 应用 ---
    {
        "name": "Spring 自动提交模式导致 log file sync 风暴",
        "conditions": "log file sync 占 DB Time > 20%，commits_per_sec > 1000，redo write avg size < 512 bytes，应用使用 Java/Spring 框架",
        "solution": "1) 检查 JDBC 连接是否开启了 autoCommit=true（Spring 默认行为）；2) 在事务级别控制提交频率；3) 将 autoCommit=false，使用 @Transactional 注解；4) 增大 redo log 到 2-4GB 并放在 SSD",
        "confidence": 0.92,
    },

    # --- Sequence 争用 ---
    {
        "name": "Sequence 缓存不足导致争用",
        "conditions": "Top Events 出现 enq: SQ - contention 或 latch: shared pool 伴随 sequence 相关等待，应用大量使用序列生成主键",
        "solution": "1) 增大 Sequence Cache：ALTER SEQUENCE ... CACHE 1000（默认 20 太小）；2) RAC 环境必须用 CACHE + NOORDER；3) 考虑使用 IDENTITY 列（12c+）替代 Sequence；4) 批量插入使用 CACHE 减少争用",
        "confidence": 0.90,
    },

    # --- 外键缺失索引导致 TM 锁 ---
    {
        "name": "外键缺少索引导致全表锁定",
        "conditions": "Top Events 出现 enq: TM - contention，且阻塞链路涉及子表删除/更新操作，Application wait class 占比高",
        "solution": "1) 检查所有外键是否创建了索引：SELECT table_name, column_name FROM all_cons_columns WHERE constraint_name IN (SELECT constraint_name FROM all_constraints WHERE constraint_type='R' AND owner='SCHEMA')；2) 缺少索引则创建：CREATE INDEX idx_child_fk ON child_table(parent_id)；3) 这是最常见的锁问题根因之一",
        "confidence": 0.95,
    },

    # --- 索引高度过高 ---
    {
        "name": "索引高度过高导致单块读延迟增加",
        "conditions": "db file sequential read 平均等待 > 8ms，SQL 的 Gets/Exec 中等（100-1000），但执行时间偏长，表数据量 > 1亿行",
        "solution": "1) 检查索引高度：ANALYZE INDEX ... VALIDATE STRUCTURE → 查看 HEIGHT 列（>4 需关注）；2) 在线重建索引：ALTER INDEX ... REBUILD ONLINE；3) 考虑分区索引降低高度；4) 12c+ 可以使用 Advanced Index Compression",
        "confidence": 0.82,
    },

    # --- 分区表全分区扫描 ---
    {
        "name": "分区裁剪失效导致全分区扫描",
        "conditions": "SQL 访问分区表但出现 PARTITION ALL 或 PARTITION RANGE ALL，physical reads 很高，WHERE 条件包含分区键但类型不匹配或使用了函数",
        "solution": "1) 检查 WHERE 条件中分区键是否使用了函数（TO_DATE/TO_CHAR），这会导致分区裁剪失效；2) 确保分区键列的数据类型和比较值类型一致；3) 使用 EXPLAIN PLAN 检查 Pstart/Pstop 是否为 KEY 而非 ALL；4) 考虑使用虚拟列分区",
        "confidence": 0.88,
    },

    # --- 大表 UPDATE 导致 undo/redo 暴涨 ---
    {
        "name": "大表全量 UPDATE 导致 undo/redo 风暴",
        "conditions": "redo_size_per_sec 异常高（>10MB/s），write_io_mb_per_sec 很高，但 AAS 不一定很高（可能是后台写），Top SQL 中有大表 UPDATE 语句",
        "solution": "1) 检查是否有大表的全量 UPDATE（即使只改一列也会写所有行的 undo/redo）；2) 改为分批 UPDATE（每批 10000 行并 COMMIT）；3) 使用 DBMS_REDEFINITION 在线重定义只保留需要的列；4) 对历史数据使用分区裁剪后 TRUNCATE 而非 DELETE",
        "confidence": 0.88,
    },

    # --- 隐式类型转换导致索引失效 ---
    {
        "name": "隐式类型转换导致索引失效",
        "conditions": "SQL 中 WHERE 条件列是 NUMBER 类型但比较值用字符串，或 VARCHAR2 列比较 NUMBER，导致全表扫描。Top SQL 的 Gets/Exec 很高且 SQL 文本含引号数字",
        "solution": "1) 检查 SQL 文本中是否有 '123'（字符串）与 NUMBER 列比较；2) 修正为匹配类型：WHERE num_col = 123 而非 WHERE num_col = '123'；3) 使用函数索引如果无法改代码：CREATE INDEX ... ON table(TO_CHAR(num_col))；4) 检查 V$SQL_PLAN 的 ACCESS_PREDICATES 列",
        "confidence": 0.90,
    },

    # --- DBWR 写出瓶颈 ---
    {
        "name": "DBWR 写出能力不足",
        "conditions": "Top Events 出现 free buffer waits 或 write complete waits，说明 DBWR 跟不上脏块产生速度。通常伴随高物理写入",
        "solution": "1) 增加 DBWR 进程数：db_writer_processes（默认 CPU_COUNT/8，可增大）；2) 检查异步 I/O 是否启用（filesystemio_options=SETALL）；3) 增大 DB_CACHE_SIZE 减少写频率；4) 检查存储写延迟（iostat 的 await 值）",
        "confidence": 0.85,
    },

    # --- 统计信息收集时间不当 ---
    {
        "name": "统计信息在业务高峰收集导致性能抖动",
        "conditions": "DB Time 在特定时段（通常凌晨或中午）突然飙升，Top Events 中出现 DB CPU 和 latch 争用，但该时段不是业务高峰。DBA 自动任务窗口与业务时段重叠",
        "solution": "1) 检查 DBA_SCHEDULER_JOBS 中统计信息收集任务的时间；2) 将自动收集窗口调整到业务低峰期；3) 对关键表使用 LOCK_TABLE_STATS 避免自动收集；4) 使用 SET_TABLE_PREFS 设置增量收集",
        "confidence": 0.85,
    },

    # --- ADG 备库 apply lag ---
    {
        "name": "ADG 备库 apply lag 导致查询数据过期",
        "conditions": "RAC 环境中某一实例的 AWR 显示大量 'RFS' 进程和 'log file sequential read' 等待，同时有 'recovery' 相关等待",
        "solution": "1) 检查 V$ARCHIVE_DEST_STATUS 的 APPLIED_SCN 和最新的 SEQUENCE#；2) 增大备库的并行 apply 进程（ALTER DATABASE RECOVER MANAGED STANDBY DATABASE PARALLEL 8）；3) 检查网络传输延迟；4) 考虑使用 Far Sync 减少传输延迟",
        "confidence": 0.78,
    },

    # --- Materialized View 刷新争用 ---
    {
        "name": "物化视图刷新导致锁争用",
        "conditions": "定期出现 enq: TM - contention 和大量 redo 产生，同时有物化视图刷新任务在执行。Application wait class 异常高",
        "solution": "1) 将物化视图刷新改为 FAST REFRESH 而非 COMPLETE REFRESH；2) 使用 DBMS_MVIEW.REFRESH 的 ATOMIC_REFRESH=FALSE 减少锁持有时间；3) 错开刷新时间与业务高峰；4) 考虑使用增量刷新日志",
        "confidence": 0.82,
    },

    # --- SQL 注入导致硬解析风暴 ---
    {
        "name": "SQL 注入或字符串拼接导致硬解析风暴",
        "conditions": "hard_parses_per_sec > 500，shared pool 使用率高，library cache 命中率 < 90%，V$SQL 中同一 SQL 结构但有大量不同的 SQL_ID（literal 不同）",
        "solution": "1) 使用绑定变量是根本方案；2) 临时设置 cursor_sharing=FORCE；3) 增大 shared_pool_size 到 SGA 的 30-40%；4) 检查应用日志查找拼接 SQL 的代码位置；5) 使用 SPM/SQL Profile 固定关键 SQL 的执行计划",
        "confidence": 0.92,
    },

    # --- 直接路径写 TEMP 与 PGA 关联 ---
    {
        "name": "Hash Join 溢出到 TEMP 导致 I/O 放大",
        "conditions": "Top Events 出现 direct path read temp + direct path write temp，TEMP 等待占比 > 5%，Top SQL 中有大表之间的 Hash Join",
        "solution": "1) 增大 PGA_AGGREGATE_TARGET；2) 检查 Hash Join 的驱动表是否选择正确（小表作为驱动表）；3) 添加合适的索引将 Hash Join 转为 Nested Loop；4) 使用 /*+ USE_HASH */ hint 控制 Join 策略；5) 对大表考虑分区 Join",
        "confidence": 0.88,
    },

    # --- RAC 跨实例热块 ---
    {
        "name": "RAC 跨实例热点索引块争用",
        "conditions": "RAC 环境中 gc buffer busy acquire/release 占比高，同时有 latch: cache buffers chains 争用，某个索引段的 logical reads 极高",
        "solution": "1) 使用 Reverse Key Index 打散索引块的并发争用；2) 使用 Hash Partition 分散热块；3) 将关联业务通过 Service 绑定到同一实例；4) 增大 Sequence Cache 减少跨实例序列争用；5) 检查 Interconnect 带宽（建议 ≥10Gbps）",
        "confidence": 0.88,
    },

    # --- 长事务导致 undo 空间暴涨 ---
    {
        "name": "长事务导致 undo 空间不足和 ORA-01555",
        "conditions": "出现 ORA-01555 snapshot too old 或 undo tablespace 使用率持续增长，Top Events 可能出现 enq: US - contention",
        "solution": "1) 检查长事务：V$TRANSACTION 中 START_TIME 最早的事务；2) 增大 UNDO_TABLESPACE 和 UNDO_RETENTION；3) 应用层避免大事务（分批 COMMIT）；4) 使用 Guaranteed Undo Retention 确保查询一致性；5) 检查 LOB 的 RETENTION 设置",
        "confidence": 0.90,
    },

    # --- Cursor 泄漏 ---
    {
        "name": "应用游标泄漏导致 ORA-01000",
        "conditions": "open_cursors_per_sec 持续增长，出现 ORA-01000 maximum open cursors exceeded，library cache 中大量子游标",
        "solution": "1) 检查 V$OPEN_CURSOR 按 SID 统计游标数；2) 增大 OPEN_CURSORS 参数（临时方案）；3) 检查应用代码是否正确关闭 PreparedStatement/ResultSet；4) 检查 PL/SQL 是否在循环中执行动态 SQL 未关闭游标",
        "confidence": 0.88,
    },

    # --- 高并发小事务的最佳实践 ---
    {
        "name": "高并发小事务系统的 log file sync 优化",
        "conditions": "commits_per_sec > 1000，log file sync avg > 3ms，但单个事务很小（redo < 1KB），典型 OLTP 系统",
        "solution": "1) 将 redo log 放在最快的 SSD/NVMe 上；2) 增大 log_buffer（64MB+）；3) 启用 LGWR 的 I/O 从属进程（11g: _lgwr_async_io=true）；4) commit_write=NOWAIT 可显著减少等待但有数据丢失风险；5) Group Commit 是自动的，无需额外配置",
        "confidence": 0.85,
    },

    # --- SQL Monitor 报告使用 ---
    {
        "name": "使用 SQL Monitor 深度分析 Top SQL",
        "conditions": "某 SQL_ID 的 Elapsed Time > 5 秒且仍在执行中（11g+），或 DBA_HIST_SQLSTAT 中有该 SQL 的历史记录",
        "solution": "1) 获取 SQL Monitor 报告：SELECT DBMS_SQLTUNE.REPORT_SQL_MONITOR(sql_id=>'xxx') FROM dual；2) 查看实时执行进度、每步操作的耗时和行数；3) 对比 Rows vs Estimate 判断统计信息准确性；4) 使用 DBMS_SQLTUNE.REPORT_SQL_MONITOR_LIST 查看所有监控中的 SQL",
        "confidence": 0.92,
    },

    # --- 自适应统计信息 (12c+) ---
    {
        "name": "自适应统计信息导致执行计划不稳定",
        "conditions": "12c+ 数据库中出现 SQL 执行计划频繁变化，V$SQL 中 IS_REOPTIMIZABLE=Y，执行后 Feedback 重新优化",
        "solution": "1) 理解 Adaptive Statistics：自适应游标共享、SQL Plan Directives、动态采样；2) 检查 DBA_SQL_PLAN_DIRECTIVES 的状态；3) 使用 SQL Plan Baseline 固定已知好的计划；4) 对关键查询关闭自适应：ALTER SYSTEM SET optimizer_adaptive_statistics=FALSE",
        "confidence": 0.82,
    },

    # ==================== 高级场景：Exadata ====================
    {
        "name": "Exadata Smart Scan 未生效",
        "conditions": "Exadata 环境中 physical reads 很高但 cell physical IO interconnect bytes 很低，或 cell offload efficiency < 50%",
        "solution": "1) 检查是否使用了 Direct Path Read（绕过 Smart Scan）；2) 确认表未使用 NO_STORAGE 选项；3) 检查是否启用了 offload（_serial_direct_read=FALSE 可能绕过）；4) 检查存储索引是否在目标列上；5) 确认 Cell 的 Flash Cache 和 IORM 配置",
        "confidence": 0.82,
    },
    {
        "name": "Exadata Flash Cache 命中率低",
        "conditions": "Exadata 环境中 cell flash cache read hits / cell logical read requests < 70%，physical reads 仍然很高",
        "solution": "1) 检查 Keep/Default Flash Cache 配置；2) 将热表/索引放入 Keep Flash Cache：ALTER TABLE ... STORAGE(CELL_FLASH_CACHE KEEP)；3) 检查 Flash Cache 大小是否足够（MEG.CELL_FLASH_CACHE 使用情况）；4) 检查 IORM 是否限制了数据库级别的 Flash Cache 分配",
        "confidence": 0.80,
    },
    {
        "name": "Exadata I/O 资源管理器（IORM）限流",
        "conditions": "Top Events 出现 resmgr:ioq 或 cell I/O 延迟异常高，但 Cell 硬件负载正常",
        "solution": "1) 检查 IORM 配置：CELLCLI> LIST IORMPLAN DETAIL；2) 检查当前数据库是否被 IORM 限流；3) 调整 IORM plan 增加数据库的 I/O 份额；4) 检查是否在维护窗口期间 IORM 分配不均",
        "confidence": 0.78,
    },

    # ==================== 高级场景：云环境 ====================
    {
        "name": "AWS RDS IOPS 限流导致延迟飙升",
        "conditions": "AWS RDS 环境中 db file sequential read avg > 15ms，Read IOPS 接近卷 IOPS 上限，或 EBS Volume Queue Length 持续 > 4",
        "solution": "1) 检查 EBS 卷类型（gp2 有 burst bucket，gp3/io2 可预配置 IOPS）；2) 升级到 gp3 或 io2 以获得一致 IOPS；3) 减少 I/O 密集 SQL 或优化 SQL 减少物理读；4) 检查 RDS Performance Insights 的 I/O 等待分布",
        "confidence": 0.85,
    },
    {
        "name": "OCI 数据库 IOPS 配额不足",
        "conditions": "OCI 环境中存储延迟异常高，IOPS 接近 shape 的 IOPS 上限（DB Systems 各 shape 有不同限制）",
        "solution": "1) 检查 shape 的 IOPS 限制（2-socket OCPU = 6000 IOPS baseline）；2) 升级 shape 或使用 Higher Performance 存储层；3) 检查是否可使用 ASM flex disk group 均衡 I/O 分布；4) 对 I/O 密集查询优化 SQL 减少物理读",
        "confidence": 0.80,
    },
    {
        "name": "云数据库网络延迟影响 SQL*Net",
        "conditions": "SQL*Net message from/to client 占 DB Time > 10%，Avg Wait > 5ms，应用与数据库不在同一可用区或 Region",
        "solution": "1) 将应用部署到与数据库同 Region/可用区；2) 检查 SQL*Net round trips 数量；3) 增大 arraysize/fetch size 减少往返次数；4) 使用连接池减少新建连接的网络握手；5) 检查 SDU 配置（增大到 32767）",
        "confidence": 0.82,
    },

    # ==================== 高级场景：多租户 (CDB/PDB) ====================
    {
        "name": "PDB 资源管理器限流",
        "conditions": "Top Events 出现 resmgr:cpu quantum 或 resmgr:pq 或 resmgr:I/O，PDB 级别 AWR 显示资源管理器等待",
        "solution": "1) 检查 CDB Resource Plan 配置：SELECT * FROM DBA_CDB_RSRC_PLAN_DIRECTIVES；2) 调整 PDB 的 CPU_SHARE 和 I/O 限额；3) 检查是否某个 PDB 占用了大量资源影响其他 PDB；4) 考虑使用 MAX_UTILIZATION_LIMIT 限制单个 PDB",
        "confidence": 0.80,
    },
    {
        "name": "PDB 共享池争用影响其他 PDB",
        "conditions": "CDB 级别 AWR 显示 shared pool 使用率 > 90%，多个 PDB 同时有硬解析高的问题",
        "solution": "1) 检查各 PDB 的 shared pool 使用：SELECT * FROM V$SGASTAT WHERE CON_ID > 2；2) 使用 PDB 级别 SGA_TARGET 限制单个 PDB 内存；3) 各 PDB 分别使用绑定变量减少硬解析；4) 增大 CDB 级 SGA_TARGET",
        "confidence": 0.78,
    },

    # ==================== 高级场景：In-Memory Column Store ====================
    {
        "name": "In-Memory 列存未被查询使用",
        "conditions": "启用了 In-Memory Option 但 IM scan segments / IM scan rows per second = 0，Top SQL 仍然有大量 buffer gets",
        "solution": "1) 检查表是否设置了 INMEMORY 属性：SELECT table_name, inmemory FROM dba_tables WHERE inmemory='ENABLED'；2) 确认 populate 完成：SELECT * FROM V$IM_SEGMENTS；3) 检查查询 hint 是否禁用了 IM（NO_INMEMORY）；4) 确认 optimizer_features_enable >= 12.1",
        "confidence": 0.78,
    },
    {
        "name": "In-Memory 列存填充争用",
        "conditions": "Top Events 出现 'in memory area' 或 'in memory populate'，IM populate 与业务查询争用 CPU",
        "solution": "1) 调整 IMCS populate 策略为 PRIORITY LOW/MEDIUM 减少初始填充冲击；2) 使用 IM expression 限制填充列；3) 分批填充大表而非一次性加载；4) 增大 INMEMORY_SIZE 避免频繁淘汰",
        "confidence": 0.75,
    },

    # ==================== 高级场景：PL/SQL 性能 ====================
    {
        "name": "PL/SQL 上下文切换开销过大",
        "conditions": "Top SQL 中有 PL/SQL 调用（CALL 语句），SQL*Net round trips 很高，但单次 SQL 执行时间不长",
        "solution": "1) 检查 PL/SQL 代码中是否有循环内单条 SQL（应改为 BULK COLLECT + FORALL）；2) 减少 PL/SQL 到 SQL 的上下文切换次数；3) 使用 PIPELINED 函数替代逐行处理；4) 使用 DBMS_PARALLEL_EXECUTE 并行化大操作",
        "confidence": 0.82,
    },
    {
        "name": "PL/SQL 缺少 BULK COLLECT 导致逐行处理",
        "conditions": "Top SQL 的 Executions 极高（>100000）但 Gets/Exec 很低（<10），CPU Time 与 Executions 成正比",
        "solution": "1) 将 PL/SQL 中的 SELECT INTO / FETCH 改为 BULK COLLECT INTO；2) 将 INSERT/UPDATE/DELETE 循环改为 FORALL 批量操作；3) 使用 RETURNING BULK COLLECT INTO 减少额外查询；4) 增大 ARRAYSIZE 参数",
        "confidence": 0.88,
    },

    # ==================== 高级场景：LOB 性能 ====================
    {
        "name": "BasicFile LOB 性能劣化",
        "conditions": "Top Events 出现 enq: HW - contention 或 enq: TX - index contention，段统计显示 LOB 段高水位线争用",
        "solution": "1) 迁移到 SecureFile LOB：ALTER TABLE ... MODIFY LOB(col) (STORE AS SECUREFILE)；2) 启用 LOB CACHE：ALTER TABLE ... MODIFY LOB(col) (CACHE)；3) 启用 LOB 压缩：ALTER TABLE ... MODIFY LOB(col) (COMPRESS HIGH)；4) 预分配 LOB 空间减少高水位推进",
        "confidence": 0.85,
    },

    # ==================== 高级场景：Global Temporary Table ====================
    {
        "name": "GTT 滥用导致 TEMP 表空间压力",
        "conditions": "TEMP 等待占比高，SQL 中大量使用 GLOBAL TEMPORARY TABLE，TEMP 表空间使用率接近 100%",
        "solution": "1) 检查 GTT 的 ON COMMIT DELETE ROWS vs ON COMMIT PRESERVE ROWS；2) 对频繁插入的 GTT 考虑使用普通表 + 定期 TRUNCATE；3) 增大 TEMP 表空间；4) 优化使用 GTT 的 SQL 减少数据量；5) 检查是否有未提交事务导致 GTT 数据累积",
        "confidence": 0.78,
    },

    # ==================== 高级场景：Undo ====================
    {
        "name": "Undo 表空间自动扩展导致磁盘耗尽",
        "conditions": "Undo 表空间使用率持续增长，ORA-30036 unable to extend segment 或 undo tablespace autoextend 频繁触发",
        "solution": "1) 检查长事务：SELECT * FROM V$TRANSACTION ORDER BY START_TIME ASC；2) 回滚或提交长事务；3) 设置 UNDO_RETENTION 合理值；4) 使用固定大小 Undo 表空间 + GUARANTEE UNDO RETENTION；5) 检查 LOB RETENTION 设置是否过大",
        "confidence": 0.85,
    },

    # ==================== 高级场景：SQL Plan Management ====================
    {
        "name": "SQL Plan Baseline 导致计划退化",
        "conditions": "某 SQL 有 Accepted 的 Plan Baseline 但执行时间比无 Baseline 时更慢，或 DBA_SQL_PLAN_BASELINES 中 FIXED=YES 的计划不是最优",
        "solution": "1) 检查 Plan Baseline：SELECT * FROM DBA_SQL_PLAN_BASELINES WHERE SQL_HANDLE='...'；2) Evolve 新计划：DBMS_SPM.EVOLVE_SQL_PLAN_BASELINE；3) 删除退化的 Baseline：DBMS_SPM.DROP_SQL_PLAN_BASELINE；4) 对固定计划考虑 UNFIX 后重新 Evolve",
        "confidence": 0.80,
    },

    # ==================== 高级场景：JSON/XML 操作 ====================
    {
        "name": "JSON/XML 大对象查询性能差",
        "conditions": "Top SQL 中有 JSON_VALUE/JSON_QUERY/XMLTYPE 操作，Buffer Gets 极高，可能伴随 LOB 读取",
        "solution": "1) 对 JSON 查询列创建 Search Index：CREATE SEARCH INDEX idx ON table(json_col)；2) 对高频查询路径创建函数索引：CREATE INDEX idx ON table(JSON_VALUE(json_col, '$.key'))；3) 12c+ 使用 IS JSON 约束优化；4) XMLType 使用 XMLIndex 或 Binary XML 存储",
        "confidence": 0.78,
    },

    # ==================== 高级场景：物化视图刷新 ====================
    {
        "name": "物化视图 Complete Refresh 锁定基表",
        "conditions": "定期出现 TM 锁等待和大量 redo 产生，对应时段有物化视图刷新任务在执行",
        "solution": "1) 改为 FAST REFRESH（需要 MV Log）；2) 使用 DBMS_MVIEW.REFRESH 的 ATOMIC_REFRESH=FALSE 减少锁时间；3) 错开刷新时间与业务高峰；4) 使用增量刷新日志；5) 12c+ 使用 Real-Time MV 减少刷新需求",
        "confidence": 0.82,
    },

    # ==================== 高级场景：Data Pump ====================
    {
        "name": "Data Pump 导出导入性能差",
        "conditions": "expdp/impdp 运行期间出现高 I/O、全表扫描和 direct path read/write，系统响应变慢",
        "solution": "1) 使用 PARALLEL 参数加速（但注意 CPU 和 I/O 限制）；2) 对大表使用分区 EXCLUDE/INCLUDE 减少单次数据量；3) 使用 FLASHBACK_SCN 避免一致性锁；4) impdp 使用 TABLE_EXISTS_ACTION=TRUNCATE 减少 redo；5) 专用 buffer_size 调整传输效率",
        "confidence": 0.75,
    },

    # ====================================================================
    # 扩展专家模式 v2.0 — 覆盖新因果图节点和深度生产场景
    # ====================================================================

    # ==================== 因果传播链模式 ====================
    {
        "name": "CPU→Latch 因果传播链",
        "conditions": "DB CPU > 50%，同时 latch: cache buffers chains 等待 > 1%，logical_read_blocks_per_sec > 100000。高逻辑读 SQL 制造了 latch 争用",
        "solution": "1) 根因是高逻辑读 SQL 而非 latch 本身；2) 优化 Gets/Exec 最高的 SQL 减少逻辑读量；3) latch 争用会随逻辑读下降自然消失；4) 如果无法快速优化 SQL，增大 _db_block_hash_buckets 作为临时缓解",
        "confidence": 0.90,
    },
    {
        "name": "PGA→TEMP→Storage 三层传播链",
        "conditions": "PGA_AGGREGATE_TARGET 不足，sorts (disk) > 0 或 hash join overflow，同时 direct path read/write temp 占比 > 3%，存储 I/O 延迟上升",
        "solution": "1) 根因是 PGA 不足导致工作区溢出；2) 增大 PGA_AGGREGATE_TARGET 是第一步；3) TEMP I/O 和存储压力会随 PGA 增大自然缓解；4) 同时检查 Hash Join 驱动表选择是否正确",
        "confidence": 0.88,
    },
    {
        "name": "Access Path→TEMP→Redo 大查询传播链",
        "conditions": "全表扫描或 direct path read 占比高，同时 TEMP 等待 > 3%，redo size > 5MB/s。大查询同时制造读 I/O、排序溢出和 redo 压力",
        "solution": "1) 根因是 SQL 访问路径不合理；2) 优先为大查询添加索引或分区裁剪；3) 访问路径修正后 TEMP 溢出和 redo 产出量会同步下降；4) 不要单独调 PGA 或 redo log 大小——那是治标",
        "confidence": 0.88,
    },
    {
        "name": "Storage→Redo→Commit 存储瓶颈传播链",
        "conditions": "db file sequential read avg > 10ms，同时 log file parallel write avg > 5ms，log file sync avg > 10ms。存储慢导致 redo 写入和提交全部变慢",
        "solution": "1) 根因是底层存储延迟；2) 将 redo log 迁移到独立的高速存储（SSD/NVMe）；3) 数据文件存储也需要升级或优化 I/O 路径；4) 在存储未升级前，减少提交频率可以缓解 log file sync",
        "confidence": 0.90,
    },
    {
        "name": "Parse→Latch→CPU 解析传播链",
        "conditions": "hard_parses_per_sec > 200，latch: shared pool 争用明显，DB CPU 占比 > 40%。硬解析消耗 CPU 并引发共享池 latch 争用",
        "solution": "1) 根因是缺少绑定变量导致硬解析；2) 使用绑定变量是根本方案；3) 临时缓解：cursor_sharing=FORCE + 增大 shared_pool_size；4) latch 和 CPU 问题会随硬解析下降自然消失",
        "confidence": 0.92,
    },
    {
        "name": "RAC Network→GC→Lock 跨实例传播链",
        "conditions": "RAC 环境中 gc cr/current request 平均等待 > 5ms，gc buffer busy > 2%，同时出现跨实例的 enq: TX 锁等待",
        "solution": "1) 检查互联网络延迟和带宽（建议 ≥10Gbps + RDS/UDP）；2) 将关联业务通过 Service 绑定到同一实例减少跨实例访问；3) 如果是热点对象，使用 Hash Partition 分散数据块；4) 增大 Sequence Cache 减少跨实例序列争用",
        "confidence": 0.85,
    },
    {
        "name": "Parallel→TEMP+RAC GC 并行查询传播链",
        "conditions": "并行查询的 DOP > CPU 核数，TEMP 等待 > 5%，RAC 环境出现 PX Deq: Table Q 和 gc buffer busy 等待",
        "solution": "1) 限制并行度不超过实例 CPU 核数的 50%；2) RAC 环境使用 PARALLEL_FORCE_LOCAL=TRUE 避免跨实例并行；3) 增大 PGA 减少并行排序溢出；4) 对非必要的大表并行使用 NOPARALLEL",
        "confidence": 0.85,
    },

    # ==================== Buffer Cache 深度场景 ====================
    {
        "name": "Buffer Cache 被大查询冲刷",
        "conditions": "Buffer Hit Ratio 突然下降（从 >99% 降到 <95%），同时有大查询走 scattered read 或 direct path read 转为 cached read",
        "solution": "1) 使用 KEEP buffer pool 隔离热表：ALTER TABLE hot_table STORAGE(BUFFER_POOL KEEP)；2) 设置 DB_KEEP_CACHE_SIZE 专用缓冲池；3) 对大表报表查询强制 parallel + direct path（不经过 cache）；4) 检查 _serial_direct_read 参数",
        "confidence": 0.85,
    },
    {
        "name": "Buffer Cache 多实例 SGA 争用",
        "conditions": "RAC 环境中某实例 Buffer Hit Ratio < 95% 但另一实例正常，db file sequential read 集中在低命中率实例",
        "solution": "1) 检查是否业务负载不均衡导致某实例热数据超过缓存；2) 使用 Service 均衡各实例负载；3) 单独增大低命中率实例的 DB_CACHE_SIZE；4) 检查是否有大查询只在某实例执行",
        "confidence": 0.82,
    },

    # ==================== DBWR 深度场景 ====================
    {
        "name": "DBWR Checkpoint 写出延迟导致日志切换阻塞",
        "conditions": "log file switch (checkpoint incomplete) 出现，同时 db file parallel write 延迟 > 10ms，DBWR 写出速度跟不上 redo 产出速度",
        "solution": "1) 增加 db_writer_processes（建议 CPU_COUNT/8 到 CPU_COUNT/4）；2) 确保数据文件存储开启异步 I/O（filesystemio_options=SETALL）；3) 增大 redo log 到 2-4GB 给 DBWR 更多 checkpoint 窗口；4) 检查存储写队列深度",
        "confidence": 0.88,
    },
    {
        "name": "异步 I/O 未启用导致 DBWR 串行写",
        "conditions": "db file parallel write 延迟偏高但存储硬件正常，DBWR 单进程 CPU 使用率高，free buffer waits 偶现",
        "solution": "1) 检查 filesystemio_options 参数（应为 SETALL 或 ASYNCH）；2) ASM 环境确认底层操作系统支持 AIO（libaio）；3) 检查 disk_asynch_io 参数是否为 TRUE；4) AIX 环境检查 aio_max_requests 是否足够",
        "confidence": 0.85,
    },

    # ==================== 锁竞争深度场景 ====================
    {
        "name": "外键级联删除导致子表全表锁",
        "conditions": "enq: TM - contention 出现在子表上，主表有 DELETE 或 UPDATE 操作，子表的外键列缺少索引",
        "solution": "1) 这是最常见的 TM 锁根因；2) 在所有外键列上创建索引；3) 检查方法：对比 ALL_CONS_COLUMNS（R 类型）和 ALL_IND_COLUMNS；4) 创建脚本自动检测缺失的外键索引",
        "confidence": 0.95,
    },
    {
        "name": "热点行更新导致 TX 行锁堆积",
        "conditions": "enq: TX - row lock contention 持续出现，Top SQL 中有频繁更新同一行的 UPDATE 语句（如余额表、计数器表）",
        "solution": "1) 重新设计热点表结构（如将单行余额拆分为多行分桶）；2) 使用 SELECT ... FOR UPDATE SKIP LOCKED 跳过被锁行；3) 引入应用层缓存减少数据库更新频率；4) 对计数器使用 Oracle 12c+ 的 DBMS_LOCK.SLEEP + AUTONOMOUS_TRANSACTION",
        "confidence": 0.90,
    },
    {
        "name": "ITL（Interested Transaction List）等待",
        "conditions": "enq: TX - allocate ITL entry 出现，某个数据块的并发更新事务数超过 INITRANS 限制",
        "solution": "1) 增大表的 INITRANS（ALTER TABLE ... INITRANS 16 MAXTRANS 255）；2) 索引的 INITRANS 也需调整；3) 重建对象使新 INITRANS 对所有块生效；4) 对高并发更新表建议 INITRANS ≥ 16",
        "confidence": 0.88,
    },
    {
        "name": "DDL 锁阻塞 DML 操作",
        "conditions": "enq: TM - contention 或 library cache lock 出现在 DDL 操作（CREATE INDEX、ALTER TABLE）期间，阻塞了正常 DML",
        "solution": "1) 使用 ONLINE 选项：CREATE INDEX ... ONLINE / ALTER TABLE ... ONLINE；2) 在业务低峰执行 DDL；3) 使用 DBMS_REDEFINITION 在线重定义避免长时间锁；4) 设置 DDL_LOCK_TIMEOUT 避免无限等待",
        "confidence": 0.88,
    },

    # ==================== 游标管理深度场景 ====================
    {
        "name": "子游标过多导致 cursor: mutex 争用",
        "conditions": "cursor: mutex S 或 cursor: mutex X 等待出现，V$SQL 中某些 SQL 的 VERSION_COUNT > 100，library cache 争用",
        "solution": "1) 检查高 VERSION_COUNT 的 SQL：SELECT sql_id, version_count FROM V$SQLAREA WHERE version_count > 50；2) 常见原因：不同 schema 执行同一 SQL、optimizer_mismatch、bind_mismatch；3) 使用 V$SQL_SHARED_CURSOR 查看不共享原因；4) 设置 _cursor_obsolete_threshold 限制子游标数",
        "confidence": 0.88,
    },
    {
        "name": "Adaptive Cursor Sharing 引发执行计划震荡",
        "conditions": "SQL 的 IS_BIND_SENSITIVE=Y 且 VERSION_COUNT 持续增长，执行计划在 INDEX 和 FULL TABLE SCAN 之间频繁切换",
        "solution": "1) 使用 SQL Plan Baseline 固定最优计划；2) 对数据严重倾斜的列收集直方图；3) 考虑使用 CURSOR_SHARING=EXACT + 应用层显式绑定；4) 12c+ 可以使用 SQL Patch 强制计划",
        "confidence": 0.85,
    },

    # ==================== Redo/Commit 深度场景 ====================
    {
        "name": "LGWR 单点瓶颈（非存储问题）",
        "conditions": "log file sync avg wait > 5ms 但 log file parallel write avg < 2ms，差值来自 LGWR 排队和 CPU 调度延迟",
        "solution": "1) log file sync = LGWR post/wait + log file parallel write；2) 差值大说明 LGWR 本身有 CPU 争用或排队问题；3) 检查 LGWR 进程是否绑定到特定 CPU（不建议绑定）；4) 11.2.0.4+ 的 LGWR worker 机制可以启用：_use_adaptive_log_file_sync=TRUE",
        "confidence": 0.82,
    },
    {
        "name": "Redo 产出量与 DML 操作不匹配",
        "conditions": "redo_size_per_sec 异常高但 commits_per_sec 和 executes_per_sec 不高，可能有大批量 DML 产生大量 redo",
        "solution": "1) 检查是否有大表 UPDATE/DELETE/INSERT SELECT 产生大量 redo；2) 对批量操作使用 APPEND 提示减少 redo（INSERT /*+ APPEND */）；3) 对临时数据使用 NOLOGGING 减少 redo；4) 分批操作并定期 COMMIT 控制 redo 产出",
        "confidence": 0.85,
    },

    # ==================== 网络等待深度场景 ====================
    {
        "name": "SQL*Net roundtrip 过多导致网络延迟",
        "conditions": "SQL*Net message from client 占 DB Time > 15% 但 avg wait < 1ms，说明不是网络慢而是 roundtrip 次数太多",
        "solution": "1) 增大客户端 arraysize/fetch size（JDBC: setFetchSize(200)）；2) 减少 SQL 执行频率（合并小查询为大查询）；3) 使用 BULK COLLECT 替代逐行 FETCH；4) 调大 SDU_SIZE 到 32767 减少网络分包",
        "confidence": 0.88,
    },
    {
        "name": "DBLink 跨库查询网络等待",
        "conditions": "SQL*Net message from dblink 或 SQL*Net more data from dblink 等待占比高，SQL 中使用了 @dblink 远程访问",
        "solution": "1) 评估是否可以将远程数据本地化（物化视图/定时同步）；2) 减少跨库数据传输量（在远程端过滤数据）；3) 使用 DRIVING_SITE hint 控制 JOIN 执行位置；4) 增大 SDU 和使用 TCP 参数优化（SEND_BUF_SIZE）",
        "confidence": 0.85,
    },

    # ==================== Resource Manager 场景 ====================
    {
        "name": "Resource Manager CPU 限流导致会话排队",
        "conditions": "resmgr:cpu quantum 等待占 DB Time > 5%，某些会话的 CPU 使用被 Resource Manager 主动限制",
        "solution": "1) 检查 Resource Plan：SELECT * FROM DBA_RSRC_PLAN_DIRECTIVES；2) 确认限流是否为预期行为；3) 调整消费组的 CPU_P1/P2/P3 份额；4) 如果是误配置，使用 ALTER SYSTEM SET resource_manager_plan='' 临时禁用",
        "confidence": 0.82,
    },

    # ==================== Undo 深度场景 ====================
    {
        "name": "一致性读导致 Undo 段争用",
        "conditions": "enq: US - contention 出现，大量长查询需要回溯 undo 数据构建一致性读视图",
        "solution": "1) 增大 UNDO_TABLESPACE 确保 undo 数据保留足够长；2) 设置 UNDO_RETENTION 大于最长查询时间；3) 拆分长事务减少 undo 需求；4) 检查是否有 LOB 列的 RETENTION 设置过大占用 undo",
        "confidence": 0.85,
    },

    # ==================== Flashback/ADG 场景 ====================
    {
        "name": "Flashback Log 写入导致 I/O 放大",
        "conditions": "flashback log file sync 或 flashback buf free by RVWR 等待出现，Flashback Database 启用但写入速度跟不上",
        "solution": "1) 将 Flashback Log 放在高速存储上（独立于数据文件和 redo）；2) 如果不需要 Flashback Database 功能，考虑禁用以消除开销；3) 增大 db_flashback_retention_target 减少循环覆盖频率；4) 检查 RVWR 进程的 I/O 等待",
        "confidence": 0.78,
    },
    {
        "name": "ADG 备库 MRP 进程 apply 延迟大",
        "conditions": "备库 V$DATAGUARD_STATS 显示 apply lag > 60 秒，recovery 相关等待出现，可能伴随 log file sequential read 高",
        "solution": "1) 增大 recovery parallelism（ALTER DATABASE RECOVER MANAGED STANDBY DATABASE PARALLEL 8）；2) 检查备库存储 I/O 性能；3) 使用 ADG 的 Multi-Instance Redo Apply（RAC 备库）；4) 检查网络传输是否是瓶颈（V$DATAGUARD_STATS 的 transport lag）",
        "confidence": 0.80,
    },

    # ==================== 内存管理深度场景 ====================
    {
        "name": "AMM（Automatic Memory Management）内存振荡",
        "conditions": "SGA 和 PGA 大小频繁调整，出现 ORA-04031 或 SGA resize 导致短暂性能抖动",
        "solution": "1) 不建议在大内存实例上使用 AMM（memory_target）；2) 改用 ASMM：设置 SGA_TARGET + PGA_AGGREGATE_TARGET，清除 MEMORY_TARGET；3) 固定 SGA_TARGET 避免频繁自动调整；4) 关键组件可手动设置最小值（db_cache_size, shared_pool_size）",
        "confidence": 0.85,
    },
    {
        "name": "Shared Pool 碎片化导致 ORA-04031",
        "conditions": "ORA-04031 unable to allocate shared memory 间歇出现，shared pool free memory 总量足够但缺少连续大块",
        "solution": "1) 减少硬解析数量是根本方案（使用绑定变量）；2) 定期 flush shared pool 仅作为紧急手段：ALTER SYSTEM FLUSH SHARED_POOL；3) 增大 shared_pool_size 减少碎片压力；4) 使用 _shared_pool_reserved_pct 预留大块内存空间",
        "confidence": 0.85,
    },

    # ==================== 索引相关深度场景 ====================
    {
        "name": "索引回表过多导致性能退化",
        "conditions": "SQL 使用索引但 TABLE ACCESS BY INDEX ROWID 行数远大于最终返回行数，Gets/Exec 高但不是全表扫描",
        "solution": "1) 创建覆盖索引包含所有查询列避免回表；2) 如果选择性差（返回 >10% 数据），全表扫描可能更优；3) 收集列统计信息让优化器正确估算；4) 使用 Index Only Scan（覆盖索引）彻底消除回表",
        "confidence": 0.88,
    },
    {
        "name": "右增长索引热点块争用",
        "conditions": "buffer busy waits 集中在某个索引的最右叶块，通常是主键序列递增的 B-tree 索引",
        "solution": "1) 使用 Reverse Key Index（ALTER INDEX ... REBUILD REVERSE）分散插入点；2) 增大索引的 INITRANS 和 PCTFREE；3) RAC 环境使用 Hash Partition Index 分散热点；4) 对序列生成器增大 CACHE 值",
        "confidence": 0.88,
    },
    {
        "name": "索引统计信息过期导致全表扫描",
        "conditions": "SQL 之前走索引但突然变为 TABLE ACCESS FULL，DBA_TAB_STATISTICS.STALE_STATS = YES，数据量增长超过 10%",
        "solution": "1) 立即收集统计信息：DBMS_STATS.GATHER_TABLE_STATS(ownname=>'OWNER', tabname=>'TABLE', estimate_percent=>DBMS_STATS.AUTO_SAMPLE_SIZE)；2) 对关键表设置增量收集：SET_TABLE_PREFS('INCREMENTAL', 'TRUE')；3) 使用 SPM 固定好的执行计划防止统计信息变化影响",
        "confidence": 0.90,
    },

    # ==================== 分区表深度场景 ====================
    {
        "name": "全局索引导致分区维护锁",
        "conditions": "分区表 DDL 操作（DROP/TRUNCATE PARTITION）需要重建全局索引，期间全局索引不可用，查询走全表扫描",
        "solution": "1) 使用 UPDATE INDEXES 子句在线维护：ALTER TABLE ... DROP PARTITION ... UPDATE INDEXES；2) 将全局索引改为本地索引（如果查询都包含分区键）；3) 12c+ 使用 DEFERRED INDEX INVALIDATION 推迟索引重建；4) 在业务低峰执行分区维护",
        "confidence": 0.85,
    },
    {
        "name": "分区表 Partition Exchange 导致统计信息丢失",
        "conditions": "ALTER TABLE ... EXCHANGE PARTITION 后查询性能下降，新分区的统计信息为空或不准确",
        "solution": "1) Exchange 后立即收集统计信息；2) 使用 DBMS_STATS.COPY_TABLE_STATS 从源表复制统计信息；3) 在 exchange 前先在 staging 表上收集统计信息（包括直方图）；4) 使用 INCLUDING INDEXES WITHOUT VALIDATION 加速 exchange",
        "confidence": 0.82,
    },

    # ==================== 高可用/灾备场景 ====================
    {
        "name": "Switchover/Failover 后性能下降",
        "conditions": "ADG 切换后新主库性能明显差于原主库，Buffer Cache 为空需要预热，执行计划可能不同",
        "solution": "1) Buffer Cache 冷启动：使用 ALTER TABLE ... CACHE 对关键表预加载；2) 收集统计信息确保与原主库一致；3) 检查 SGA/PGA 配置是否与原主库相同；4) 使用 SQL Plan Baseline 确保执行计划一致性；5) 检查 Resource Manager 配置",
        "confidence": 0.82,
    },

    # ==================== 多列统计和扩展统计 ====================
    {
        "name": "缺少多列统计导致 Cardinality 估算偏差",
        "conditions": "执行计划中 Estimated Rows 与 Actual Rows 偏差 > 10 倍，WHERE 条件有多个列的 AND 组合但无多列统计",
        "solution": "1) 创建扩展统计：DBMS_STATS.CREATE_EXTENDED_STATS(null, 'TABLE', '(COL1, COL2)')；2) 收集统计信息：DBMS_STATS.GATHER_TABLE_STATS 会自动包含扩展统计；3) 检查 SQL Directive：DBA_SQL_PLAN_DIRECTIVES 是否已建议多列统计；4) 使用 DBMS_STATS.SEED_COL_USAGE 播种列使用信息",
        "confidence": 0.85,
    },

    # ==================== 系统级综合场景 ====================
    {
        "name": "多问题域并发（系统过载）",
        "conditions": "AAS > CPU 核数，3 个以上问题域同时活跃（CPU + I/O + Commit + Concurrency），无单一明显根因",
        "solution": "1) 系统处于过载状态，优先降低总负载量；2) 分析 Top SQL 消耗分布，找到占 DB Time 最大的 3-5 条 SQL 集中优化；3) 使用 Resource Manager 限制低优先级负载；4) 考虑分流读查询到 ADG 备库；5) 评估硬件扩容需求",
        "confidence": 0.88,
    },
    {
        "name": "业务高峰期性能周期性退化",
        "conditions": "每天固定时段（如 9:00-10:00、14:00-15:00）AAS 飙升，Top SQL 变化不大但并发会话数量翻倍",
        "solution": "1) 这是典型的并发量超出系统能力问题；2) 使用连接池限制最大并发（建议 CPU_COUNT * 2-4）；3) 检查是否有批处理与 OLTP 混合执行；4) 使用 Resource Manager 按时段调整资源分配；5) 对读查询分流到 ADG 备库",
        "confidence": 0.85,
    },
    {
        "name": "数据库补丁/升级后性能回退",
        "conditions": "PSU/RU 补丁安装后或大版本升级后 SQL 性能下降，新特性或优化器行为变化导致执行计划改变",
        "solution": "1) 使用 SQL Plan Baseline 固定升级前的好计划；2) 设置 optimizer_features_enable 回退到旧版本行为（临时方案）；3) 检查 DBA_SQL_PLAN_BASELINES 是否有自动捕获的旧计划；4) 使用 STS（SQL Tuning Set）+RATS（Real Application Testing）测试补丁影响",
        "confidence": 0.85,
    },

    # ==================== ORM/应用框架常见问题 ====================
    {
        "name": "Hibernate/JPA 生成低效 SQL",
        "conditions": "Top SQL 中有大量带 WHERE 1=1、多层嵌套子查询或 N+1 模式的 SQL，SQL 文本含 ORM 框架特征（如 hibernate 注释）",
        "solution": "1) 检查 JPA/Hibernate 的 fetch 策略（EAGER vs LAZY）；2) 使用 @NamedQuery 或原生 SQL 替代复杂 JPQL；3) 启用二级缓存减少数据库查询；4) 使用 JOIN FETCH 替代 N+1；5) 检查 hibernate.default_batch_fetch_size 配置",
        "confidence": 0.88,
    },
    {
        "name": "MyBatis 动态 SQL 导致硬解析",
        "conditions": "hard_parses_per_sec 偏高，Top SQL 中有大量结构相同但 WHERE 条件数量不同的 SQL（动态拼接）",
        "solution": "1) MyBatis 的 <if> 标签导致 SQL 结构变化，每种组合产生不同的 SQL_ID；2) 将高频查询改为固定结构 + 绑定变量；3) 使用 WHERE 1=1 AND col = NVL(:val, col) 替代动态条件；4) 增大 shared_pool_size 作为缓解",
        "confidence": 0.88,
    },
]
