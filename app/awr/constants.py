"""Pure data constants for the AWR analysis engine."""


BUILTIN_RULES = [
    # =========================================================================
    # A. WAIT EVENT RULES (等待事件)
    # =========================================================================
    {
        'name': 'db file sequential read 高等待',
        'category': 'wait_event',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 15, "event": "db file sequential read"}],
        'root_cause': '单块读等待过高，通常与索引扫描和随机I/O相关',
        'solution': '1. 检查Top SQL中Buffer Gets最高的SQL\n2. 检查I/O子系统性能(avg read time > 10ms需关注)\n3. 考虑将热点数据缓存到SGA\n4. 检查是否需要创建覆盖索引减少回表',
        'severity': 'high',
    },
    {
        'name': 'db file scattered read 高等待',
        'category': 'wait_event',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 15, "event": "db file scattered read"}],
        'root_cause': '多块读等待过高，通常与全表扫描相关',
        'solution': '1. 检查Top SQL中Physical Reads最高的SQL\n2. 确认是否缺少索引导致全表扫描\n3. 检查统计信息是否过期\n4. 考虑分区表或并行查询优化',
        'severity': 'high',
    },
    {
        'name': 'log file sync 高等待',
        'category': 'wait_event',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 10, "event": "log file sync"}],
        'root_cause': '日志文件同步等待过高，与提交频率和redo写入性能相关',
        'solution': '1. 检查redo log I/O性能(log file parallel write)\n2. 减少不必要的频繁COMMIT\n3. 将redo log放到高速存储\n4. 检查是否有Data Guard同步延迟',
        'severity': 'high',
    },
    {
        'name': 'log file parallel write 高等待',
        'category': 'wait_event',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 5, "event": "log file parallel write"}],
        'root_cause': 'LGWR进程写redo log的I/O延迟过高，底层存储写性能不足',
        'solution': '1. 检查redo log所在存储的写IOPS和延迟\n2. 将redo log迁移到低延迟SSD/NVMe存储\n3. 确认redo log不与数据文件共享I/O通道\n4. 检查ASM冗余策略(NORMAL vs HIGH)对写放大的影响',
        'severity': 'high',
    },
    {
        'name': 'TX row lock contention',
        'category': 'wait_event',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 10, "event": "enq: TX - row lock contention"}],
        'root_cause': '行锁争用严重，多个会话竞争同一行数据',
        'solution': '1. 定位持锁SQL和阻塞会话\n2. 优化事务粒度，减少长事务\n3. 检查应用逻辑是否存在热点行更新\n4. 考虑使用乐观锁机制',
        'severity': 'high',
    },
    {
        'name': 'TX index contention',
        'category': 'wait_event',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 5, "event": "enq: TX - index contention"}],
        'root_cause': '索引叶子块争用，通常出现在单调递增主键的右侧插入场景',
        'solution': '1. 将序列缓存增大(CACHE 1000+)\n2. 考虑使用反转索引(Reverse Key Index)\n3. 使用Hash分区索引分散插入点\n4. 对于RAC环境考虑实例级序列CACHE',
        'severity': 'high',
    },
    {
        'name': 'TX allocate ITL entry',
        'category': 'wait_event',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 5, "event": "enq: TX - allocate ITL entry"}],
        'root_cause': 'ITL(Interested Transaction List)槽位不足，块内并发事务过多',
        'solution': '1. 增大表/索引的INITRANS参数(建议10-20)\n2. 重建受影响的表和索引\n3. 检查是否有极小块中大量并发DML\n4. ALTER TABLE xxx INITRANS 16;',
        'severity': 'medium',
    },
    {
        'name': 'latch/mutex 争用',
        'category': 'wait_event',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 10, "event": "latch"}],
        'root_cause': 'Latch或Mutex争用，通常与高并发和shared pool相关',
        'solution': '1. 检查是否存在大量硬解析(cursor: pin S)\n2. 使用绑定变量减少硬解析\n3. 调整cursor_sharing参数\n4. 检查shared pool是否过小',
        'severity': 'high',
    },
    {
        'name': 'cursor: pin S wait on X',
        'category': 'wait_event',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 5, "event": "cursor: pin S wait on X"}],
        'root_cause': '大量会话同时解析同一SQL语句导致的互斥等待，经典的高并发硬解析症状',
        'solution': '1. 检查V$SQL中VERSION_COUNT过高的游标\n2. 推动应用端使用绑定变量\n3. 检查ACS(Adaptive Cursor Sharing)是否导致游标版本过多\n4. 设置_cursor_obsolete_threshold限制版本数',
        'severity': 'high',
    },
    {
        'name': 'cursor: mutex S',
        'category': 'wait_event',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 5, "event": "cursor: mutex S"}],
        'root_cause': 'Cursor Mutex争用，通常与高频SQL执行和Library Cache并发访问有关',
        'solution': '1. 检查是否有高频执行且不使用绑定变量的SQL\n2. 检查V$SQL中EXECUTIONS极高的语句\n3. 确认是否存在library cache内存不足\n4. 检查补丁 - 多个Bug可导致此等待异常升高',
        'severity': 'medium',
    },
    {
        'name': 'library cache lock/pin',
        'category': 'wait_event',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 5, "event": "library cache"}],
        'root_cause': 'Library Cache对象锁等待，通常与DDL操作、包编译或对象失效有关',
        'solution': '1. 检查是否有DDL操作(ALTER/GRANT)锁住库缓存对象\n2. 检查是否有PL/SQL包正在编译\n3. 确认是否有对象失效导致的级联重编译\n4. 避免在业务高峰执行DDL',
        'severity': 'medium',
    },
    {
        'name': 'direct path read 高等待',
        'category': 'wait_event',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 15, "event": "direct path read"}],
        'root_cause': '直接路径读(绕过Buffer Cache)过高，通常与大表全扫或并行查询有关',
        'solution': '1. 11g+大表自动走direct path read，检查_serial_direct_read参数\n2. 检查是否有不必要的大表全扫描\n3. 确认并行度设置是否合理\n4. 对于LOB列检查是否可优化为SECUREFILE',
        'severity': 'medium',
    },
    {
        'name': 'direct path write 高等待',
        'category': 'wait_event',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 10, "event": "direct path write"}],
        'root_cause': '直接路径写等待过高，与CTAS、INSERT APPEND、排序溢出到磁盘有关',
        'solution': '1. 检查是否有大量CTAS/INSERT /*+ APPEND */操作\n2. 增大PGA_AGGREGATE_TARGET减少排序溢出\n3. 检查临时表空间I/O性能\n4. 如为批量加载，确认走的是direct path load',
        'severity': 'medium',
    },
    {
        'name': 'direct path read temp 高等待',
        'category': 'wait_event',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 10, "event": "direct path read temp"}],
        'root_cause': '临时表空间读取过多，SQL排序/哈希操作溢出到磁盘',
        'solution': '1. 增大PGA_AGGREGATE_TARGET，减少磁盘排序\n2. 优化Top SQL减少排序/哈希连接数据量\n3. 将临时表空间放到高速存储\n4. 检查WORKAREA_SIZE_POLICY是否为AUTO',
        'severity': 'medium',
    },
    {
        'name': 'direct path write temp 高等待',
        'category': 'wait_event',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 10, "event": "direct path write temp"}],
        'root_cause': '临时表空间写入过多，排序/哈希/全局临时表溢出到磁盘',
        'solution': '1. 增大PGA_AGGREGATE_TARGET\n2. 检查V$SQL_WORKAREA中ONE_PASS/MULTI_PASS次数\n3. 优化SQL减少排序集大小\n4. 确认临时表空间自动扩展配置',
        'severity': 'medium',
    },
    {
        'name': 'read by other session',
        'category': 'wait_event',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 8, "event": "read by other session"}],
        'root_cause': '多个会话并发请求读取相同数据块，需等待第一个会话完成物理读',
        'solution': '1. 检查热点段和热点块(V$BH中TCH值)\n2. 优化SQL减少对同一块的并发访问\n3. 如果是索引根块/分支块热点，考虑Hash分区索引\n4. 增大Buffer Cache减少物理读概率',
        'severity': 'medium',
    },
    {
        'name': 'buffer busy waits 高等待',
        'category': 'wait_event',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 8, "event": "buffer busy waits"}],
        'root_cause': '缓冲区忙等待，多个进程同时修改同一数据块',
        'solution': '1. 确定等待的块类型(数据块/段头/undo头)\n2. 数据块争用: 增大表PCTFREE或使用ASSM\n3. 段头争用: 增大FREELISTS\n4. Undo头争用: 增大UNDO表空间或调整undo_retention',
        'severity': 'high',
    },
    {
        'name': 'free buffer waits',
        'category': 'wait_event',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 5, "event": "free buffer waits"}],
        'root_cause': '没有空闲缓冲区可用，DBWR写脏块速度跟不上',
        'solution': '1. 增大DB_CACHE_SIZE\n2. 检查DBWR I/O性能(是否存储瓶颈)\n3. 增加DB_WRITER_PROCESSES数量\n4. 启用异步I/O(FILESYSTEMIO_OPTIONS=SETALL)',
        'severity': 'high',
    },
    {
        'name': 'enq: HW - contention',
        'category': 'wait_event',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 5, "event": "enq: HW - contention"}],
        'root_cause': '高水位线(HWM)争用，大量并发INSERT扩展段时竞争',
        'solution': '1. 使用ASSM(自动段空间管理)表空间\n2. 对高并发INSERT表预分配空间(ALTER TABLE ALLOCATE EXTENT)\n3. 使用本地管理表空间(LMT)而非字典管理\n4. 考虑分区表分散插入',
        'severity': 'medium',
    },
    {
        'name': 'enq: ST - contention',
        'category': 'wait_event',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 3, "event": "enq: ST - contention"}],
        'root_cause': '空间管理(Space Transaction)争用，字典管理表空间的空间分配冲突',
        'solution': '1. 将字典管理表空间转换为本地管理表空间\n2. 检查是否有频繁的表空间扩展操作\n3. 增大数据文件的AUTOEXTEND增量\n4. 预分配足够的空间减少动态扩展',
        'severity': 'medium',
    },
    {
        'name': 'enq: TM - contention',
        'category': 'wait_event',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 5, "event": "enq: TM - contention"}],
        'root_cause': 'DML表锁争用，通常因为外键无索引或并发DDL/DML冲突',
        'solution': '1. 检查外键列是否都已建索引(最常见原因)\n2. 确认是否有并发DDL锁住了表\n3. 检查是否有LOCK TABLE显式锁定\n4. 对子表外键列添加索引消除全表锁升级',
        'severity': 'high',
    },
    {
        'name': 'latch: shared pool',
        'category': 'wait_event',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 5, "event": "latch: shared pool"}],
        'root_cause': 'Shared Pool Latch争用，与大量硬解析或shared pool碎片化有关',
        'solution': '1. 使用绑定变量减少硬解析\n2. 增大SHARED_POOL_SIZE\n3. 设置SHARED_POOL_RESERVED_SIZE为shared pool的5-10%\n4. 检查V$SHARED_POOL_RESERVED中的REQUEST_FAILURES',
        'severity': 'high',
    },
    {
        'name': 'latch: cache buffers chains',
        'category': 'wait_event',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 5, "event": "latch: cache buffers chains"}],
        'root_cause': 'Buffer Cache哈希链Latch争用，存在热点数据块被高频访问',
        'solution': '1. 识别热点块(V$LATCH_CHILDREN.GETS最高的地址)\n2. 检查是否有小表被高频全扫描 - 考虑CACHE提示\n3. 分散热点数据到更多块(增大PCTFREE或分区)\n4. 对于索引根块热点，考虑Hash分区索引',
        'severity': 'high',
    },
    {
        'name': 'log buffer space',
        'category': 'wait_event',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 3, "event": "log buffer space"}],
        'root_cause': 'Log Buffer空间不足，redo生成速度超过LGWR写入速度',
        'solution': '1. 增大LOG_BUFFER参数(通常16-64MB)\n2. 检查redo log文件I/O性能\n3. 确认LGWR没有被其他I/O操作阻塞\n4. 检查是否有大事务产生巨量redo',
        'severity': 'medium',
    },
    {
        'name': 'log file switch (checkpoint/archiving)',
        'category': 'wait_event',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 3, "event": "log file switch"}],
        'root_cause': '日志切换等待，因checkpoint未完成或归档进程跟不上',
        'solution': '1. 增大redo log文件大小(建议1-4GB)\n2. 增加redo log组数(建议每组3-4个)\n3. 检查归档目的地空间和I/O性能\n4. 调整LOG_CHECKPOINT_INTERVAL/LOG_CHECKPOINT_TIMEOUT',
        'severity': 'high',
    },
    {
        'name': 'Scheduler 等待过高',
        'category': 'wait_event',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 10, "event": "resmgr:cpu quantum"}],
        'root_cause': 'Resource Manager限制了CPU使用，会话被降级排队',
        'solution': '1. 检查当前Resource Manager Plan设置\n2. 确认消费者组CPU限制是否过严\n3. 调整计划中的CPU分配比例\n4. 在非必要时禁用Resource Manager: ALTER SYSTEM SET RESOURCE_MANAGER_PLAN=\'\';',
        'severity': 'medium',
    },
    {
        'name': 'SQL*Net 网络等待过高',
        'category': 'wait_event',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 10, "event": "SQL*Net"}],
        'root_cause': '应用层与数据库之间的网络延迟过高或数据传输量大',
        'solution': '1. 检查应用端是否逐行FETCH(改用批量FETCH)\n2. 调整SDU/TDU参数增大网络包大小\n3. 确认网络带宽和延迟是否正常\n4. 使用数组绑定批量操作减少往返次数',
        'severity': 'medium',
    },
    {
        'name': 'control file sequential/parallel read',
        'category': 'wait_event',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 5, "event": "control file"}],
        'root_cause': '控制文件读取等待过高，与频繁的控制文件访问或慢存储有关',
        'solution': '1. 将控制文件放到高速存储\n2. 减少控制文件副本到2-3个(不放慢盘)\n3. 检查是否有频繁的日志切换触发控制文件更新\n4. 确认控制文件未放在NFS等高延迟存储上',
        'severity': 'medium',
    },
    {
        'name': 'os thread startup',
        'category': 'wait_event',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 5, "event": "os thread startup"}],
        'root_cause': '并行查询启动线程等待过高，PX进程创建开销大',
        'solution': '1. 设置PARALLEL_MIN_SERVERS预启动并行进程\n2. 减少不必要的并行查询\n3. 检查OS线程创建是否有资源限制(ulimit)\n4. 设置合理的PARALLEL_MAX_SERVERS',
        'severity': 'medium',
    },

    # =========================================================================
    # B. CPU RULES (CPU相关)
    # =========================================================================
    {
        'name': 'CPU 使用率过高',
        'category': 'cpu',
        'conditions': [{"metric": "db_time_ratio", "op": ">", "value": 1.5}, {"metric": "cpu_pct_db_time", "op": ">", "value": 60}],
        'root_cause': 'CPU资源成为瓶颈，DB Time远超CPU Time',
        'solution': '1. 优化Top SQL减少Buffer Gets\n2. 检查是否有低效的PL/SQL循环\n3. 考虑SQL Profile或SQL Plan Baseline\n4. 评估是否需要增加CPU资源',
        'severity': 'high',
    },
    {
        'name': 'DB CPU 占 DB Time 超过80%',
        'category': 'cpu',
        'conditions': [{"metric": "cpu_pct_db_time", "op": ">", "value": 80}],
        'root_cause': 'CPU密集型负载，几乎所有DB Time都消耗在CPU上',
        'solution': '1. 重点优化Top SQL by CPU Time中的语句\n2. 检查是否有PL/SQL中的大循环或递归调用\n3. 使用SQL Profile/SPM固定好的执行计划\n4. 评估是否有不必要的函数调用在SQL中',
        'severity': 'high',
    },
    {
        'name': 'AAS/CPU 比率过高',
        'category': 'cpu',
        'conditions': [{"metric": "aas_per_cpu", "op": ">", "value": 0.7}],
        'root_cause': 'Average Active Sessions接近或超过CPU核数，系统过载',
        'solution': '1. 减少并发活跃会话数(检查连接池配置)\n2. 优化高频SQL减少单次执行CPU消耗\n3. 考虑增加CPU资源(横向/纵向扩展)\n4. 使用Resource Manager限制低优先级消费者',
        'severity': 'high',
    },

    # =========================================================================
    # C. SQL EFFICIENCY RULES (SQL效率)
    # =========================================================================
    {
        'name': 'SQL 执行效率低 - 高逻辑读',
        'category': 'sql_efficiency',
        'conditions': [{"metric": "buffer_gets_per_exec", "op": ">", "value": 100000}],
        'root_cause': '存在高Buffer Gets的SQL，执行计划可能不优',
        'solution': '1. 检查SQL执行计划是否走全表扫描\n2. 验证统计信息是否最新\n3. 考虑创建合适的索引\n4. 使用SQL Tuning Advisor分析',
        'severity': 'medium',
    },
    {
        'name': 'SQL 执行效率低 - 高物理读',
        'category': 'sql_efficiency',
        'conditions': [{"metric": "disk_reads_per_exec", "op": ">", "value": 1000}],
        'root_cause': '存在高物理读SQL，数据不在缓存中或访问量巨大',
        'solution': '1. 检查SQL是否全表扫描大表\n2. 增大Buffer Cache缓存更多数据\n3. 创建索引减少物理读取\n4. 考虑分区裁剪减少扫描范围',
        'severity': 'medium',
    },
    {
        'name': 'SQL 执行次数过高',
        'category': 'sql_efficiency',
        'conditions': [{"metric": "sql_executions_per_sec", "op": ">", "value": 10000}],
        'root_cause': '存在高频执行的SQL，即使单次开销小，累积影响也很大',
        'solution': '1. 检查是否有不必要的循环内SQL调用\n2. 评估是否可以批量操作替代逐行处理\n3. 使用应用层缓存减少数据库往返\n4. 检查是否有不必要的健康检查/心跳SQL',
        'severity': 'medium',
    },
    {
        'name': 'SQL 解析占比过高(Parse vs Execute)',
        'category': 'sql_efficiency',
        'conditions': [{"metric": "execute_to_parse_pct", "op": "<", "value": 50}],
        'root_cause': 'Execute to Parse%过低，说明SQL没有被复用，每次执行都要解析',
        'solution': '1. 应用端使用Statement Cache / Session Cursor Cache\n2. 增大SESSION_CACHED_CURSORS参数(建议100+)\n3. 设置OPEN_CURSORS足够大\n4. 确保应用连接池正确复用PreparedStatement',
        'severity': 'medium',
    },
    {
        'name': 'Top SQL 占 DB Time 过于集中',
        'category': 'sql_efficiency',
        'conditions': [{"metric": "top1_sql_pct_db_time", "op": ">", "value": 30}],
        'root_cause': '单条SQL消耗了超过30% DB Time，为关键性能瓶颈点',
        'solution': '1. 最高优先级优化此SQL\n2. 检查执行计划是否发生变化(计划翻转)\n3. 使用SQL Plan Baseline锁定好的计划\n4. 检查统计信息和直方图是否准确',
        'severity': 'high',
    },

    # =========================================================================
    # D. MEMORY RULES (内存相关)
    # =========================================================================
    {
        'name': 'Buffer Cache 命中率低',
        'category': 'memory',
        'conditions': [{"metric": "buffer_cache_hit_ratio", "op": "<", "value": 95}],
        'root_cause': 'Buffer Cache命中率不足，大量物理读取',
        'solution': '1. 考虑增大db_cache_size\n2. 检查是否有大量全表扫描\n3. 使用KEEP/RECYCLE缓冲池隔离热点对象\n4. 检查是否有不合理的direct path read',
        'severity': 'medium',
    },
    {
        'name': 'Library Cache 命中率低',
        'category': 'memory',
        'conditions': [{"metric": "library_cache_hit_ratio", "op": "<", "value": 95}],
        'root_cause': 'Library Cache命中率不足，SQL游标频繁失效或被换出',
        'solution': '1. 增大shared_pool_size\n2. 使用绑定变量减少游标数量\n3. Pin住关键的PL/SQL对象\n4. 检查是否有DDL操作导致游标失效',
        'severity': 'medium',
    },
    {
        'name': 'Shared Pool 空闲不足',
        'category': 'memory',
        'conditions': [{"metric": "shared_pool_free_pct", "op": "<", "value": 10}],
        'root_cause': 'Shared Pool可用空间不足，可能导致ORA-4031错误和硬解析失败',
        'solution': '1. 增大SHARED_POOL_SIZE\n2. 设置SHARED_POOL_RESERVED_SIZE=shared_pool的5-10%\n3. 检查V$SGASTAT中free memory和V$SHARED_POOL_RESERVED\n4. 使用绑定变量减少游标数量占用',
        'severity': 'high',
    },
    {
        'name': 'PGA 使用过高/溢出频繁',
        'category': 'memory',
        'conditions': [{"metric": "pga_over_allocation_count", "op": ">", "value": 0}],
        'root_cause': 'PGA过度分配，排序和Hash Join频繁溢出到磁盘(multi-pass)',
        'solution': '1. 增大PGA_AGGREGATE_TARGET\n2. 检查V$SQL_WORKAREA中OPTIMAL/ONE_PASS/MULTI_PASS分布\n3. 优化SQL减少排序和Hash Join数据量\n4. 检查是否有异常的PGA消耗者(V$PROCESS.PGA_USED_MEM)',
        'severity': 'medium',
    },
    {
        'name': 'In-memory Sort% 过低',
        'category': 'memory',
        'conditions': [{"metric": "in_memory_sort_pct", "op": "<", "value": 95}],
        'root_cause': '内存排序比例过低，大量排序溢出到磁盘(临时表空间)',
        'solution': '1. 增大PGA_AGGREGATE_TARGET\n2. 优化排序SQL减少排序集大小\n3. 使用索引避免排序(ORDER BY走索引)\n4. 检查是否有不必要的DISTINCT/GROUP BY/ORDER BY',
        'severity': 'medium',
    },
    {
        'name': 'Soft Parse% 过低',
        'category': 'memory',
        'conditions': [{"metric": "soft_parse_pct", "op": "<", "value": 90}],
        'root_cause': '软解析比例过低，硬解析比例过高，Shared Pool压力大',
        'solution': '1. 推动应用使用绑定变量(最根本解决方案)\n2. 设置cursor_sharing=FORCE(紧急缓解)\n3. 增大SHARED_POOL_SIZE\n4. 增大SESSION_CACHED_CURSORS',
        'severity': 'high',
    },
    {
        'name': 'Latch Hit% 过低',
        'category': 'memory',
        'conditions': [{"metric": "latch_hit_pct", "op": "<", "value": 99}],
        'root_cause': 'Latch命中率低于99%，存在严重的Latch争用',
        'solution': '1. 检查V$LATCH中MISSES/GETS最高的Latch名称\n2. shared pool latch: 绑定变量+增大shared pool\n3. cache buffers chains: 消除热点块\n4. redo allocation: 增大LOG_BUFFER或使用Private Redo Strands',
        'severity': 'high',
    },

    # =========================================================================
    # E. I/O RULES (存储I/O)
    # =========================================================================
    {
        'name': 'I/O 延迟过高',
        'category': 'io',
        'conditions': [{"metric": "avg_read_time", "op": ">", "value": 10}],
        'root_cause': '磁盘I/O响应时间过长',
        'solution': '1. 检查存储阵列性能和队列深度\n2. 确认是否存在I/O热点文件\n3. 考虑将数据文件分散到多个磁盘组\n4. 评估SSD存储升级方案',
        'severity': 'high',
    },
    {
        'name': 'I/O 写延迟过高',
        'category': 'io',
        'conditions': [{"metric": "avg_write_time", "op": ">", "value": 5}],
        'root_cause': '磁盘写I/O响应时间过长，影响DBWR和LGWR性能',
        'solution': '1. 检查存储写缓存是否正常工作(BBU电池)\n2. 确认RAID级别写惩罚(RAID5/6写放大)\n3. 将redo log和数据文件分开到不同存储\n4. 检查是否有I/O调度器瓶颈(Linux: deadline/noop)',
        'severity': 'high',
    },
    {
        'name': '单个表空间I/O过于集中',
        'category': 'io',
        'conditions': [{"metric": "tablespace_io_pct", "op": ">", "value": 60}],
        'root_cause': '单个表空间承担了超过60%的I/O负载，存在I/O热点',
        'solution': '1. 将热点表分区到多个表空间\n2. 检查热点表空间中的大表是否可以分区\n3. 使用ASM条带化分散I/O\n4. 将热点表空间迁移到高速存储(SSD)',
        'severity': 'medium',
    },
    {
        'name': 'IOPS 过高',
        'category': 'io',
        'conditions': [{"metric": "physical_reads_per_sec", "op": ">", "value": 50000}],
        'root_cause': '物理读IOPS过高，存储子系统可能接近饱和',
        'solution': '1. 优化Top SQL减少物理读\n2. 增大Buffer Cache提高缓存命中率\n3. 检查是否有不必要的全表扫描\n4. 评估存储IOPS上限并考虑扩容',
        'severity': 'high',
    },

    # =========================================================================
    # F. LOAD PROFILE RULES (负载画像)
    # =========================================================================
    {
        'name': 'DB Time 远超 CPU Time',
        'category': 'load',
        'conditions': [{"metric": "db_time_ratio", "op": ">", "value": 3.0}],
        'root_cause': 'DB Time是CPU Time的3倍以上，大量时间花在等待',
        'solution': '1. 分析Top Wait Events定位等待瓶颈\n2. 检查I/O等待和锁等待\n3. 分析AAS(Average Active Sessions)趋势\n4. 确认是否存在资源瓶颈',
        'severity': 'high',
    },
    {
        'name': '事务量过高',
        'category': 'load',
        'conditions': [{"metric": "transactions_per_sec", "op": ">", "value": 500}],
        'root_cause': '每秒事务数过高，提交频率大，log file sync压力增大',
        'solution': '1. 检查是否可以合并小事务为批量操作\n2. 减少自动提交(autocommit=true)\n3. 使用批量DML + 定期COMMIT(每1000-5000行)\n4. 确认redo log I/O性能足够支撑事务量',
        'severity': 'medium',
    },
    {
        'name': '逻辑读/秒过高',
        'category': 'load',
        'conditions': [{"metric": "logical_reads_per_sec", "op": ">", "value": 2000000}],
        'root_cause': '逻辑读速率极高，CPU消耗大量时间在Buffer Cache查找',
        'solution': '1. 优化Top SQL减少Buffer Gets\n2. 检查是否有高频执行的小SQL累积造成\n3. 考虑结果集缓存(Result Cache)\n4. 检查是否有不必要的重复查询',
        'severity': 'medium',
    },

    # =========================================================================
    # G. PARSE RULES (解析相关)
    # =========================================================================
    {
        'name': '硬解析比例过高',
        'category': 'parse',
        'conditions': [{"metric": "hard_parse_pct", "op": ">", "value": 10}],
        'root_cause': '硬解析占比过高，消耗大量CPU和shared pool资源',
        'solution': '1. 推动应用使用绑定变量\n2. 设置cursor_sharing=FORCE(临时方案)\n3. 增大shared_pool_size\n4. 检查是否有动态SQL拼接导致的硬解析',
        'severity': 'medium',
    },
    {
        'name': '硬解析次数/秒过高',
        'category': 'parse',
        'conditions': [{"metric": "hard_parses_per_sec", "op": ">", "value": 100}],
        'root_cause': '每秒硬解析超过100次，严重消耗CPU和Shared Pool资源',
        'solution': '1. 分析V$SQL中PLAN_HASH_VALUE唯一但SQL_TEXT仅字面值不同的SQL\n2. 推动开发使用绑定变量\n3. cursor_sharing=FORCE作为紧急措施\n4. 增大SHARED_POOL_SIZE缓解ORA-4031风险',
        'severity': 'high',
    },
    {
        'name': '总解析次数/秒过高',
        'category': 'parse',
        'conditions': [{"metric": "total_parses_per_sec", "op": ">", "value": 1000}],
        'root_cause': '每秒总解析(含软解析)过高，即使软解析也有Latch开销',
        'solution': '1. 增大SESSION_CACHED_CURSORS(建议100-200)\n2. 应用端使用Statement Cache减少软解析\n3. 使用PL/SQL Static SQL天然避免解析\n4. 检查应用连接池是否正确复用会话游标',
        'severity': 'medium',
    },
    {
        'name': 'Parse CPU to Parse Elapsed% 过低',
        'category': 'parse',
        'conditions': [{"metric": "parse_cpu_to_elapsed_pct", "op": "<", "value": 50}],
        'root_cause': '解析时CPU时间远低于解析经历时间，解析过程存在等待(Latch争用或I/O)',
        'solution': '1. 检查是否有Library Cache Latch争用\n2. 检查Shared Pool是否碎片化\n3. 确认解析期间是否有磁盘I/O(dictionary cache miss)\n4. 增大SHARED_POOL_SIZE减少失效和换出',
        'severity': 'medium',
    },

    # =========================================================================
    # H. RAC RULES (RAC集群)
    # =========================================================================
    {
        'name': 'GC cr block receive time 高',
        'category': 'rac',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 10, "event": "gc cr block receive time"}],
        'root_cause': 'RAC节点间Global Cache CR块传输延迟过高',
        'solution': '1. 检查RAC互联网络带宽和延迟(ping延迟<0.5ms)\n2. 识别热点对象并做实例隔离\n3. 使用服务(Service)将相关SQL路由到同一节点\n4. 检查是否有跨节点锁争用',
        'severity': 'high',
    },
    {
        'name': 'GC current block receive time 高',
        'category': 'rac',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 10, "event": "gc current block receive time"}],
        'root_cause': 'RAC节点间Global Cache Current块传输延迟高，跨节点修改同一块',
        'solution': '1. 识别跨节点修改的热点表/索引(GV$SEGMENT_STATISTICS)\n2. 使用服务路由DML到单一节点\n3. 对热点表做Hash分区分散修改\n4. 检查互联网络是否存在丢包或延迟抖动',
        'severity': 'high',
    },
    {
        'name': 'GC buffer busy acquire/release',
        'category': 'rac',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 5, "event": "gc buffer busy"}],
        'root_cause': 'RAC GC缓冲区忙等待，多个实例频繁争用同一数据块',
        'solution': '1. 最常见于序列和索引右侧插入 - 使用大CACHE序列\n2. 使用反转索引减少块争用\n3. 表级分区+实例隔离\n4. 检查是否有不必要的跨节点操作',
        'severity': 'high',
    },
    {
        'name': 'RAC 互联网络延迟过高',
        'category': 'rac',
        'conditions': [{"metric": "gc_cr_block_receive_time", "op": ">", "value": 1.0}],
        'root_cause': 'RAC节点间数据块传输平均延迟超过1ms，互联网络可能有问题',
        'solution': '1. 检查私网ping延迟(正常<0.5ms)\n2. 确认互联使用万兆或更高带宽\n3. 检查网卡绑定和UDP/RDS配置\n4. 排查交换机端口错误和丢包率',
        'severity': 'high',
    },
    {
        'name': 'DRM(Dynamic Remastering)频繁',
        'category': 'rac',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 3, "event": "gc remaster"}],
        'root_cause': 'GRD动态资源重主控频繁触发，导致短暂冻结和性能抖动',
        'solution': '1. 设置_gc_policy_time=0禁用DRM(Oracle推荐非默认场景)\n2. 使用读写分离减少跨节点资源访问\n3. 固定关键对象的主控节点\n4. 升级到最新PSU/RU修复DRM相关bug',
        'severity': 'medium',
    },

    # =========================================================================
    # I. REDO / LOG RULES (日志相关)
    # =========================================================================
    {
        'name': 'Redo 生成量过大',
        'category': 'redo',
        'conditions': [{"metric": "redo_size_per_sec", "op": ">", "value": 50000000}],
        'root_cause': 'Redo日志生成速度过快，可能影响日志切换和备份',
        'solution': '1. 检查是否有大批量DML操作未分批提交\n2. 评估是否可以使用NOLOGGING操作\n3. 增大redo log文件大小减少日志切换\n4. 确认归档传输带宽是否充足',
        'severity': 'medium',
    },
    {
        'name': '日志切换过于频繁',
        'category': 'redo',
        'conditions': [{"metric": "log_switches_per_hour", "op": ">", "value": 6}],
        'root_cause': '每小时日志切换超过6次(每10分钟一次)，影响性能和归档传输',
        'solution': '1. 增大redo log文件大小(建议2-4GB)\n2. 确认当前redo log大小: V$LOG\n3. 增加redo log组数减少等待\n4. ALTER DATABASE ADD LOGFILE GROUP N SIZE 2G;',
        'severity': 'medium',
    },
    {
        'name': 'Redo 日志切换每小时超20次',
        'category': 'redo',
        'conditions': [{"metric": "log_switches_per_hour", "op": ">", "value": 20}],
        'root_cause': '日志切换极其频繁(3分钟一次)，可能触发log file switch等待',
        'solution': '1. 紧急增大redo log大小到4GB以上\n2. 检查是否有大批量数据加载任务\n3. 确认归档进程能否跟上切换速度\n4. 考虑对大批量操作使用NOLOGGING+后续全备',
        'severity': 'high',
    },

    # =========================================================================
    # J. SEGMENT RULES (段/对象级)
    # =========================================================================
    {
        'name': '热点段争用 - Buffer Busy Waits',
        'category': 'segment',
        'conditions': [{"metric": "segment_buffer_busy_waits", "op": ">", "value": 1000}],
        'root_cause': '特定段(表/索引)存在热点Buffer Busy Waits争用',
        'solution': '1. 对热点表使用ASSM表空间自动段管理\n2. 增加FREELISTS/FREELIST GROUPS\n3. 考虑反转索引或Hash分区减少右侧插入争用\n4. 检查是否需要增大PCTFREE',
        'severity': 'medium',
    },
    {
        'name': '热点段 - 逻辑读集中',
        'category': 'segment',
        'conditions': [{"metric": "segment_logical_reads_pct", "op": ">", "value": 30}],
        'root_cause': '单个段(表/索引)贡献了超过30%的逻辑读，是主要的缓存消费者',
        'solution': '1. 优化访问此段的Top SQL\n2. 检查是否缺少合适索引导致全扫\n3. 考虑将热点表放入KEEP缓冲池\n4. 检查分区策略是否能减少扫描范围',
        'severity': 'medium',
    },
    {
        'name': '热点段 - 物理读集中',
        'category': 'segment',
        'conditions': [{"metric": "segment_physical_reads_pct", "op": ">", "value": 30}],
        'root_cause': '单个段贡献了超过30%的物理读，可能是大表全扫或缓存不足',
        'solution': '1. 分析该段大小与Buffer Cache大小的比例\n2. 优化相关SQL减少物理读\n3. 考虑分区表减少扫描范围\n4. 将该表空间放到高速存储',
        'severity': 'medium',
    },
    {
        'name': '热点段 - Row Lock 集中',
        'category': 'segment',
        'conditions': [{"metric": "segment_row_lock_waits", "op": ">", "value": 500}],
        'root_cause': '特定段上行锁等待集中，存在热点行争用',
        'solution': '1. 分析应用逻辑，识别热点行的更新模式\n2. 优化事务大小减少锁持有时间\n3. 考虑使用乐观锁(版本号)替代悲观锁\n4. 对于计数器类热点行，考虑使用DBMS_LOCK序列化',
        'severity': 'high',
    },
    {
        'name': '热点段 - ITL Waits',
        'category': 'segment',
        'conditions': [{"metric": "segment_itl_waits", "op": ">", "value": 100}],
        'root_cause': '段的ITL(事务槽)等待，同一块上并发事务过多',
        'solution': '1. 增大表/索引的INITRANS(ALTER TABLE xxx INITRANS 20)\n2. 需要MOVE/REBUILD使新INITRANS生效\n3. 增大PCTFREE给块留更多空间动态扩展ITL\n4. 分散数据减少单块并发修改',
        'severity': 'medium',
    },

    # =========================================================================
    # K. UNDO / TEMP TABLESPACE RULES (Undo与临时表空间)
    # =========================================================================
    {
        'name': 'Undo 表空间争用',
        'category': 'undo',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 3, "event": "enq: US - contention"}],
        'root_cause': 'Undo Segment争用，可能undo表空间过小或undo_retention设置不当',
        'solution': '1. 增大Undo表空间大小\n2. 调整UNDO_RETENTION参数(默认900s)\n3. 检查是否有长事务占用大量undo空间\n4. 确认UNDO_MANAGEMENT=AUTO',
        'severity': 'medium',
    },
    {
        'name': 'ORA-1555 / Undo不足风险',
        'category': 'undo',
        'conditions': [{"metric": "undo_space_used_pct", "op": ">", "value": 85}],
        'root_cause': 'Undo表空间使用率过高，存在ORA-1555 Snapshot Too Old风险',
        'solution': '1. 增大Undo表空间(至少保证UNDO_RETENTION时间内的空间)\n2. 避免长查询与大事务并行\n3. 分析V$UNDOSTAT找到undo使用高峰\n4. 考虑UNDO_RETENTION保证(RETENTION GUARANTEE)',
        'severity': 'high',
    },
    {
        'name': '临时表空间使用率过高',
        'category': 'temp',
        'conditions': [{"metric": "temp_space_used_pct", "op": ">", "value": 80}],
        'root_cause': '临时表空间使用率过高，可能导致排序/Hash操作失败',
        'solution': '1. 增大临时表空间(添加临时数据文件)\n2. 优化大排序SQL减少排序集大小\n3. 增大PGA_AGGREGATE_TARGET减少磁盘排序\n4. 检查V$TEMPSEG_USAGE定位占用最多的会话/SQL',
        'severity': 'high',
    },

    # =========================================================================
    # L. OS / RESOURCE RULES (操作系统与资源管理)
    # =========================================================================
    {
        'name': 'OS CPU 使用率过高',
        'category': 'os',
        'conditions': [{"metric": "os_cpu_used_pct", "op": ">", "value": 85}],
        'root_cause': '操作系统层面CPU使用率过高，数据库与其他进程竞争CPU',
        'solution': '1. 检查是否有非数据库进程占用CPU\n2. 优化数据库Top SQL减少CPU消耗\n3. 确认CPU没有被频繁的上下文切换浪费\n4. 评估是否需要增加CPU资源或迁移非数据库负载',
        'severity': 'high',
    },
    {
        'name': 'OS 内存不足(Swap使用)',
        'category': 'os',
        'conditions': [{"metric": "os_swap_used_pct", "op": ">", "value": 10}],
        'root_cause': '操作系统Swap使用超过10%，可能存在物理内存不足',
        'solution': '1. 检查SGA+PGA总量是否超过物理内存\n2. 设置HugePages锁定SGA避免被swap\n3. 降低PGA_AGGREGATE_TARGET或SGA大小\n4. 检查是否有其他进程(如备份)占用大量内存',
        'severity': 'high',
    },
    {
        'name': 'OS Load Average 过高',
        'category': 'os',
        'conditions': [{"metric": "os_load_avg", "op": ">", "value": 2.0}],
        'root_cause': 'OS负载均值超过CPU核数2倍，系统排队严重(此处value为per-CPU)',
        'solution': '1. 检查运行队列中是否有大量等待CPU的进程\n2. 检查是否有I/O等待导致的uninterruptible sleep\n3. 优化数据库负载减少活跃进程数\n4. 考虑增加CPU核数或分散负载',
        'severity': 'high',
    },

    # =========================================================================
    # M. DATA GUARD / STANDBY RULES (Data Guard相关)
    # =========================================================================
    {
        'name': 'Data Guard Sync 等待过高',
        'category': 'dataguard',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 5, "event": "LGWR-LNS"}],
        'root_cause': 'LGWR等待LNS进程同步redo到备库的延迟过高(SYNC模式)',
        'solution': '1. 检查主备之间网络延迟和带宽\n2. 考虑从MAXIMUM PROTECTION降级到MAXIMUM AVAILABILITY\n3. 使用ASYNC模式如果RPO允许\n4. 确认备库归档和MRP(恢复进程)没有延迟',
        'severity': 'high',
    },
    {
        'name': 'log file sync 受 Data Guard 影响',
        'category': 'dataguard',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 10, "event": "log file sync"}, {"metric": "dg_sync_enabled", "op": "==", "value": 1}],
        'root_cause': '在SYNC Data Guard模式下，每次COMMIT需要等待备库确认，增加了log file sync时间',
        'solution': '1. 检查V$DATAGUARD_STATS中transport lag\n2. 如果RPO允许切换到ASYNC传输\n3. 优化应用减少COMMIT频率(批量提交)\n4. 使用FAST_START FAILOVER + FASTSYNC(12c+)',
        'severity': 'high',
    },

    # =========================================================================
    # N. STATISTICS & OPTIMIZER RULES (统计信息与优化器)
    # =========================================================================
    {
        'name': '统计信息可能过期',
        'category': 'optimizer',
        'conditions': [{"metric": "stale_stats_tables", "op": ">", "value": 5}],
        'root_cause': '存在统计信息过期的表，可能导致优化器选择次优执行计划',
        'solution': '1. 执行DBMS_STATS.GATHER_DATABASE_STATS(options=>\'GATHER STALE\')\n2. 检查自动统计信息收集Job是否正常运行\n3. 对关键大表手动收集(ESTIMATE_PERCENT=>DBMS_STATS.AUTO_SAMPLE_SIZE)\n4. 检查DBA_TAB_STATISTICS中STALE_STATS=YES的表',
        'severity': 'medium',
    },
    {
        'name': '执行计划不稳定(Plan Flip)',
        'category': 'optimizer',
        'conditions': [{"metric": "plan_hash_changes", "op": ">", "value": 3}],
        'root_cause': '关键SQL的执行计划频繁变化(Plan Flip)，导致性能不稳定',
        'solution': '1. 使用SQL Plan Baseline(SPM)锁定好的执行计划\n2. 创建SQL Profile固定最优计划\n3. 检查统计信息收集是否导致计划变化\n4. 检查ACS(Adaptive Cursor Sharing)行为',
        'severity': 'high',
    },

    # =========================================================================
    # K. EXADATA SPECIFIC RULES
    # =========================================================================
    {
        'name': 'cell smart scan 效率低',
        'category': 'exadata',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 20, "event": "cell single block physical read"}],
        'root_cause': 'Exadata Smart Scan未生效，退化为单块读。可能因为查询不满足Smart Scan条件(非全扫描、使用了不支持的数据类型或函数)',
        'solution': '1. 检查SQL执行计划是否使用TABLE ACCESS STORAGE FULL\n2. 确认Cell Offload Efficiency是否接近100%\n3. 检查是否存在HCC压缩不兼容的列类型\n4. 验证Storage Index是否被有效利用',
        'severity': 'high',
    },
    {
        'name': 'cell offload 效率低',
        'category': 'exadata',
        'conditions': [{"metric": "cell_offload_efficiency", "op": "<", "value": 50}],
        'root_cause': 'Cell Offload处理效率低，大量数据未在存储层过滤。可能因为谓词无法下推到存储层',
        'solution': '1. 检查SQL谓词是否包含不可下推的函数(如PL/SQL函数)\n2. 确认列数据类型是否支持Storage Index\n3. 检查是否需要重建HCC压缩\n4. 考虑使用In-Memory减少存储层扫描',
        'severity': 'medium',
    },
    {
        'name': 'cell interconnect retransmit 高',
        'category': 'exadata',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 5, "event": "cell interconnect retransmit"}],
        'root_cause': 'Exadata存储网格互联重传率高，可能存在InfiniBand网络问题或存储Cell节点负载不均',
        'solution': '1. 检查InfiniBand网络链路状态(ibstatus)\n2. 检查Cell Server负载均衡(cellcli list cell)\n3. 确认是否有Cell节点故障或降级\n4. 检查ASM磁盘组rebalance状态',
        'severity': 'high',
    },
    # =========================================================================
    # L. RAC INTERCONNECT DEEP ANALYSIS RULES
    # =========================================================================
    {
        'name': 'gc current block busy 高等待',
        'category': 'rac',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 10, "event": "gc current block busy"}],
        'root_cause': 'GC Current Block Busy表示远端实例正在修改请求的块，需要等待远端完成修改再发送。说明存在跨实例的热点块并发修改',
        'solution': '1. 识别热点对象(V$SEGMENT_STATISTICS)\n2. 通过分区/哈希分区将不同数据分配到不同实例\n3. 检查应用连接是否正确路由到正确实例\n4. 考虑使用Read-Mostly Locking(12.2+)',
        'severity': 'high',
    },
    {
        'name': 'gc cr block busy 高等待',
        'category': 'rac',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 10, "event": "gc cr block busy"}],
        'root_cause': 'CR Block Busy表示请求CR副本时远端正在修改该块。与gc current block busy类似但是读操作受影响',
        'solution': '1. 检查Top SQL中的热点对象是否跨实例读取\n2. 考虑将只读查询路由到单一实例\n3. 增大_db_block_hash_buckets减少hash bucket争用\n4. 评估是否需要调整GCS服务分配',
        'severity': 'high',
    },
    {
        'name': 'gc congested 互联拥塞',
        'category': 'rac',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 5, "event": "gc current grant congested"}],
        'root_cause': 'GC Grant Congested表示互联网络或LMS进程出现瓶颈。收到grant授权但传输延迟高',
        'solution': '1. 检查互联网络带宽和延迟(ping -s 8192)\n2. 检查LMS进程数量(GCS_SERVER_PROCESSES)是否足够\n3. 确认互联网络没有与用户流量混用\n4. 监控V$CR_BLOCK_SERVER和V$CURRENT_BLOCK_SERVER诊断LMS瓶颈',
        'severity': 'high',
    },
    {
        'name': 'DRM remaster 性能影响',
        'category': 'rac',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 3, "event": "gc remaster"}],
        'root_cause': 'Dynamic Resource Mastering(DRM)重新主控过程中导致性能抖动。DRM在重新分配资源主控权时会短暂冻结相关对象的访问',
        'solution': '1. 考虑禁用DRM: ALTER SYSTEM SET "_gc_policy_time"=0 SCOPE=BOTH\n2. 检查DRM触发频率(V$DYNAMIC_REMASTER_STATS)\n3. 如果DRM频繁触发，可能应用负载分配不均\n4. 升级到19c+可使用改进的DRM算法',
        'severity': 'medium',
    },
    # =========================================================================
    # M. DATAGUARD DIAGNOSTIC RULES
    # =========================================================================
    {
        'name': 'LGWR-LNS 网络延迟高',
        'category': 'dataguard',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 5, "event": "LGWR-LNS wait on channel"}],
        'root_cause': 'Data Guard同步传输延迟高，LGWR需要等待LNS确认redo已发送到备库。直接影响主库事务提交延迟',
        'solution': '1. 检查主备库之间网络延迟(ping RTT)\n2. 考虑从SYNC切换到ASYNC模式减少对主库影响\n3. 增大LOG_ARCHIVE_MAX_PROCESSES提高传输并行度\n4. 检查备库apply是否跟不上导致RFS归档积压\n5. 检查SDU_SIZE(Session Data Unit)是否足够大',
        'severity': 'high',
    },
    {
        'name': 'log file sync 高(DG同步)',
        'category': 'dataguard',
        'conditions': [{"metric": "pct_db_time", "op": ">", "value": 15, "event": "log file sync"}],
        'root_cause': '当Data Guard使用SYNC模式时，log file sync等待包含了网络传输时间。如果平均等待远高于本地log file parallel write，则DG网络延迟是主因',
        'solution': '1. 对比log file sync和log file parallel write的avg wait\n2. 差值即为DG网络传输开销\n3. 考虑SYNC NOAFFIRM减少备库I/O等待\n4. 评估是否可以切换到ASYNC AFFIRM模式\n5. 检查NET_TIMEOUT参数设置',
        'severity': 'high',
    },
    {
        'name': 'archivelog 传输延迟',
        'category': 'dataguard',
        'conditions': [{"metric": "archive_lag_seconds", "op": ">", "value": 300}],
        'root_cause': '归档日志传输到备库存在延迟(>5分钟)，可能导致数据丢失风险增加',
        'solution': '1. 检查LOG_ARCHIVE_DEST_n状态(V$ARCHIVE_DEST)\n2. 增大LOG_ARCHIVE_MAX_PROCESSES\n3. 检查备库RFS进程是否有I/O瓶颈\n4. 检查网络带宽是否被其他流量占用\n5. 考虑使用压缩传输(COMPRESSION=ENABLE)',
        'severity': 'high',
    },
    # =========================================================================
    # N. SQL EXECUTION PLAN STABILITY RULES
    # =========================================================================
    {
        'name': 'SQL Plan变化检测(Plan Flip)',
        'category': 'sql_plan',
        'conditions': [{"metric": "plan_hash_changes", "op": ">", "value": 3}],
        'root_cause': '关键SQL的执行计划频繁变化(Plan Flip)，导致性能不稳定。可能因为统计信息变化、ACS、绑定变量窥视等原因',
        'solution': '1. 使用SQL Plan Baseline(SPM)锁定好的执行计划\n2. 创建SQL Profile固定最优计划\n3. 检查统计信息收集策略是否导致计划变化\n4. 检查ACS(Adaptive Cursor Sharing)行为\n5. 使用DBMS_SPM.EVOLVE_SQL_PLAN_BASELINE定期评估',
        'severity': 'high',
    },
    {
        'name': '绑定变量窥视影响',
        'category': 'sql_plan',
        'conditions': [{"metric": "bind_peeking_impact", "op": ">", "value": 0}],
        'root_cause': '绑定变量窥视(Bind Variable Peeking)导致首次执行的计划不适合后续执行的绑定值分布',
        'solution': '1. 启用Adaptive Cursor Sharing(11g+)\n2. 对偏斜分布的列使用BIND_AWARE hint\n3. 使用SQL Plan Baseline保存多个好的执行计划\n4. 考虑_optim_peek_user_binds=FALSE(不推荐，全局影响大)',
        'severity': 'medium',
    },
]

