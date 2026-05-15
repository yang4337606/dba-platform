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
]