# Current knowledge version – bump when BUILTIN_RULES change so
# _seed_defaults can detect the need for an incremental sync.
BUILTIN_RULES_VERSION = 2

# ---------------------------------------------------------------------------
# ORACLE PARAMETER RECOMMENDATION KNOWLEDGE BASE
# ---------------------------------------------------------------------------

# Each entry: parameter -> {description, formula/default, version_notes}
PARAMETER_RECOMMENDATIONS = {
    # --- Memory ---
    'SGA_TARGET': {
        'description': 'SGA自动管理总大小',
        'recommendation': '物理内存的40-60%(留给OS和PGA)',
        'formula': 'physical_memory * 0.5',
        'min_value': '1G',
        'notes': '设置SGA_TARGET后，DB_CACHE_SIZE/SHARED_POOL_SIZE等成为下限',
    },
    'SGA_MAX_SIZE': {
        'description': 'SGA最大允许值',
        'recommendation': '>=SGA_TARGET，建议等于SGA_TARGET避免碎片',
        'formula': 'SGA_TARGET',
        'notes': '增大需要重启实例',
    },
    'PGA_AGGREGATE_TARGET': {
        'description': 'PGA自动管理目标大小',
        'recommendation': '物理内存的15-25%，OLTP环境偏低，DSS/DW偏高',
        'formula': 'physical_memory * 0.2',
        'min_value': '512M',
        'trigger_when': ['in_memory_sort_pct < 95', 'pga_over_allocation_count > 0', 'direct path write temp 高等待'],
    },
    'DB_CACHE_SIZE': {
        'description': 'Buffer Cache大小(SGA_TARGET下为下限)',
        'recommendation': 'SGA的60-80%用于Buffer Cache',
        'trigger_when': ['buffer_cache_hit_ratio < 95', 'db file sequential read 高', 'free buffer waits'],
        'notes': '参考Buffer Pool Advisory选择最佳值',
    },
    'SHARED_POOL_SIZE': {
        'description': 'Shared Pool大小(SGA_TARGET下为下限)',
        'recommendation': 'SGA的10-20%，硬解析多时增大',
        'trigger_when': ['library_cache_hit_ratio < 95', 'hard_parse_pct > 10', 'latch: shared pool'],
        'min_value': '300M',
        'notes': '参考Shared Pool Advisory',
    },
    'SHARED_POOL_RESERVED_SIZE': {
        'description': 'Shared Pool保留区(大对象加载)',
        'recommendation': 'SHARED_POOL_SIZE的5-10%',
        'formula': 'shared_pool_size * 0.05',
    },
    'MEMORY_TARGET': {
        'description': 'AMM自动内存管理(SGA+PGA)',
        'recommendation': '在Linux上建议不用AMM，改用ASMM(SGA_TARGET+PGA_AGGREGATE_TARGET)',
        'notes': '11g+可用，但Linux HugePages不兼容AMM。RAC环境不建议使用',
    },
    # --- Redo / Log ---
    'LOG_BUFFER': {
        'description': 'Redo Log Buffer大小',
        'recommendation': '16-64MB，log buffer space等待时增大',
        'default': '自动(隐含约几MB)',
        'trigger_when': ['log buffer space 高等待'],
    },
    'LOG_CHECKPOINT_INTERVAL': {
        'description': '检查点间隔(OS blocks)',
        'recommendation': '0(由redo log大小自动控制)',
        'notes': '通常不需要手动设置，增大redo log文件即可',
    },
    # --- Cursor / Parse ---
    'SESSION_CACHED_CURSORS': {
        'description': '每会话缓存游标数',
        'recommendation': '100-200',
        'default': '50(很多版本)',
        'trigger_when': ['soft_parse_pct < 95', 'execute_to_parse_pct < 50'],
        'notes': '增大可减少软解析开销',
    },
    'OPEN_CURSORS': {
        'description': '每会话最大打开游标数',
        'recommendation': '300-1000',
        'default': '50',
        'notes': '设小会导致ORA-1000，设大只占少量内存',
    },
    'CURSOR_SHARING': {
        'description': '自动绑定变量替换',
        'recommendation': 'EXACT(默认)。仅在无法修改应用时设FORCE作为紧急措施',
        'trigger_when': ['hard_parse_pct > 30'],
        'notes': 'FORCE会导致部分SQL执行计划次优，SIMILAR已在11.2废弃',
    },
    # --- Parallel ---
    'PARALLEL_MAX_SERVERS': {
        'description': '最大并行进程数',
        'recommendation': 'CPU_COUNT * 2 (OLTP)，CPU_COUNT * 4 (DW)',
        'notes': '过大可能导致os thread startup等待和资源争用',
    },
    'PARALLEL_MIN_SERVERS': {
        'description': '预启动的并行进程数',
        'recommendation': '常用并行度的总和，避免os thread startup等待',
        'trigger_when': ['os thread startup 高等待'],
    },
    # --- Undo ---
    'UNDO_RETENTION': {
        'description': 'Undo保留时间(秒)',
        'recommendation': '900-3600，有长查询需更大',
        'default': '900',
        'trigger_when': ['undo_space_used_pct > 85', 'ORA-1555'],
    },
    'UNDO_TABLESPACE': {
        'description': 'Undo表空间名称',
        'recommendation': '确保自动扩展，大小足够UNDO_RETENTION时间内的undo量',
    },
    # --- Optimizer ---
    'OPTIMIZER_ADAPTIVE_FEATURES': {
        'description': '12c自适应优化器特性',
        'recommendation': '12.1建议FALSE(bug多)，12.2+拆分为两个参数',
        'notes': '12.2+使用OPTIMIZER_ADAPTIVE_PLANS和OPTIMIZER_ADAPTIVE_STATISTICS',
    },
    'OPTIMIZER_INDEX_CACHING': {
        'description': '优化器假设索引数据在缓存中的比例',
        'recommendation': '0-100，NL Join多时设50-90可鼓励索引访问',
        'default': '0',
    },
    'OPTIMIZER_INDEX_COST_ADJ': {
        'description': '索引访问成本调整因子',
        'recommendation': '10-50 鼓励走索引(默认100等同全扫)',
        'default': '100',
        'notes': '谨慎修改，全局影响大。优先用SQL Profile/Hint针对性调优',
    },
    # --- I/O ---
    'FILESYSTEMIO_OPTIONS': {
        'description': '文件系统I/O选项',
        'recommendation': 'SETALL(启用异步I/O和直接I/O)',
        'trigger_when': ['db file sequential read 高', 'free buffer waits'],
        'notes': 'Linux上使用ext4/xfs时建议SETALL。ASM自动管理',
    },
    'DISK_ASYNCH_IO': {
        'description': '异步I/O开关',
        'recommendation': 'TRUE(默认)',
        'notes': '仅在特定存储有bug时才设FALSE',
    },
    'DB_FILE_MULTIBLOCK_READ_COUNT': {
        'description': '多块读块数(全扫描)',
        'recommendation': '让Oracle自动管理(不设置)，或128',
        'default': '自动(基于I/O大小)',
        'notes': '设置过大会让优化器倾向全扫描',
    },
    # --- Process / Session ---
    'PROCESSES': {
        'description': '最大进程数',
        'recommendation': '预期并发连接数 * 1.2 + 后台进程(~50)',
        'notes': '修改需重启。SESSIONS自动为PROCESSES*1.5+22',
    },
    'DB_WRITER_PROCESSES': {
        'description': 'DBWR进程数',
        'recommendation': '1-8，I/O密集型增加到CPU_COUNT/8',
        'trigger_when': ['free buffer waits', 'write complete waits'],
    },
    # --- RAC ---
    '_GC_POLICY_TIME': {
        'description': 'DRM重主控评估间隔(隐藏参数)',
        'recommendation': '0(禁用DRM) - 仅在DRM导致性能抖动时',
        'trigger_when': ['gc remaster 高等待'],
        'notes': '隐藏参数，修改需Oracle Support建议',
    },
    # --- Statistics ---
    'STATISTICS_LEVEL': {
        'description': '统计信息收集级别',
        'recommendation': 'TYPICAL(默认)。ALL增加10%开销但提供更多诊断',
        'notes': '不要设BASIC，会禁用ADDM/AWR等诊断功能',
    },
    'RESULT_CACHE_MAX_SIZE': {
        'description': '结果集缓存大小',
        'recommendation': 'SHARED_POOL_SIZE的1-5%，适用于静态数据的重复查询',
        'trigger_when': ['logical_reads_per_sec > 2000000'],
    },
}

# ---------------------------------------------------------------------------
# ORACLE VERSION-SPECIFIC DIAGNOSTIC KNOWLEDGE
# ---------------------------------------------------------------------------

VERSION_SPECIFIC_KNOWLEDGE = {
    '11.2': [
        {
            'feature': 'Serial Direct Path Read',
            'description': '11g开始大表(>5*buffer_cache)自动走direct path read绕过Buffer Cache',
            'impact': 'db file sequential read减少但direct path read增加，不一定是问题',
            'parameter': '_serial_direct_read=FALSE 可禁用(不推荐)',
            'diagnosis': '如果direct path read等待高且buffer cache足够大，检查_small_table_threshold',
        },
        {
            'feature': 'Adaptive Cursor Sharing',
            'description': '11g自适应游标共享，同一SQL根据绑定变量值选择不同计划',
            'impact': '可能导致V$SQL中VERSION_COUNT过高和cursor: pin S wait on X',
            'parameter': '_optimizer_adaptive_cursor_sharing=FALSE 可禁用',
        },
        {
            'feature': 'Deferred Segment Creation',
            'description': '11.2延迟段创建，CREATE TABLE不立即分配空间',
            'impact': '首次INSERT可能慢，大批量建表后exp/imp可能遗漏空表',
            'parameter': 'DEFERRED_SEGMENT_CREATION=FALSE 禁用',
        },
    ],
    '12': [
        {
            'feature': 'Adaptive Plans',
            'description': '12c自适应执行计划，运行时可从NL切换到Hash Join',
            'impact': '12.1有多个bug导致性能退化，12.1建议OPTIMIZER_ADAPTIVE_FEATURES=FALSE',
            'parameter': '12.2+拆分为OPTIMIZER_ADAPTIVE_PLANS和OPTIMIZER_ADAPTIVE_STATISTICS',
        },
        {
            'feature': 'In-Memory Column Store',
            'description': '12c内存列存储，适合分析型查询',
            'impact': '需要额外SGA内存(INMEMORY_SIZE)，不影响DML性能',
            'parameter': 'INMEMORY_SIZE, INMEMORY_QUERY, ALTER TABLE ... INMEMORY',
        },
        {
            'feature': 'Temporal Validity',
            'description': '12c行级时间有效性和Flashback Archive增强',
            'impact': '对undo要求更高',
        },
        {
            'feature': 'Fetch First N Rows',
            'description': '12c原生TOP-N语法(FETCH FIRST N ROWS ONLY)',
            'impact': '替代ROWNUM分页写法，优化器可直接优化',
        },
    ],
    '19': [
        {
            'feature': 'Automatic Indexing',
            'description': '19c自动索引，Oracle自动识别和创建索引',
            'impact': '可能创建大量不必要索引，消耗空间',
            'parameter': 'DBMS_AUTO_INDEX.CONFIGURE(\'AUTO_INDEX_MODE\', \'IMPLEMENT\')',
            'diagnosis': '检查DBA_AUTO_INDEX_CONFIG和报告',
        },
        {
            'feature': 'SQL Quarantine',
            'description': '19c SQL隔离，自动阻止消耗过多资源的SQL',
            'impact': '配合Resource Manager使用',
        },
        {
            'feature': 'Real-Time Statistics',
            'description': '19c实时统计信息收集，DML时自动更新统计信息',
            'impact': '减少统计信息过期导致的计划退化',
            'parameter': '默认开启，_optimizer_gather_stats_on_conventional_dml',
        },
        {
            'feature': 'Hybrid Partitioned Tables',
            'description': '19c混合分区表，部分分区可在外部文件',
            'impact': '归档场景有用',
        },
    ],
    '21': [
        {
            'feature': 'Blockchain Tables',
            'description': '21c区块链表，行只能插入不能修改删除',
            'impact': '审计场景使用',
        },
        {
            'feature': 'In-Memory Enhancements',
            'description': '21c IM列存增强，自动In-Memory和IM Join Groups',
            'impact': '分析型查询性能提升',
        },
    ],
    '23': [
        {
            'feature': 'SQL Domains',
            'description': '23c SQL域，允许在列定义中指定语义约束和校验规则',
            'impact': '简化应用层数据验证，提供更强的数据完整性',
        },
        {
            'feature': 'JSON Relational Duality Views',
            'description': '23c JSON关系二元视图，同一数据可作为JSON文档或关系表访问',
            'impact': '简化微服务架构下的数据访问模式',
        },
        {
            'feature': 'True Cache',
            'description': '23c True Cache，自动维护的只读数据库缓存实例',
            'impact': '可替代客户端缓存方案，自动保持数据一致性',
        },
        {
            'feature': 'Priority Transactions',
            'description': '23c优先事务，可为关键事务设置更高优先级',
            'impact': '高优先级事务可在资源争用时获得更快处理',
        },
        {
            'feature': 'JavaScript Stored Procedures',
            'description': '23c支持JavaScript存储过程，使用GraalVM运行',
            'impact': '前端开发者可直接在数据库中编写逻辑',
        },
    ],
}


# ---------------------------------------------------------------------------
# WAIT EVENT CLASSIFICATION (Oracle Wait Class Knowledge Base)
# ---------------------------------------------------------------------------

# Keys are stored in lowercase for consistent lookup in classify_wait_event().
WAIT_EVENT_CLASS = {
    # User I/O
    'db file sequential read': 'User I/O',
    'db file scattered read': 'User I/O',
    'direct path read': 'User I/O',
    'direct path read temp': 'User I/O',
    'direct path write': 'User I/O',
    'direct path write temp': 'User I/O',
    'read by other session': 'User I/O',
    'db file parallel read': 'User I/O',
    'cell single block physical read': 'User I/O',
    'cell multiblock physical read': 'User I/O',
    'cell smart table scan': 'User I/O',
    'cell smart index scan': 'User I/O',
    'cell list of blocks physical read': 'User I/O',
    # System I/O
    'log file parallel write': 'System I/O',
    'db file parallel write': 'System I/O',
    'control file sequential read': 'System I/O',
    'control file parallel write': 'System I/O',
    'log file sequential read': 'System I/O',
    'log file single write': 'System I/O',
    'lgwr-lns wait on channel': 'System I/O',
    'cell smart file creation': 'System I/O',
    # Commit
    'log file sync': 'Commit',
    # Concurrency
    'buffer busy waits': 'Concurrency',
    'free buffer waits': 'Concurrency',
    'latch: shared pool': 'Concurrency',
    'latch: cache buffers chains': 'Concurrency',
    'latch: library cache': 'Concurrency',
    'latch: cache buffers lru chain': 'Concurrency',
    'latch free': 'Concurrency',
    'library cache pin': 'Concurrency',
    'library cache lock': 'Concurrency',
    'library cache load lock': 'Concurrency',
    'cursor: pin s': 'Concurrency',
    'cursor: pin s wait on x': 'Concurrency',
    'cursor: mutex s': 'Concurrency',
    'cursor: mutex x': 'Concurrency',
    'row cache lock': 'Concurrency',
    'log buffer space': 'Concurrency',
    'enq: hw - contention': 'Concurrency',
    'enq: st - contention': 'Concurrency',
    'gc buffer busy acquire': 'Concurrency',
    'gc buffer busy release': 'Concurrency',
    # Application
    'enq: tx - row lock contention': 'Application',
    'enq: tx - index contention': 'Application',
    'enq: tx - allocate itl entry': 'Application',
    'enq: tm - contention': 'Application',
    'enq: ul - contention': 'Application',
    'sql*net break/reset to client': 'Application',
    # Network
    'sql*net message to client': 'Network',
    'sql*net more data from client': 'Network',
    'sql*net more data to client': 'Network',
    'sql*net message from dblink': 'Network',
    # Configuration
    'log file switch completion': 'Configuration',
    'log file switch (checkpoint incomplete)': 'Configuration',
    'log file switch (archiving needed)': 'Configuration',
    'log file switch (private strand flush incomplete)': 'Configuration',
    'resmgr:cpu quantum': 'Configuration',
    'enq: us - contention': 'Configuration',
    'os thread startup': 'Configuration',
    # Cluster / RAC
    'gc cr block receive time': 'Cluster',
    'gc cr grant 2-way': 'Cluster',
    'gc cr grant congested': 'Cluster',
    'gc current block receive time': 'Cluster',
    'gc current grant 2-way': 'Cluster',
    'gc current grant congested': 'Cluster',
    'gc cr block busy': 'Cluster',
    'gc current block busy': 'Cluster',
    'gc remaster': 'Cluster',
    'gc cr multi block request': 'Cluster',
    'ges inquiry response': 'Cluster',
    'cell interconnect retransmit': 'Cluster',
    # Idle (filtered from analysis)
    'sql*net message from client': 'Idle',
    'px deq: execution msg': 'Idle',
    'px deq: table q normal': 'Idle',
    'streams aq: waiting for messages in the queue': 'Idle',
    'wait for unread message on broadcast channel': 'Idle',
    'class slave wait': 'Idle',
    'rdbms ipc message': 'Idle',
    'pmon timer': 'Idle',
    'smon timer': 'Idle',
    'diag idle wait': 'Idle',
    'jobq slave wait': 'Idle',
    'space manager: slave idle wait': 'Idle',
}

# Reverse map: wait class -> set of events (for aggregate analysis)
WAIT_CLASS_EVENTS = {}
for _evt, _cls in WAIT_EVENT_CLASS.items():
    WAIT_CLASS_EVENTS.setdefault(_cls, set()).add(_evt)

