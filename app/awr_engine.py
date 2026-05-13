"""
Oracle AWR Report Analysis Engine
Modules: Parser -> Scorer -> Correlator -> Baseline -> LLM -> Learning
"""
import re
import json
from datetime import datetime, timedelta
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# BUILTIN RULES
# ---------------------------------------------------------------------------

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
}


def get_parameter_recommendations(problems: list, parsed_data: dict) -> list:
    """Based on identified problems, return relevant Oracle parameter tuning suggestions."""
    recommendations = []
    problem_keywords = set()
    for p in problems:
        title = (p.get('title', '') + ' ' + p.get('evidence', '')).lower()
        problem_keywords.add(title)
        metric = p.get('metric_name', '')
        if metric:
            problem_keywords.add(metric)

    combined = ' '.join(problem_keywords)
    for param_name, info in PARAMETER_RECOMMENDATIONS.items():
        triggers = info.get('trigger_when', [])
        if not triggers:
            continue
        matched = False
        for trigger in triggers:
            trigger_lower = trigger.lower()
            # Check if any problem matches this trigger
            for kw in problem_keywords:
                if trigger_lower in kw or any(t in kw for t in trigger_lower.split()):
                    matched = True
                    break
            if matched:
                break
        if matched:
            recommendations.append({
                'parameter': param_name,
                'description': info.get('description', ''),
                'recommendation': info.get('recommendation', ''),
                'formula': info.get('formula', ''),
                'notes': info.get('notes', ''),
                'trigger': triggers,
            })

    return recommendations


def get_version_specific_notes(db_version: str) -> list:
    """Return version-specific diagnostic notes for the given Oracle version."""
    if not db_version:
        return []
    notes = []
    for version_prefix, items in VERSION_SPECIFIC_KNOWLEDGE.items():
        if db_version.startswith(version_prefix):
            notes.extend(items)
    return notes


def compute_composite_health_score(problems: list, correlations: list, deviations: list) -> int:
    """Compute a 0-100 composite health score (100 = perfectly healthy).

    Scoring weights:
      - Each problem deducts points based on severity.
      - Correlations (cross-dimension root causes) add extra penalty.
      - Baseline deviations add moderate penalty.
    The score is clamped to [0, 100].
    """
    score = 100.0

    # Severity weights for problems
    severity_penalty = {
        'critical': 12,
        'high': 8,
        'serious': 8,
        'medium': 4,
        'warning': 4,
        'low': 2,
    }

    for p in (problems or []):
        sev = p.get('severity', p.get('health_level', 'medium')).lower()
        score -= severity_penalty.get(sev, 4)

    # Correlation findings indicate deeper systemic issues
    for c in (correlations or []):
        score -= 3

    # Baseline deviations (less severe individually)
    for d in (deviations or []):
        sev = d.get('severity', 'medium').lower()
        score -= severity_penalty.get(sev, 2) * 0.5

    return max(0, min(100, int(round(score))))


# ---------------------------------------------------------------------------
# WAIT EVENT CLASSIFICATION (Oracle Wait Class Knowledge Base)
# ---------------------------------------------------------------------------

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
    # System I/O
    'log file parallel write': 'System I/O',
    'db file parallel write': 'System I/O',
    'control file sequential read': 'System I/O',
    'control file parallel write': 'System I/O',
    'log file sequential read': 'System I/O',
    'log file single write': 'System I/O',
    'LGWR-LNS wait on channel': 'System I/O',
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
    'cursor: pin S': 'Concurrency',
    'cursor: pin S wait on X': 'Concurrency',
    'cursor: mutex S': 'Concurrency',
    'cursor: mutex X': 'Concurrency',
    'row cache lock': 'Concurrency',
    'log buffer space': 'Concurrency',
    'enq: HW - contention': 'Concurrency',
    'enq: ST - contention': 'Concurrency',
    'gc buffer busy acquire': 'Concurrency',
    'gc buffer busy release': 'Concurrency',
    # Application
    'enq: TX - row lock contention': 'Application',
    'enq: TX - index contention': 'Application',
    'enq: TX - allocate ITL entry': 'Application',
    'enq: TM - contention': 'Application',
    'enq: UL - contention': 'Application',
    'SQL*Net break/reset to client': 'Application',
    # Network
    'SQL*Net message from client': 'Idle',
    'SQL*Net message to client': 'Network',
    'SQL*Net more data from client': 'Network',
    'SQL*Net more data to client': 'Network',
    'SQL*Net message from dblink': 'Network',
    # Configuration
    'log file switch completion': 'Configuration',
    'log file switch (checkpoint incomplete)': 'Configuration',
    'log file switch (archiving needed)': 'Configuration',
    'log file switch (private strand flush incomplete)': 'Configuration',
    'resmgr:cpu quantum': 'Configuration',
    'enq: US - contention': 'Configuration',
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
    # Idle (filtered from analysis)
    'SQL*Net message from client': 'Idle',
    'PX Deq: Execution Msg': 'Idle',
    'PX Deq: Table Q Normal': 'Idle',
    'Streams AQ: waiting for messages in the queue': 'Idle',
    'wait for unread message on broadcast channel': 'Idle',
    'class slave wait': 'Idle',
    'rdbms ipc message': 'Idle',
    'pmon timer': 'Idle',
    'smon timer': 'Idle',
    'DIAG idle wait': 'Idle',
    'jobq slave wait': 'Idle',
    'Space Manager: slave idle wait': 'Idle',
}

# Reverse map: wait class -> set of events (for aggregate analysis)
WAIT_CLASS_EVENTS = {}
for _evt, _cls in WAIT_EVENT_CLASS.items():
    WAIT_CLASS_EVENTS.setdefault(_cls, set()).add(_evt)


def classify_wait_event(event_name: str) -> str:
    """Return Oracle wait class for an event name. Falls back to 'Other'."""
    if not event_name:
        return 'Other'
    lower = event_name.strip().lower()
    # Exact match first
    if lower in WAIT_EVENT_CLASS:
        return WAIT_EVENT_CLASS[lower]
    # Prefix/substring match
    for pattern, cls in WAIT_EVENT_CLASS.items():
        if pattern in lower or lower in pattern:
            return cls
    # Heuristic fallback
    if lower.startswith('enq:'):
        return 'Application'
    if lower.startswith('gc ') or lower.startswith('ges '):
        return 'Cluster'
    if lower.startswith('latch'):
        return 'Concurrency'
    if lower.startswith('cursor:'):
        return 'Concurrency'
    return 'Other'


# ---------------------------------------------------------------------------
# SQL ANTI-PATTERN DETECTOR
# ---------------------------------------------------------------------------

class SQLAntiPatternDetector:
    """Detect common SQL anti-patterns from SQL text extracted from AWR."""

    # Each pattern: (name, regex/callable, severity, description, suggestion)
    PATTERNS = [
        {
            'name': 'SELECT_STAR',
            'pattern': r'\bSELECT\s+\*\s+FROM\b',
            'severity': 'medium',
            'description': 'SELECT * 查询所有列，增加不必要的I/O和网络传输',
            'suggestion': '明确指定需要的列名，减少数据传输和Buffer Gets',
        },
        {
            'name': 'NO_WHERE_CLAUSE',
            'pattern': r'\bSELECT\b.+?\bFROM\b\s+\w+\s*(?:$|;|\)|ORDER|GROUP|HAVING|UNION)',
            'severity': 'high',
            'description': '查询缺少WHERE条件，可能导致全表扫描',
            'suggestion': '添加合适的WHERE条件限制返回行数',
        },
        {
            'name': 'LEADING_WILDCARD_LIKE',
            'pattern': r"\bLIKE\s+'%[^']+",
            'severity': 'high',
            'description': "LIKE '%xxx' 前导通配符导致索引失效，必须全表扫描",
            'suggestion': '改用全文索引(Oracle Text)或反转字符串索引，避免前导%',
        },
        {
            'name': 'FUNCTION_ON_INDEX_COLUMN',
            'pattern': r'\b(?:TO_CHAR|TO_DATE|TO_NUMBER|TRUNC|UPPER|LOWER|NVL|SUBSTR|TRIM|DECODE)\s*\([^)]*\)\s*=',
            'severity': 'high',
            'description': '函数包裹索引列导致索引失效(隐式全扫描)',
            'suggestion': '创建函数索引，或改写条件避免对列施加函数',
        },
        {
            'name': 'NOT_IN_SUBQUERY',
            'pattern': r'\bNOT\s+IN\s*\(\s*SELECT\b',
            'severity': 'medium',
            'description': 'NOT IN子查询在有NULL值时语义可能错误，且性能差',
            'suggestion': '改用NOT EXISTS或LEFT JOIN ... IS NULL',
        },
        {
            'name': 'CARTESIAN_JOIN',
            'pattern': r'\bFROM\b\s+\w+\s*,\s*\w+(?:\s*,\s*\w+)*\s+WHERE\b(?:(?!(?:\w+\.\w+\s*=\s*\w+\.\w+)).)*$',
            'severity': 'high',
            'description': '可能存在笛卡尔积(Cartesian Join)，缺少表关联条件',
            'suggestion': '检查FROM子句中多表是否都有正确的JOIN条件',
        },
        {
            'name': 'UNION_INSTEAD_OF_UNION_ALL',
            'pattern': r'\bUNION\b(?!\s+ALL\b)',
            'severity': 'low',
            'description': 'UNION 会执行去重排序(SORT UNIQUE)，如果不需要去重应使用 UNION ALL',
            'suggestion': '确认是否需要去重，不需要则改为 UNION ALL 避免排序开销',
        },
        {
            'name': 'ORDER_BY_WITHOUT_LIMIT',
            'pattern': r'\bORDER\s+BY\b(?!.*\b(?:ROWNUM|FETCH\s+FIRST|ROW_NUMBER|OFFSET)\b)',
            'severity': 'low',
            'description': 'ORDER BY 无分页限制，可能对大结果集排序消耗大量PGA/TEMP',
            'suggestion': '添加ROWNUM限制或使用分页(12c+ FETCH FIRST N ROWS)',
        },
        {
            'name': 'IMPLICIT_TYPE_CONVERSION',
            'pattern': r"(?:WHERE|AND|OR)\s+\w+\s*=\s*'?\d{4,}'?",
            'severity': 'medium',
            'description': '可能存在隐式类型转换(字符串列与数值比较)导致索引失效',
            'suggestion': '确保比较两侧数据类型一致，避免Oracle隐式调用TO_NUMBER/TO_CHAR',
        },
        {
            'name': 'NESTED_SUBQUERY_DEEP',
            'pattern': r'(?:\bSELECT\b.*){4,}',
            'severity': 'medium',
            'description': '嵌套子查询层级过深(4+层)，优化器可能无法有效优化',
            'suggestion': '使用WITH(CTE)改写子查询，或拆分为多步操作',
        },
        {
            'name': 'DISTINCT_ON_LARGE_SET',
            'pattern': r'\bSELECT\s+DISTINCT\b',
            'severity': 'low',
            'description': 'DISTINCT 需要排序去重，大结果集消耗PGA/TEMP',
            'suggestion': '检查是否因JOIN不当导致重复行，修正JOIN后移除DISTINCT',
        },
        {
            'name': 'HINT_FULL_TABLE_SCAN',
            'pattern': r'/\*\+.*\bFULL\s*\(\s*\w+\s*\).*\*/',
            'severity': 'medium',
            'description': 'SQL Hint强制全表扫描，可能是历史遗留或不适当的优化',
            'suggestion': '评估全扫描提示是否仍然合理，更新统计信息后考虑移除',
        },
    ]

    def detect(self, sql_text_list: list) -> list:
        """Detect anti-patterns in a list of SQL text strings.
        Each item should be a dict with at least 'sql_text' and optionally 'sql_id'.
        Returns list of finding dicts."""
        findings = []
        if not sql_text_list:
            return findings

        for sql_entry in sql_text_list:
            if isinstance(sql_entry, str):
                sql_text = sql_entry
                sql_id = 'unknown'
            elif isinstance(sql_entry, dict):
                sql_text = sql_entry.get('sql_text', sql_entry.get('SQL Text', ''))
                sql_id = sql_entry.get('sql_id', sql_entry.get('SQL Id', 'unknown'))
            else:
                continue

            if not sql_text or len(sql_text.strip()) < 10:
                continue

            sql_upper = sql_text.upper()
            for pattern_def in self.PATTERNS:
                try:
                    if re.search(pattern_def['pattern'], sql_upper, re.IGNORECASE | re.DOTALL):
                        findings.append({
                            'sql_id': sql_id,
                            'anti_pattern': pattern_def['name'],
                            'severity': pattern_def['severity'],
                            'description': pattern_def['description'],
                            'suggestion': pattern_def['suggestion'],
                            'sql_snippet': sql_text[:200],
                        })
                except re.error:
                    pass

        return findings

    def detect_from_parsed(self, parsed_data: dict) -> list:
        """Convenience method: extract SQL text from parsed AWR data and detect."""
        sql_entries = []
        top_sql = parsed_data.get('top_sql', {})
        if isinstance(top_sql, dict):
            for section_name, sql_list in top_sql.items():
                if isinstance(sql_list, list):
                    for entry in sql_list:
                        if isinstance(entry, dict) and entry.get('sql_text', entry.get('SQL Text', '')):
                            sql_entries.append(entry)
        elif isinstance(top_sql, list):
            for entry in top_sql:
                if isinstance(entry, dict) and entry.get('sql_text', entry.get('SQL Text', '')):
                    sql_entries.append(entry)

        # Deduplicate by sql_id
        seen = set()
        unique_entries = []
        for e in sql_entries:
            sid = e.get('sql_id', e.get('SQL Id', ''))
            if sid and sid not in seen:
                seen.add(sid)
                unique_entries.append(e)
            elif not sid:
                unique_entries.append(e)

        return self.detect(unique_entries)


# ---------------------------------------------------------------------------
# AWR PARSER
# ---------------------------------------------------------------------------

class AWRParser:
    """Parse Oracle AWR HTML reports and extract structured metrics."""

    def parse(self, html_content: str) -> dict:
        """Parse AWR HTML and return structured data dict."""
        try:
            soup = BeautifulSoup(html_content, 'lxml')
        except Exception:
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
            pass
        return result

    def _extract_io_stats(self, soup) -> list:
        try:
            table = self._find_table_after(soup, r'IOStat|I/O\s*Stat|Tablespace\s+IO\s+Stats')
            return self._parse_table(table)
        except Exception:
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
            return []

    def _extract_os_stats(self, soup) -> list:
        try:
            table = self._find_table_after(soup, r'Operating\s+System\s+Statistics|OS\s+Statistics')
            return self._parse_table(table)
        except Exception:
            return []

    def _extract_rac_stats(self, soup) -> list:
        try:
            table = self._find_table_after(soup, r'RAC\s+Statistics|Global\s+Cache')
            return self._parse_table(table)
        except Exception:
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
            pass
        return result

    def _extract_enqueue_activity(self, soup) -> list:
        """Extract Enqueue Activity (lock wait breakdown)."""
        try:
            table = self._find_table_after(soup, r'Enqueue\s+Activity')
            return self._parse_table(table)
        except Exception:
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
            pass
        return result

    def _extract_wait_histogram(self, soup) -> list:
        """Extract Wait Event Histogram (time distribution buckets)."""
        try:
            table = self._find_table_after(soup, r'Wait\s+Event\s+Histogram')
            return self._parse_table(table)
        except Exception:
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
            pass
        return result

    def _extract_wait_class_summary(self, soup) -> list:
        """Extract Foreground Wait Class summary (if present in AWR)."""
        try:
            table = self._find_table_after(soup, r'(?:Foreground\s+)?Wait\s+Class(?:es)?')
            rows = self._parse_table(table)
            return rows if rows else []
        except Exception:
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
            pass
        return result

    def _safe_float(self, val, default=0.0) -> float:
        """Safely convert a string to float."""
        try:
            if val is None:
                return default
            s = str(val).strip()
            if not s:
                return default
            s = s.replace(',', '').replace('%', '').replace(' ', '')
            multiplier = 1
            if s.upper().endswith('G'):
                multiplier = 1e9
                s = s[:-1]
            elif s.upper().endswith('M'):
                multiplier = 1e6
                s = s[:-1]
            elif s.upper().endswith('K'):
                multiplier = 1000
                s = s[:-1]
            return float(s) * multiplier
        except (ValueError, TypeError):
            return default


# ---------------------------------------------------------------------------
# METRIC SCORER
# ---------------------------------------------------------------------------

class MetricScorer:
    """Score AWR metrics against configurable thresholds."""

    # Default thresholds: {metric_key: (warning_threshold, serious_threshold, unit, direction)}
    # direction: 'higher_worse' means higher value = worse, 'lower_worse' means lower = worse
    DEFAULT_THRESHOLDS = {
        # --- Load / Capacity ---
        'aas_per_cpu': (0.7, 1.0, 'ratio', 'higher_worse'),
        'db_time_ratio': (1.0, 3.0, 'ratio', 'higher_worse'),
        'transactions_per_sec': (500.0, 2000.0, 'txn/s', 'higher_worse'),
        'logical_reads_per_sec': (2_000_000, 5_000_000, 'reads/s', 'higher_worse'),
        'physical_reads_per_sec': (50_000, 150_000, 'reads/s', 'higher_worse'),
        # --- Wait Events ---
        'top_event_pct_db_time': (15.0, 30.0, '%DB Time', 'higher_worse'),
        'db_file_sequential_read_avg_wait': (10.0, 20.0, 'ms', 'higher_worse'),
        'db_file_scattered_read_avg_wait': (10.0, 20.0, 'ms', 'higher_worse'),
        'log_file_sync_avg_wait': (5.0, 15.0, 'ms', 'higher_worse'),
        'log_file_parallel_write_avg_wait': (5.0, 15.0, 'ms', 'higher_worse'),
        'buffer_busy_waits_avg_wait': (5.0, 20.0, 'ms', 'higher_worse'),
        'read_by_other_session_avg_wait': (10.0, 30.0, 'ms', 'higher_worse'),
        'enq_tx_row_lock_avg_wait': (50.0, 200.0, 'ms', 'higher_worse'),
        # --- Parse ---
        'hard_parse_pct': (10.0, 30.0, '%', 'higher_worse'),
        'hard_parses_per_sec': (100.0, 500.0, 'parses/s', 'higher_worse'),
        'total_parses_per_sec': (1000.0, 5000.0, 'parses/s', 'higher_worse'),
        'execute_to_parse_pct': (50.0, 30.0, '%', 'lower_worse'),
        'soft_parse_pct': (90.0, 70.0, '%', 'lower_worse'),
        'parse_cpu_to_elapsed_pct': (50.0, 20.0, '%', 'lower_worse'),
        # --- SQL Efficiency ---
        'buffer_gets_per_exec': (10000, 100000, 'gets', 'higher_worse'),
        'disk_reads_per_exec': (100, 1000, 'reads', 'higher_worse'),
        'sql_executions_per_sec': (10000, 50000, 'exec/s', 'higher_worse'),
        'top1_sql_pct_db_time': (30.0, 50.0, '%DB Time', 'higher_worse'),
        # --- Memory / Cache ---
        'buffer_cache_hit_ratio': (95.0, 90.0, '%', 'lower_worse'),
        'library_cache_hit_ratio': (99.0, 95.0, '%', 'lower_worse'),
        'shared_pool_free_pct': (10.0, 5.0, '%', 'lower_worse'),
        'in_memory_sort_pct': (95.0, 85.0, '%', 'lower_worse'),
        'latch_hit_pct': (99.0, 98.0, '%', 'lower_worse'),
        'pga_over_allocation_count': (0, 100, 'count', 'higher_worse'),
        # --- I/O ---
        'avg_read_time': (10.0, 20.0, 'ms', 'higher_worse'),
        'avg_write_time': (5.0, 15.0, 'ms', 'higher_worse'),
        'tablespace_io_pct': (60.0, 80.0, '%', 'higher_worse'),
        # --- Redo ---
        'redo_size_per_sec': (50_000_000, 200_000_000, 'bytes/s', 'higher_worse'),
        'log_switches_per_hour': (6, 20, 'switches/hr', 'higher_worse'),
        # --- RAC ---
        'gc_cr_block_receive_time': (1.0, 3.0, 'ms', 'higher_worse'),
        'gc_current_block_receive_time': (1.0, 3.0, 'ms', 'higher_worse'),
        # --- Undo / Temp ---
        'undo_space_used_pct': (85.0, 95.0, '%', 'higher_worse'),
        'temp_space_used_pct': (80.0, 95.0, '%', 'higher_worse'),
        # --- OS ---
        'os_cpu_used_pct': (85.0, 95.0, '%', 'higher_worse'),
        'os_swap_used_pct': (10.0, 30.0, '%', 'higher_worse'),
        'os_load_avg': (2.0, 4.0, 'per CPU', 'higher_worse'),
    }

    def __init__(self, custom_thresholds=None):
        self.thresholds = dict(self.DEFAULT_THRESHOLDS)
        if custom_thresholds:
            self.thresholds.update(custom_thresholds)

    def score_metric(self, metric_key: str, value: float) -> dict:
        """Score a single metric. Returns dict with level, evidence, thresholds."""
        if metric_key not in self.thresholds:
            return {'level': 'healthy', 'evidence': '', 'warning_threshold': None, 'serious_threshold': None}

        warning_threshold, serious_threshold, unit, direction = self.thresholds[metric_key]

        level = 'healthy'
        if direction == 'higher_worse':
            if value >= serious_threshold:
                level = 'serious'
            elif value >= warning_threshold:
                level = 'warning'
        elif direction == 'lower_worse':
            if value <= serious_threshold:
                level = 'serious'
            elif value <= warning_threshold:
                level = 'warning'

        evidence = ''
        if level != 'healthy':
            metric_display = metric_key.replace('_', ' ')
            if level == 'serious':
                evidence = f"{metric_display} 当前值 {value}{unit}, 超过严重阈值 {serious_threshold}{unit}"
            else:
                evidence = f"{metric_display} 当前值 {value}{unit}, 超过警告阈值 {warning_threshold}{unit}"

        return {
            'level': level,
            'evidence': evidence,
            'warning_threshold': warning_threshold,
            'serious_threshold': serious_threshold,
        }

    def _safe_float(self, val, default=0.0):
        """Safely convert a value to float."""
        try:
            if val is None:
                return default
            return float(val)
        except (ValueError, TypeError):
            return default

    def _get_problem_type(self, metric_key):
        """Map metric key to problem type category."""
        IO_KEYS = ('db_file_sequential_read_avg_wait', 'db_file_scattered_read_avg_wait',
                    'avg_read_time', 'avg_write_time', 'tablespace_io_pct', 'physical_reads_per_sec')
        WAIT_KEYS = ('log_file_sync_avg_wait', 'log_file_parallel_write_avg_wait',
                     'top_event_pct_db_time', 'buffer_busy_waits_avg_wait',
                     'read_by_other_session_avg_wait', 'enq_tx_row_lock_avg_wait')
        SQL_KEYS = ('buffer_gets_per_exec', 'disk_reads_per_exec', 'sql_executions_per_sec',
                    'top1_sql_pct_db_time')
        MEMORY_KEYS = ('buffer_cache_hit_ratio', 'library_cache_hit_ratio', 'shared_pool_free_pct',
                       'in_memory_sort_pct', 'latch_hit_pct', 'pga_over_allocation_count')
        PARSE_KEYS = ('hard_parse_pct', 'hard_parses_per_sec', 'total_parses_per_sec',
                      'execute_to_parse_pct', 'soft_parse_pct', 'parse_cpu_to_elapsed_pct')
        REDO_KEYS = ('redo_size_per_sec', 'log_switches_per_hour')
        RAC_KEYS = ('gc_cr_block_receive_time', 'gc_current_block_receive_time')
        LOAD_KEYS = ('db_time_ratio', 'aas_per_cpu', 'transactions_per_sec', 'logical_reads_per_sec')
        OS_KEYS = ('os_cpu_used_pct', 'os_swap_used_pct', 'os_load_avg')
        UNDO_TEMP_KEYS = ('undo_space_used_pct', 'temp_space_used_pct')

        if metric_key in IO_KEYS:
            return 'io'
        elif metric_key in WAIT_KEYS:
            return 'wait_event'
        elif metric_key in SQL_KEYS:
            return 'sql'
        elif metric_key in MEMORY_KEYS:
            return 'memory'
        elif metric_key in PARSE_KEYS:
            return 'parse'
        elif metric_key in REDO_KEYS:
            return 'redo'
        elif metric_key in RAC_KEYS:
            return 'rac'
        elif metric_key in LOAD_KEYS:
            return 'load'
        elif metric_key in OS_KEYS:
            return 'os'
        elif metric_key in UNDO_TEMP_KEYS:
            return 'undo_temp'
        return 'other'

    def _get_problem_title(self, metric_key, value, unit):
        """Generate Chinese title for a problem."""
        titles = {
            # Load
            'aas_per_cpu': f'平均活跃会话/CPU比率过高 ({value}{unit})',
            'db_time_ratio': f'DB Time远超CPU Time ({value}{unit})',
            'transactions_per_sec': f'事务量过高 ({value}{unit})',
            'logical_reads_per_sec': f'逻辑读/秒过高 ({value}{unit})',
            'physical_reads_per_sec': f'物理读IOPS过高 ({value}{unit})',
            # Wait events
            'top_event_pct_db_time': f'Top等待事件占比过高 ({value}{unit})',
            'db_file_sequential_read_avg_wait': f'db file sequential read 平均等待过高 ({value}{unit})',
            'db_file_scattered_read_avg_wait': f'db file scattered read 平均等待过高 ({value}{unit})',
            'log_file_sync_avg_wait': f'log file sync 平均等待过高 ({value}{unit})',
            'log_file_parallel_write_avg_wait': f'log file parallel write 平均等待过高 ({value}{unit})',
            'buffer_busy_waits_avg_wait': f'buffer busy waits 平均等待过高 ({value}{unit})',
            'read_by_other_session_avg_wait': f'read by other session 平均等待过高 ({value}{unit})',
            'enq_tx_row_lock_avg_wait': f'行锁等待时间过高 ({value}{unit})',
            # Parse
            'hard_parse_pct': f'硬解析比例过高 ({value}{unit})',
            'hard_parses_per_sec': f'每秒硬解析次数过高 ({value}{unit})',
            'total_parses_per_sec': f'每秒总解析次数过高 ({value}{unit})',
            'execute_to_parse_pct': f'Execute to Parse%过低 ({value}{unit})',
            'soft_parse_pct': f'软解析比例过低 ({value}{unit})',
            'parse_cpu_to_elapsed_pct': f'Parse CPU/Elapsed%过低 ({value}{unit})',
            # SQL
            'buffer_gets_per_exec': f'SQL逻辑读过高 ({value}{unit})',
            'disk_reads_per_exec': f'SQL物理读过高 ({value}{unit})',
            'sql_executions_per_sec': f'SQL执行频率过高 ({value}{unit})',
            'top1_sql_pct_db_time': f'Top1 SQL占DB Time过高 ({value}{unit})',
            # Memory
            'buffer_cache_hit_ratio': f'Buffer Cache 命中率过低 ({value}{unit})',
            'library_cache_hit_ratio': f'Library Cache 命中率过低 ({value}{unit})',
            'shared_pool_free_pct': f'Shared Pool 空闲不足 ({value}{unit})',
            'in_memory_sort_pct': f'内存排序比例过低 ({value}{unit})',
            'latch_hit_pct': f'Latch命中率过低 ({value}{unit})',
            'pga_over_allocation_count': f'PGA过度分配 ({value}{unit})',
            # I/O
            'avg_read_time': f'I/O平均读取延迟过高 ({value}{unit})',
            'avg_write_time': f'I/O平均写入延迟过高 ({value}{unit})',
            'tablespace_io_pct': f'单表空间I/O过于集中 ({value}{unit})',
            # Redo
            'redo_size_per_sec': f'Redo生成量过大 ({value}{unit})',
            'log_switches_per_hour': f'日志切换过于频繁 ({value}{unit})',
            # RAC
            'gc_cr_block_receive_time': f'RAC GC CR块传输延迟过高 ({value}{unit})',
            'gc_current_block_receive_time': f'RAC GC Current块传输延迟过高 ({value}{unit})',
            # Undo / Temp
            'undo_space_used_pct': f'Undo表空间使用率过高 ({value}{unit})',
            'temp_space_used_pct': f'临时表空间使用率过高 ({value}{unit})',
            # OS
            'os_cpu_used_pct': f'OS CPU使用率过高 ({value}{unit})',
            'os_swap_used_pct': f'OS Swap使用过多 ({value}{unit})',
            'os_load_avg': f'OS负载均值过高 ({value}{unit})',
        }
        return titles.get(metric_key, f'{metric_key} 异常 ({value}{unit})')

    def score_all(self, parsed_data: dict, report=None) -> list:
        """Score all extracted metrics. Returns list of problem dicts."""
        if not parsed_data:
            return []

        problems = []
        scored_metrics = {}  # metric_key -> value

        # -----------------------------------------------------------------
        # 1. load_profile computed values
        # -----------------------------------------------------------------
        try:
            load_profile = parsed_data.get('load_profile')
            if load_profile and isinstance(load_profile, dict):
                computed = load_profile.get('computed', {})
                if computed:
                    db_time = self._safe_float(computed.get('db_time'))
                    db_cpu = self._safe_float(computed.get('db_cpu'))
                    if db_cpu > 0:
                        scored_metrics['db_time_ratio'] = db_time / db_cpu

                    hard_parses = self._safe_float(computed.get('hard_parses'))
                    parses = self._safe_float(computed.get('parses'))
                    if parses > 0:
                        scored_metrics['hard_parse_pct'] = hard_parses / parses * 100
                        scored_metrics['hard_parses_per_sec'] = hard_parses
                        scored_metrics['total_parses_per_sec'] = parses

                    redo_size = computed.get('redo_size')
                    if redo_size is not None:
                        scored_metrics['redo_size_per_sec'] = self._safe_float(redo_size)

                    # New: transactions, logical reads, physical reads, executes
                    txn = self._safe_float(computed.get('transactions'))
                    if txn > 0:
                        scored_metrics['transactions_per_sec'] = txn
                    logical_reads = self._safe_float(computed.get('logical_reads'))
                    if logical_reads > 0:
                        scored_metrics['logical_reads_per_sec'] = logical_reads
                    physical_reads = self._safe_float(computed.get('physical_reads'))
                    if physical_reads > 0:
                        scored_metrics['physical_reads_per_sec'] = physical_reads
                    executes = self._safe_float(computed.get('executes'))
                    if executes > 0:
                        scored_metrics['sql_executions_per_sec'] = executes
        except Exception:
            pass

        # -----------------------------------------------------------------
        # 2. top_events - score avg_wait for all known events
        # -----------------------------------------------------------------
        try:
            top_events = parsed_data.get('top_events', [])
            if top_events and isinstance(top_events, list):
                if len(top_events) > 0:
                    first_event = top_events[0]
                    pct_val = self._safe_float(first_event.get('pct_db_time'))
                    if pct_val > 0:
                        scored_metrics['top_event_pct_db_time'] = pct_val

                # Map event names -> metric keys for avg_wait scoring
                EVENT_AVG_WAIT_MAP = {
                    'db file sequential read': 'db_file_sequential_read_avg_wait',
                    'db file scattered read': 'db_file_scattered_read_avg_wait',
                    'log file sync': 'log_file_sync_avg_wait',
                    'log file parallel write': 'log_file_parallel_write_avg_wait',
                    'buffer busy waits': 'buffer_busy_waits_avg_wait',
                    'read by other session': 'read_by_other_session_avg_wait',
                    'enq: tx - row lock contention': 'enq_tx_row_lock_avg_wait',
                }
                # Also track top1 SQL pct from top events for DB CPU
                for event in top_events:
                    event_name = (event.get('name') or event.get('event') or '').strip().lower()
                    avg_wait = self._safe_float(event.get('avg_wait'))
                    for pattern, metric_key in EVENT_AVG_WAIT_MAP.items():
                        if event_name == pattern and avg_wait > 0:
                            scored_metrics[metric_key] = avg_wait
                            break
        except Exception:
            pass

        # -----------------------------------------------------------------
        # 3. top_sql - buffer gets, disk reads, top1 pct
        # -----------------------------------------------------------------
        try:
            top_sql = parsed_data.get('top_sql', {})
            if top_sql and isinstance(top_sql, dict):
                sql_by_gets = top_sql.get('SQL ordered by Gets') or top_sql.get('sql_by_gets') or []
                if sql_by_gets and len(sql_by_gets) > 0:
                    top_entry = sql_by_gets[0]
                    gets_per_exec = self._safe_float(
                        top_entry.get('gets_per_exec') or top_entry.get('gets/exec')
                        or top_entry.get('Buffer Gets per Exec', 0)
                    )
                    if gets_per_exec > 0:
                        scored_metrics['buffer_gets_per_exec'] = gets_per_exec

                sql_by_reads = top_sql.get('SQL ordered by Reads') or top_sql.get('sql_by_reads') or []
                if sql_by_reads and len(sql_by_reads) > 0:
                    top_entry = sql_by_reads[0]
                    reads_per_exec = self._safe_float(
                        top_entry.get('reads_per_exec') or top_entry.get('reads/exec')
                        or top_entry.get('Physical Reads per Exec', 0)
                    )
                    if reads_per_exec > 0:
                        scored_metrics['disk_reads_per_exec'] = reads_per_exec

                # Top1 SQL by Elapsed Time as % of DB Time
                sql_by_elapsed = top_sql.get('SQL ordered by Elapsed Time') or []
                if sql_by_elapsed and len(sql_by_elapsed) > 0:
                    top1_pct = self._safe_float(
                        sql_by_elapsed[0].get('%Total') or sql_by_elapsed[0].get('pct_db_time')
                        or sql_by_elapsed[0].get('% Total DB Time', 0)
                    )
                    if top1_pct > 0:
                        scored_metrics['top1_sql_pct_db_time'] = top1_pct
        except Exception:
            pass

        # -----------------------------------------------------------------
        # 4. instance_efficiency - ALL efficiency metrics
        # -----------------------------------------------------------------
        try:
            instance_eff = parsed_data.get('instance_efficiency', [])
            if instance_eff:
                # Unified extraction helper
                def _match_efficiency(name, val):
                    nl = name.lower() if name else ''
                    fval = self._safe_float(val)
                    if fval <= 0:
                        return
                    if 'buffer' in nl and ('hit' in nl or 'nowait' in nl):
                        scored_metrics.setdefault('buffer_cache_hit_ratio', fval)
                    elif 'library' in nl and 'hit' in nl:
                        scored_metrics.setdefault('library_cache_hit_ratio', fval)
                    elif 'soft parse' in nl:
                        scored_metrics.setdefault('soft_parse_pct', fval)
                    elif 'execute to parse' in nl:
                        scored_metrics.setdefault('execute_to_parse_pct', fval)
                    elif 'latch hit' in nl:
                        scored_metrics.setdefault('latch_hit_pct', fval)
                    elif 'in-memory sort' in nl or 'memory sort' in nl:
                        scored_metrics.setdefault('in_memory_sort_pct', fval)
                    elif 'parse cpu' in nl and 'elapsed' in nl:
                        scored_metrics.setdefault('parse_cpu_to_elapsed_pct', fval)
                    elif 'non-parse cpu' in nl:
                        pass  # informational, not scored separately

                if isinstance(instance_eff, list):
                    for item in instance_eff:
                        name = (item.get('name') or item.get('stat_name')
                                or item.get('metric') or '').strip()
                        val = item.get('value') or item.get('pct')
                        _match_efficiency(name, val)
                elif isinstance(instance_eff, dict):
                    for name, val in instance_eff.items():
                        _match_efficiency(name, val)
        except Exception:
            pass

        # -----------------------------------------------------------------
        # 5. rac_stats - gc cr + gc current
        # -----------------------------------------------------------------
        try:
            rac_stats = parsed_data.get('rac_stats', [])
            if rac_stats and isinstance(rac_stats, list):
                for stat in rac_stats:
                    name = (stat.get('name') or stat.get('stat_name') or '').strip().lower()
                    val = self._safe_float(stat.get('value') or stat.get('avg_wait'))
                    if val > 0:
                        if 'gc cr block receive time' in name:
                            scored_metrics['gc_cr_block_receive_time'] = val
                        elif 'gc current block receive time' in name:
                            scored_metrics['gc_current_block_receive_time'] = val
        except Exception:
            pass

        # -----------------------------------------------------------------
        # 6. AAS/CPU
        # -----------------------------------------------------------------
        try:
            if report and hasattr(report, 'cpu_count') and report.cpu_count:
                cpu_count = self._safe_float(report.cpu_count)
                load_profile = parsed_data.get('load_profile')
                if load_profile and isinstance(load_profile, dict):
                    computed = load_profile.get('computed', {})
                    db_time = self._safe_float(computed.get('db_time'))
                    elapsed = self._safe_float(computed.get('elapsed_seconds') or computed.get('elapsed'))
                    if elapsed > 0 and cpu_count > 0:
                        aas = db_time / elapsed
                        aas_per_cpu = aas / cpu_count
                        scored_metrics['aas_per_cpu'] = aas_per_cpu
        except Exception:
            pass

        # -----------------------------------------------------------------
        # 7. I/O stats - read/write latency, tablespace concentration
        # -----------------------------------------------------------------
        try:
            io_stats = parsed_data.get('io_stats', [])
            if io_stats and isinstance(io_stats, list):
                total_reads = 0
                max_reads = 0
                for io in io_stats:
                    reads = self._safe_float(io.get('Physical Reads', io.get('reads', io.get('physical_reads', 0))))
                    total_reads += reads
                    if reads > max_reads:
                        max_reads = reads
                    # avg read/write time per tablespace
                    avg_rd = self._safe_float(io.get('Av Rd(ms)', io.get('avg_read_ms', io.get('Av Rd', 0))))
                    avg_wr = self._safe_float(io.get('Av Wr(ms)', io.get('avg_write_ms', io.get('Av Wr', 0))))
                    if avg_rd > scored_metrics.get('avg_read_time', 0):
                        scored_metrics['avg_read_time'] = avg_rd
                    if avg_wr > scored_metrics.get('avg_write_time', 0):
                        scored_metrics['avg_write_time'] = avg_wr
                if total_reads > 0 and max_reads > 0:
                    scored_metrics['tablespace_io_pct'] = (max_reads / total_reads) * 100
        except Exception:
            pass

        # -----------------------------------------------------------------
        # 8. OS stats
        # -----------------------------------------------------------------
        try:
            os_stats = parsed_data.get('os_stats', [])
            if os_stats and isinstance(os_stats, list):
                busy_time = idle_time = 0
                total_physical_mem = 0
                free_swap = total_swap = 0
                for stat in os_stats:
                    name = (stat.get('name') or stat.get('stat_name') or stat.get('Statistic', '')).strip().lower()
                    val = self._safe_float(stat.get('value') or stat.get('Value', 0))
                    if 'busy_time' in name or 'busy time' in name:
                        busy_time = val
                    elif 'idle_time' in name or 'idle time' in name:
                        idle_time = val
                    elif 'load' in name and ('avg' in name or 'average' in name):
                        if val > 0:
                            cpu_count = 1
                            if report and hasattr(report, 'cpu_count') and report.cpu_count:
                                cpu_count = max(1, report.cpu_count)
                            scored_metrics['os_load_avg'] = val / cpu_count
                    elif 'physical memory' in name and 'total' in name:
                        total_physical_mem = val
                    elif 'free swap' in name or 'swap free' in name:
                        free_swap = val
                    elif ('total swap' in name or 'swap space' in name) and 'free' not in name:
                        total_swap = val
                if busy_time > 0 and (busy_time + idle_time) > 0:
                    scored_metrics['os_cpu_used_pct'] = (busy_time / (busy_time + idle_time)) * 100
                if total_swap > 0:
                    used_swap = total_swap - free_swap
                    scored_metrics['os_swap_used_pct'] = (used_swap / total_swap) * 100
            elif os_stats and isinstance(os_stats, dict):
                if os_stats.get('cpu_used_pct'):
                    scored_metrics['os_cpu_used_pct'] = self._safe_float(os_stats['cpu_used_pct'])
                if os_stats.get('load_avg'):
                    scored_metrics['os_load_avg'] = self._safe_float(os_stats['load_avg'])
                if os_stats.get('swap_used_pct'):
                    scored_metrics['os_swap_used_pct'] = self._safe_float(os_stats['swap_used_pct'])
        except Exception:
            pass

        # -----------------------------------------------------------------
        # 9. memory_stats - shared pool free, PGA over-allocation
        # -----------------------------------------------------------------
        try:
            memory_stats = parsed_data.get('memory_stats', {})
            if memory_stats:
                # SGA sub-components
                sga_list = memory_stats.get('SGA', []) if isinstance(memory_stats, dict) else []
                if isinstance(sga_list, list):
                    total_sga = 0
                    free_mem = 0
                    for item in sga_list:
                        name = (item.get('Pool', '') + ' ' + item.get('Name', item.get('name', ''))).lower()
                        size = self._safe_float(item.get('Size', item.get('size', item.get('Bytes', 0))))
                        total_sga += size
                        if 'free' in name and 'shared pool' in name:
                            free_mem += size
                    if total_sga > 0 and free_mem > 0:
                        scored_metrics['shared_pool_free_pct'] = (free_mem / total_sga) * 100

                # PGA stats
                pga_list = memory_stats.get('PGA', []) if isinstance(memory_stats, dict) else []
                if isinstance(pga_list, list):
                    for item in pga_list:
                        name = (item.get('name', item.get('Name', item.get('Statistic', '')))).lower()
                        val = self._safe_float(item.get('value', item.get('Value', item.get('Bytes', 0))))
                        if 'over alloc' in name and val > 0:
                            scored_metrics['pga_over_allocation_count'] = val

                # Advisory sections
                advisories = parsed_data.get('advisories', {})
                if isinstance(advisories, dict):
                    pga_advice = advisories.get('PGA', [])
                    if isinstance(pga_advice, list):
                        for row in pga_advice:
                            over = self._safe_float(row.get('Over Alloc', row.get('over_allocation_count', 0)))
                            if over > 0:
                                scored_metrics.setdefault('pga_over_allocation_count', over)
        except Exception:
            pass

        # -----------------------------------------------------------------
        # 10. redo_stats - log switches per hour
        # -----------------------------------------------------------------
        try:
            redo_stats = parsed_data.get('redo_stats', {})
            if redo_stats and isinstance(redo_stats, dict):
                log_switches = self._safe_float(redo_stats.get('log_switches', 0))
                elapsed_seconds = self._safe_float(
                    parsed_data.get('snap_info', {}).get('elapsed_seconds', 0)
                )
                if log_switches > 0 and elapsed_seconds > 0:
                    scored_metrics['log_switches_per_hour'] = log_switches / (elapsed_seconds / 3600)
                elif log_switches > 0:
                    scored_metrics['log_switches_per_hour'] = log_switches  # assume per hour
        except Exception:
            pass

        # -----------------------------------------------------------------
        # 11. parse_stats supplementary
        # -----------------------------------------------------------------
        try:
            parse_stats = parsed_data.get('parse_stats', {})
            if parse_stats and isinstance(parse_stats, dict):
                if parse_stats.get('execute_to_parse_pct') and 'execute_to_parse_pct' not in scored_metrics:
                    scored_metrics['execute_to_parse_pct'] = self._safe_float(parse_stats['execute_to_parse_pct'])
                if parse_stats.get('parse_cpu_to_elapsed_pct') and 'parse_cpu_to_elapsed_pct' not in scored_metrics:
                    scored_metrics['parse_cpu_to_elapsed_pct'] = self._safe_float(parse_stats['parse_cpu_to_elapsed_pct'])
                if parse_stats.get('hard_parse_pct') and 'hard_parse_pct' not in scored_metrics:
                    scored_metrics['hard_parse_pct'] = self._safe_float(parse_stats['hard_parse_pct'])
                if parse_stats.get('hard_parses_per_sec') and 'hard_parses_per_sec' not in scored_metrics:
                    scored_metrics['hard_parses_per_sec'] = self._safe_float(parse_stats['hard_parses_per_sec'])
                if parse_stats.get('total_parses_per_sec') and 'total_parses_per_sec' not in scored_metrics:
                    scored_metrics['total_parses_per_sec'] = self._safe_float(parse_stats['total_parses_per_sec'])
        except Exception:
            pass

        # -----------------------------------------------------------------
        # 12. undo / temp space (from advisories or dedicated sections)
        # -----------------------------------------------------------------
        try:
            undo_stats = parsed_data.get('undo_stats', {})
            if undo_stats and isinstance(undo_stats, dict):
                used_pct = self._safe_float(undo_stats.get('used_pct', 0))
                if used_pct > 0:
                    scored_metrics['undo_space_used_pct'] = used_pct
            temp_stats = parsed_data.get('temp_stats', {})
            if temp_stats and isinstance(temp_stats, dict):
                used_pct = self._safe_float(temp_stats.get('used_pct', 0))
                if used_pct > 0:
                    scored_metrics['temp_space_used_pct'] = used_pct
        except Exception:
            pass

        # =================================================================
        # Build problem list from scored metrics
        # =================================================================
        for metric_key, value in scored_metrics.items():
            try:
                result = self.score_metric(metric_key, value)
                if result['level'] != 'healthy':
                    _, _, unit, _ = self.thresholds.get(metric_key, (None, None, '', ''))
                    severity_map = {'warning': 'medium', 'serious': 'high'}
                    problem = {
                        'problem_type': self._get_problem_type(metric_key),
                        'title': self._get_problem_title(metric_key, value, unit),
                        'severity': severity_map.get(result['level'], 'medium'),
                        'health_level': result['level'],
                        'metric_name': metric_key,
                        'metric_value': value,
                        'metric_unit': unit,
                        'threshold_warning': result['warning_threshold'],
                        'threshold_serious': result['serious_threshold'],
                        'evidence': result['evidence'],
                    }
                    problems.append(problem)
            except Exception:
                pass

        return problems


# ---------------------------------------------------------------------------
# CORRELATION ANALYZER
# ---------------------------------------------------------------------------

class CorrelationAnalyzer:
    """Correlate metrics across dimensions to identify root causes."""

    # Correlation rules: each rule defines a chain of evidence
    CORRELATION_RULES = [
        {'name': 'io_sql', 'trigger': ['db_file_sequential_read', 'db_file_scattered_read'],
         'check': 'top_sql_gets_reads'},
        {'name': 'cpu_sql', 'trigger': ['cpu', 'db_time_ratio'],
         'check': 'top_sql_cpu'},
        {'name': 'redo_commit', 'trigger': ['log_file_sync'],
         'check': 'redo_transactions'},
        {'name': 'parse', 'trigger': ['library_cache', 'latch'],
         'check': 'hard_parse_pct'},
        {'name': 'rac', 'trigger': ['gc'],
         'check': 'rac_stats'},
        {'name': 'memory', 'trigger': ['buffer_cache_hit'],
         'check': 'physical_reads_sga'},
    ]

    def analyze(self, parsed_data: dict, problems: list) -> list:
        """Analyze correlations between identified problems and metrics.
        Returns list of correlation findings."""
        if not parsed_data or not problems:
            return []
        findings = []
        findings.extend(self._check_io_sql_correlation(parsed_data, problems))
        findings.extend(self._check_cpu_sql_correlation(parsed_data, problems))
        findings.extend(self._check_redo_commit_correlation(parsed_data, problems))
        findings.extend(self._check_parse_correlation(parsed_data, problems))
        findings.extend(self._check_rac_correlation(parsed_data, problems))
        findings.extend(self._check_memory_correlation(parsed_data, problems))
        findings.extend(self._check_temp_pga_correlation(parsed_data, problems))
        findings.extend(self._check_lock_sql_correlation(parsed_data, problems))
        findings.extend(self._check_os_db_correlation(parsed_data, problems))
        findings.extend(self._check_segment_sql_correlation(parsed_data, problems))
        return findings

    def _check_io_sql_correlation(self, parsed_data: dict, problems: list) -> list:
        """db file sequential/scattered read high -> check Top SQL buffer gets/reads."""
        findings = []
        io_problems = [p for p in problems if p.get('metric_name', '') and
                       ('db_file_sequential_read' in p.get('metric_name', '') or
                        'db_file_scattered_read' in p.get('metric_name', ''))]
        if not io_problems:
            return findings
        top_sql = parsed_data.get('top_sql', {}) or {}
        sql_by_gets = top_sql.get('SQL ordered by Gets', []) or []
        sql_by_reads = top_sql.get('SQL ordered by Reads', []) or []
        for io_problem in io_problems:
            evidence = []
            pct = io_problem.get('metric_value', 0)
            event_name = io_problem.get('event_name', io_problem.get('metric_name', ''))
            evidence.append(f"{event_name} \u5360 DB Time {pct}%")
            for sql in sql_by_gets[:3]:
                sql_id = sql.get('sql_id', sql.get('SQL Id', 'unknown'))
                gets = sql.get('buffer_gets_per_exec', sql.get('Buffer Gets per Exec', 0))
                if gets:
                    evidence.append(f"SQL_ID={sql_id} Buffer Gets/Exec={gets}")
            for sql in sql_by_reads[:3]:
                sql_id = sql.get('sql_id', sql.get('SQL Id', 'unknown'))
                reads = sql.get('disk_reads_per_exec', sql.get('Physical Reads per Exec', 0))
                if reads:
                    evidence.append(f"SQL_ID={sql_id} Disk Reads/Exec={reads}")
            if len(evidence) > 1:
                findings.append({
                    'title': 'I/O\u7b49\u5f85\u4e0e\u9ad8\u903b\u8f91\u8bfbSQL\u5173\u8054',
                    'trigger_problem': io_problem.get('title', event_name),
                    'related_evidence': evidence,
                    'root_cause': '\u5b58\u5728\u9ad8\u903b\u8f91\u8bfbSQL\u5bfc\u81f4\u5927\u91cf\u5355\u5757\u8bfbI/O\u7b49\u5f85',
                    'suggestion': '\u4f18\u5148\u4f18\u5316Top SQL\u6267\u884c\u8ba1\u5212\u548c\u7d22\u5f15\u9009\u62e9\u6027'
                })
        return findings

    def _check_cpu_sql_correlation(self, parsed_data: dict, problems: list) -> list:
        """CPU high -> check SQL CPU time and buffer gets."""
        findings = []
        cpu_problems = [p for p in problems if p.get('metric_name', '') and
                        ('cpu' in p.get('metric_name', '').lower() or
                         'db_time_ratio' in p.get('metric_name', ''))]
        if not cpu_problems:
            return findings
        top_sql = parsed_data.get('top_sql', {}) or {}
        sql_by_cpu = top_sql.get('SQL ordered by CPU Time', []) or []
        for cpu_problem in cpu_problems:
            evidence = []
            evidence.append(f"{cpu_problem.get('title', 'CPU\u95ee\u9898')}")
            for sql in sql_by_cpu[:3]:
                sql_id = sql.get('sql_id', sql.get('SQL Id', 'unknown'))
                cpu_time = sql.get('cpu_time_s', sql.get('CPU Time (s)', 0))
                if cpu_time:
                    evidence.append(f"SQL_ID={sql_id} CPU Time={cpu_time}s")
            if len(evidence) > 1:
                findings.append({
                    'title': 'CPU\u74f6\u9888\u4e0e\u9ad8CPU\u6d88\u8017SQL\u5173\u8054',
                    'trigger_problem': cpu_problem.get('title', 'CPU\u4f7f\u7528\u7387\u9ad8'),
                    'related_evidence': evidence,
                    'root_cause': '\u5b58\u5728\u9ad8CPU\u6d88\u8017\u7684SQL\u8bed\u53e5\u5bfc\u81f4CPU\u8d44\u6e90\u7d27\u5f20',
                    'suggestion': '\u4f18\u5316Top CPU SQL\u7684\u6267\u884c\u8ba1\u5212\uff0c\u51cf\u5c11\u903b\u8f91\u8bfb\u548c\u8ba1\u7b97\u91cf'
                })
        return findings

    def _check_redo_commit_correlation(self, parsed_data: dict, problems: list) -> list:
        """log file sync high -> check redo size, commit frequency, log file parallel write."""
        findings = []
        log_problems = [p for p in problems if p.get('metric_name', '') and
                        'log_file_sync' in p.get('metric_name', '')]
        if not log_problems:
            return findings
        load_profile = parsed_data.get('load_profile', {})
        if isinstance(load_profile, dict):
            computed = load_profile.get('computed', {})
        else:
            computed = {}
        redo_size = computed.get('redo_size', 0)
        transactions_per_sec = computed.get('transactions', 0)
        for log_problem in log_problems:
            evidence = []
            evidence.append(f"log file sync \u5e73\u5747\u7b49\u5f85 {log_problem.get('metric_value', 0)}ms")
            if redo_size > 0:
                evidence.append(f"Redo Size/Sec = {redo_size:.0f} bytes")
            if transactions_per_sec > 0:
                evidence.append(f"Transactions/Sec = {transactions_per_sec:.1f}")
            if redo_size > 50_000_000:
                evidence.append('Redo\u751f\u6210\u91cf\u8fc7\u5927')
            if transactions_per_sec > 100:
                evidence.append('\u63d0\u4ea4\u9891\u7387\u8fc7\u9ad8')
            findings.append({
                'title': 'Redo\u65e5\u5fd7\u540c\u6b65\u4e0e\u63d0\u4ea4\u9891\u7387\u5173\u8054',
                'trigger_problem': log_problem.get('title', 'log file sync\u7b49\u5f85'),
                'related_evidence': evidence,
                'root_cause': '\u9891\u7e41\u63d0\u4ea4\u6216\u5927\u91cfredo\u751f\u6210\u5bfc\u81f4\u65e5\u5fd7\u540c\u6b65\u7b49\u5f85',
                'suggestion': '\u51cf\u5c11\u4e0d\u5fc5\u8981\u7684\u9891\u7e41COMMIT\uff0c\u5408\u5e76\u5c0f\u4e8b\u52a1\uff0c\u68c0\u67e5redo\u65e5\u5fd7I/O\u6027\u80fd'
            })
        return findings

    def _check_parse_correlation(self, parsed_data: dict, problems: list) -> list:
        """library cache / latch high -> check hard parse ratio."""
        findings = []
        parse_problems = [p for p in problems if p.get('metric_name', '') and
                          ('library_cache' in p.get('metric_name', '') or
                           'latch' in p.get('metric_name', '').lower())]
        if not parse_problems:
            return findings
        parse_stats = parsed_data.get('parse_stats', {}) or {}
        hard_parse_pct = parse_stats.get('hard_parse_pct', 0)
        for problem in parse_problems:
            evidence = []
            evidence.append(f"{problem.get('title', 'Library Cache\u95ee\u9898')}")
            if hard_parse_pct:
                evidence.append(f"\u786c\u89e3\u6790\u6bd4\u4f8b = {hard_parse_pct}%")
            if hard_parse_pct and float(hard_parse_pct) > 10:
                evidence.append('\u786c\u89e3\u6790\u6bd4\u4f8b\u8fc7\u9ad8\uff0c\u6d88\u8017\u5927\u91cfshared pool\u8d44\u6e90')
            findings.append({
                'title': 'Library Cache\u4e89\u7528\u4e0e\u786c\u89e3\u6790\u5173\u8054',
                'trigger_problem': problem.get('title', 'Library Cache\u95ee\u9898'),
                'related_evidence': evidence,
                'root_cause': '\u5927\u91cf\u786c\u89e3\u6790\u5bfc\u81f4Library Cache\u548cLatch\u4e89\u7528',
                'suggestion': '\u63a8\u52a8\u5e94\u7528\u4f7f\u7528\u7ed1\u5b9a\u53d8\u91cf\uff0c\u51cf\u5c11\u786c\u89e3\u6790\u6b21\u6570'
            })
        return findings

    def _check_rac_correlation(self, parsed_data: dict, problems: list) -> list:
        """gc wait high -> check RAC interconnect and hot SQL."""
        findings = []
        gc_problems = [p for p in problems if p.get('metric_name', '') and
                       'gc' in p.get('metric_name', '').lower()]
        if not gc_problems:
            return findings
        rac_stats = parsed_data.get('rac_stats', []) or []
        for problem in gc_problems:
            evidence = []
            evidence.append(f"{problem.get('title', 'GC\u7b49\u5f85\u95ee\u9898')}")
            for stat in rac_stats[:3]:
                name = stat.get('name', stat.get('Statistic', ''))
                value = stat.get('value', stat.get('Total', ''))
                if name and value:
                    evidence.append(f"{name} = {value}")
            findings.append({
                'title': 'RAC\u8282\u70b9\u95f4GC\u7b49\u5f85\u5173\u8054',
                'trigger_problem': problem.get('title', 'GC\u7b49\u5f85'),
                'related_evidence': evidence,
                'root_cause': 'RAC\u8282\u70b9\u95f4\u6570\u636e\u5757\u4f20\u8f93\u5ef6\u8fdf\u5bfc\u81f4GC\u7b49\u5f85',
                'suggestion': '\u68c0\u67e5RAC\u4e92\u8054\u7f51\u7edc\u6027\u80fd\uff0c\u8bc6\u522b\u70ed\u70b9\u5bf9\u8c61\u5e76\u505a\u5b9e\u4f8b\u9694\u79bb'
            })
        return findings

    def _check_memory_correlation(self, parsed_data: dict, problems: list) -> list:
        """Buffer cache hit low -> check physical reads and SGA sizing."""
        findings = []
        mem_problems = [p for p in problems if p.get('metric_name', '') and
                        'buffer_cache_hit' in p.get('metric_name', '')]
        if not mem_problems:
            return findings
        memory_stats = parsed_data.get('memory_stats', {}) or {}
        io_stats = parsed_data.get('io_stats', []) or []
        for problem in mem_problems:
            evidence = []
            evidence.append(f"Buffer Cache\u547d\u4e2d\u7387 = {problem.get('metric_value', 0)}%")
            if memory_stats:
                sga_size = memory_stats.get('sga_size', memory_stats.get('SGA Size', ''))
                if sga_size:
                    evidence.append(f"SGA Size = {sga_size}")
                buffer_cache = memory_stats.get('buffer_cache_size', memory_stats.get('Buffer Cache Size', ''))
                if buffer_cache:
                    evidence.append(f"Buffer Cache Size = {buffer_cache}")
            for io in io_stats[:2]:
                name = io.get('name', io.get('Tablespace', ''))
                reads = io.get('physical_reads', io.get('Physical Reads', ''))
                if name and reads:
                    evidence.append(f"{name} Physical Reads = {reads}")
            findings.append({
                'title': 'Buffer Cache\u4e0d\u8db3\u4e0e\u7269\u7406\u8bfb\u5173\u8054',
                'trigger_problem': problem.get('title', 'Buffer Cache\u547d\u4e2d\u7387\u4f4e'),
                'related_evidence': evidence,
                'root_cause': 'Buffer Cache\u8fc7\u5c0f\u6216\u5b58\u5728\u5927\u91cf\u5168\u8868\u626b\u63cf\u5bfc\u81f4\u7269\u7406\u8bfb\u589e\u591a',
                'suggestion': '\u8003\u8651\u589e\u5927db_cache_size\uff0c\u68c0\u67e5\u5168\u8868\u626b\u63cfSQL\u5e76\u4f18\u5316'
            })
        return findings

    def _check_temp_pga_correlation(self, parsed_data: dict, problems: list) -> list:
        """direct path read/write temp high -> check PGA and sort spills."""
        findings = []
        temp_problems = [p for p in problems if p.get('metric_name', '') and
                         ('temp_space' in p.get('metric_name', '') or
                          'in_memory_sort' in p.get('metric_name', '') or
                          'pga_over_allocation' in p.get('metric_name', ''))]
        if not temp_problems:
            top_events = parsed_data.get('top_events', []) or []
            for evt in top_events:
                ename = (evt.get('event', '') or '').lower()
                pct = float(evt.get('pct_db_time', 0) or 0)
                if 'direct path' in ename and 'temp' in ename and pct > 5:
                    temp_problems.append({
                        'metric_name': 'direct_path_temp',
                        'title': f'{evt.get("event", "")} 占 DB Time {pct}%',
                        'metric_value': pct
                    })
        if not temp_problems:
            return findings
        load_profile = parsed_data.get('load_profile', {})
        computed = load_profile.get('computed', {}) if isinstance(load_profile, dict) else {}
        for problem in temp_problems:
            evidence = [f"{problem.get('title', '临时表空间/PGA问题')}"]
            if computed.get('physical_reads'):
                evidence.append(f"Physical Reads/Sec = {computed['physical_reads']}")
            evidence.append('排序/Hash操作溢出到临时表空间，PGA可能不足')
            findings.append({
                'title': '临时表空间压力与PGA不足关联',
                'trigger_problem': problem.get('title', '临时表空间/PGA问题'),
                'related_evidence': evidence,
                'root_cause': 'PGA不足导致排序/Hash Join溢出到磁盘临时表空间',
                'suggestion': '增大PGA_AGGREGATE_TARGET，优化大排序SQL减少排序集'
            })
        return findings

    def _check_lock_sql_correlation(self, parsed_data: dict, problems: list) -> list:
        """TX row lock / TM contention -> check SQL and segment stats."""
        findings = []
        lock_problems = [p for p in problems if p.get('metric_name', '') and
                         ('enq_tx_row_lock' in p.get('metric_name', '') or
                          'tx' in p.get('metric_name', '').lower())]
        if not lock_problems:
            top_events = parsed_data.get('top_events', []) or []
            for evt in top_events:
                ename = (evt.get('event', '') or '').lower()
                pct = float(evt.get('pct_db_time', 0) or 0)
                if ('enq: tx' in ename or 'enq: tm' in ename) and pct > 5:
                    lock_problems.append({
                        'metric_name': 'lock_event',
                        'title': f'{evt.get("event", "")} 占 DB Time {pct}%',
                        'metric_value': pct
                    })
        if not lock_problems:
            return findings
        segment_stats = parsed_data.get('segment_stats', []) or []
        top_sql = parsed_data.get('top_sql', {}) or {}
        sql_by_elapsed = top_sql.get('SQL ordered by Elapsed Time', []) or []
        for problem in lock_problems:
            evidence = [f"{problem.get('title', '锁等待问题')}"]
            for seg in segment_stats[:3]:
                seg_name = seg.get('Segment Name', seg.get('name', ''))
                if seg_name:
                    evidence.append(f"热点段: {seg_name}")
            for sql in sql_by_elapsed[:2]:
                sql_id = sql.get('sql_id', sql.get('SQL Id', ''))
                if sql_id:
                    evidence.append(f"Top SQL_ID: {sql_id}")
            findings.append({
                'title': '锁争用与热点段/SQL关联',
                'trigger_problem': problem.get('title', '锁等待'),
                'related_evidence': evidence,
                'root_cause': '热点段上的并发DML导致行锁或表锁争用',
                'suggestion': '优化事务粒度和持有时间，检查外键是否缺少索引'
            })
        return findings

    def _check_os_db_correlation(self, parsed_data: dict, problems: list) -> list:
        """OS CPU/memory high -> correlate with DB load."""
        findings = []
        os_problems = [p for p in problems if p.get('metric_name', '') and
                       p.get('metric_name', '').startswith('os_')]
        if not os_problems:
            return findings
        load_profile = parsed_data.get('load_profile', {})
        computed = load_profile.get('computed', {}) if isinstance(load_profile, dict) else {}
        for problem in os_problems:
            evidence = [f"{problem.get('title', 'OS资源问题')}"]
            if computed.get('db_time'):
                evidence.append(f"DB Time/Sec = {computed['db_time']}")
            if computed.get('db_cpu'):
                evidence.append(f"DB CPU/Sec = {computed['db_cpu']}")
            findings.append({
                'title': 'OS资源压力与数据库负载关联',
                'trigger_problem': problem.get('title', 'OS资源问题'),
                'related_evidence': evidence,
                'root_cause': '数据库高负载消耗OS资源，或外部进程与数据库竞争资源',
                'suggestion': '优化数据库Top SQL降低资源消耗，检查非数据库进程占用'
            })
        return findings

    def _check_segment_sql_correlation(self, parsed_data: dict, problems: list) -> list:
        """Hot segment -> correlate with Top SQL accessing that segment."""
        findings = []
        seg_problems = [p for p in problems if p.get('problem_type', '') == 'segment' or
                        ('segment' in p.get('metric_name', '').lower())]
        if not seg_problems:
            return findings
        top_sql = parsed_data.get('top_sql', {}) or {}
        sql_by_gets = top_sql.get('SQL ordered by Gets', []) or []
        for problem in seg_problems:
            evidence = [f"{problem.get('title', '热点段问题')}"]
            for sql in sql_by_gets[:3]:
                sql_id = sql.get('sql_id', sql.get('SQL Id', ''))
                gets = sql.get('buffer_gets_per_exec', sql.get('Buffer Gets per Exec', ''))
                if sql_id:
                    evidence.append(f"SQL_ID={sql_id} Gets/Exec={gets}")
            if len(evidence) > 1:
                findings.append({
                    'title': '热点段与高逻辑读SQL关联',
                    'trigger_problem': problem.get('title', '热点段'),
                    'related_evidence': evidence,
                    'root_cause': '高频SQL访问热点段导致段级争用和缓存压力',
                    'suggestion': '优化SQL减少对热点段的访问频率和范围'
                })
        return findings


# ---------------------------------------------------------------------------
# BASELINE COMPARER
# ---------------------------------------------------------------------------

class BaselineComparer:
    """Compare current metrics against historical baselines."""

    def compare(self, report, parsed_data: dict, db_session) -> list:
        """Compare current metrics to baseline. Returns list of deviation findings."""
        from app.models import AWRBaseline
        deviations = []
        if not parsed_data or not report:
            return deviations
        metrics = self._extract_key_metrics(parsed_data)
        for metric_name, current_value in metrics.items():
            if current_value is None:
                continue
            baseline = db_session.query(AWRBaseline).filter(
                AWRBaseline.db_name == report.db_name,
                AWRBaseline.instance_name == report.instance_name,
                AWRBaseline.metric_name == metric_name
            ).first()
            if not baseline or baseline.sample_count < 3:
                continue
            dev = self._calculate_deviation(current_value, baseline.avg_value, baseline.max_value)
            if dev['is_anomaly']:
                deviations.append({
                    'metric_name': metric_name,
                    'current_value': current_value,
                    'baseline_avg': baseline.avg_value,
                    'baseline_max': baseline.max_value,
                    'deviation_pct': dev['deviation_pct'],
                    'is_anomaly': dev['is_anomaly'],
                    'evidence': f"{metric_name} \u5f53\u524d {current_value}, \u5386\u53f2\u5e73\u5747 {baseline.avg_value}, \u589e\u957f {dev['deviation_pct']}%"
                })
        return deviations

    def update_baseline(self, report, parsed_data: dict, db_session):
        """Update running baseline statistics after analysis."""
        from app.models import AWRBaseline
        if not parsed_data or not report:
            return
        metrics = self._extract_key_metrics(parsed_data)
        for metric_name, current_value in metrics.items():
            if current_value is None:
                continue
            baseline = db_session.query(AWRBaseline).filter(
                AWRBaseline.db_name == report.db_name,
                AWRBaseline.instance_name == report.instance_name,
                AWRBaseline.metric_name == metric_name,
                AWRBaseline.metric_type == 'auto'
            ).first()
            if baseline:
                old_avg = baseline.avg_value or 0
                old_count = baseline.sample_count or 0
                new_avg = (old_avg * old_count + current_value) / (old_count + 1)
                baseline.avg_value = round(new_avg, 4)
                baseline.min_value = min(baseline.min_value or current_value, current_value)
                baseline.max_value = max(baseline.max_value or current_value, current_value)
                baseline.sample_count = old_count + 1
            else:
                baseline = AWRBaseline(
                    db_name=report.db_name,
                    instance_name=report.instance_name,
                    metric_name=metric_name,
                    metric_type='auto',
                    avg_value=current_value,
                    min_value=current_value,
                    max_value=current_value,
                    sample_count=1
                )
                db_session.add(baseline)
        db_session.flush()

    def _calculate_deviation(self, current: float, avg: float, max_val: float) -> dict:
        """Calculate how much current deviates from baseline."""
        if not avg or avg == 0:
            return {'deviation_pct': 0, 'is_anomaly': False}
        deviation_pct = (current - avg) / avg * 100
        is_anomaly = deviation_pct > 50 or (max_val and current > max_val * 1.2)
        return {'deviation_pct': round(deviation_pct, 1), 'is_anomaly': bool(is_anomaly)}

    def _extract_key_metrics(self, parsed_data: dict) -> dict:
        """Extract ALL scoreable metrics from parsed data for baseline comparison.
        Reuses MetricScorer.score_all() extraction logic to stay in sync."""
        metrics = {}
        try:
            # Use MetricScorer to extract all metrics, then harvest the scored_metrics
            scorer = MetricScorer()
            # We need the scored_metrics dict, not the problems list.
            # Replicate the extraction by calling score_all and capturing via a wrapper.
            # Instead, directly compute the same metrics:
            load_profile = parsed_data.get('load_profile', {})
            computed = load_profile.get('computed', {}) if isinstance(load_profile, dict) else {}

            def _sf(v):
                try:
                    return float(v) if v else 0
                except (ValueError, TypeError):
                    return 0

            # Load profile derived
            db_time = _sf(computed.get('db_time'))
            db_cpu = _sf(computed.get('db_cpu'))
            if db_cpu > 0:
                metrics['db_time_ratio'] = round(db_time / db_cpu, 4)
            hard_parses = _sf(computed.get('hard_parses'))
            parses = _sf(computed.get('parses'))
            if parses > 0:
                metrics['hard_parse_pct'] = round(hard_parses / parses * 100, 2)
                metrics['hard_parses_per_sec'] = round(hard_parses, 2)
                metrics['total_parses_per_sec'] = round(parses, 2)
            if computed.get('redo_size'):
                metrics['redo_size_per_sec'] = _sf(computed['redo_size'])
            if computed.get('transactions'):
                metrics['transactions_per_sec'] = _sf(computed['transactions'])
            if computed.get('logical_reads'):
                metrics['logical_reads_per_sec'] = _sf(computed['logical_reads'])
            if computed.get('physical_reads'):
                metrics['physical_reads_per_sec'] = _sf(computed['physical_reads'])
            if computed.get('executes'):
                metrics['sql_executions_per_sec'] = _sf(computed['executes'])

            # Top events (pct + avg_wait)
            top_events = parsed_data.get('top_events', []) or []
            for event in top_events[:10]:
                pct = _sf(event.get('pct_db_time', 0))
                avg_wait = _sf(event.get('avg_wait', 0))
                ename = event.get('event', event.get('name', ''))
                if ename and pct:
                    safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', ename.lower()).strip('_')
                    metrics[f'{safe_name}_pct_db_time'] = pct
                    if avg_wait:
                        metrics[f'{safe_name}_avg_wait'] = avg_wait

            # Instance efficiency
            instance_eff = parsed_data.get('instance_efficiency', {})
            eff_map = {
                'buffer': 'buffer_cache_hit_ratio', 'library': 'library_cache_hit_ratio',
                'soft parse': 'soft_parse_pct', 'execute to parse': 'execute_to_parse_pct',
                'latch hit': 'latch_hit_pct', 'memory sort': 'in_memory_sort_pct',
                'in-memory sort': 'in_memory_sort_pct',
                'parse cpu': 'parse_cpu_to_elapsed_pct',
            }
            if isinstance(instance_eff, dict):
                for name, val in instance_eff.items():
                    fval = _sf(val)
                    if fval > 0:
                        for keyword, metric_key in eff_map.items():
                            if keyword in name.lower():
                                metrics[metric_key] = fval
                                break
            elif isinstance(instance_eff, list):
                for item in instance_eff:
                    name = (item.get('name', item.get('metric', '')) or '').lower()
                    fval = _sf(item.get('value', item.get('pct', 0)))
                    if fval > 0:
                        for keyword, metric_key in eff_map.items():
                            if keyword in name:
                                metrics[metric_key] = fval
                                break

            # Parse stats supplementary
            parse_stats = parsed_data.get('parse_stats', {}) or {}
            if isinstance(parse_stats, dict):
                for key in ('execute_to_parse_pct', 'parse_cpu_to_elapsed_pct'):
                    if parse_stats.get(key) and key not in metrics:
                        metrics[key] = _sf(parse_stats[key])

        except Exception:
            pass
        return metrics


# ---------------------------------------------------------------------------
# LLM INTEGRATION
# ---------------------------------------------------------------------------

class LLMIntegration:
    """Interface for LLM-enhanced analysis with structured output."""

    def __init__(self, provider='none', api_key='', api_url='', model=''):
        self.provider = provider
        self.api_key = api_key
        self.api_url = api_url
        self.model = model

    def enhance_analysis(self, parsed_data: dict, problems: list, correlations: list,
                         anti_patterns=None, wait_class_summary=None,
                         param_recommendations=None) -> dict:
        """Send structured data to LLM for deep analysis.
        Returns dict with: summary, problems, learned_patterns, raw_response"""
        if self.provider == 'none' or not self.api_key:
            return None
        try:
            prompt = self._build_prompt(parsed_data, problems, correlations,
                                        anti_patterns=anti_patterns,
                                        wait_class_summary=wait_class_summary,
                                        param_recommendations=param_recommendations)
            response_text = self._call_api(prompt)
            result = self._parse_llm_response(response_text)
            result['raw_response'] = response_text
            return result
        except Exception as e:
            return {'error': str(e), 'summary': '', 'problems': [], 'learned_patterns': []}

    def _build_prompt(self, parsed_data: dict, problems: list, correlations: list,
                      anti_patterns=None, wait_class_summary=None,
                      param_recommendations=None) -> str:
        """Build structured prompt for LLM with comprehensive AWR context."""
        db_info = parsed_data.get('db_info', {}) or {}
        snap_info = parsed_data.get('snap_info', {}) or {}
        load_profile = parsed_data.get('load_profile', {})
        computed = load_profile.get('computed', {}) if isinstance(load_profile, dict) else {}

        p = []  # prompt lines
        p.append("你是一个Oracle DBA专家，请分析以下AWR报告数据并给出诊断建议。")
        p.append("")

        # === Section 1: DB Info ===
        p.append(f"数据库信息: DB Name={db_info.get('db_name', 'N/A')}, "
                 f"Instance={db_info.get('instance_name', 'N/A')}, "
                 f"Version={db_info.get('db_version', 'N/A')}, "
                 f"Host={db_info.get('host_name', 'N/A')}")
        p.append(f"快照: Begin={snap_info.get('begin_id', 'N/A')}, "
                 f"End={snap_info.get('end_id', 'N/A')}, "
                 f"Elapsed={snap_info.get('elapsed_seconds', 'N/A')}s")
        p.append("")

        # === Section 2: Load Profile ===
        p.append("关键负载指标(Per Second):")
        for k, v in computed.items():
            p.append(f"  {k}: {v}")
        p.append("")

        # === Section 3: Top Wait Events ===
        top_events = parsed_data.get('top_events', []) or []
        if top_events:
            p.append("Top等待事件:")
            for i, evt in enumerate(top_events[:10], 1):
                ename = evt.get('event', evt.get('name', 'N/A'))
                pct = evt.get('pct_db_time', 0)
                avg = evt.get('avg_wait', 0)
                wclass = evt.get('wait_class', '')
                p.append(f"  {i}. {ename} | %DB Time={pct} | Avg Wait={avg}ms | Class={wclass}")
            p.append("")

        # === Section 4: Wait Class Summary ===
        if wait_class_summary:
            p.append("Wait Class汇总:")
            for wclass, total_pct in sorted(wait_class_summary.items(), key=lambda x: -x[1]):
                if total_pct > 0.1:
                    p.append(f"  {wclass}: {total_pct:.1f}% DB Time")
            p.append("")

        # === Section 5: Top SQL ===
        top_sql = parsed_data.get('top_sql', {})
        if isinstance(top_sql, dict):
            for section_name in ['SQL ordered by Elapsed Time', 'SQL ordered by CPU Time',
                                 'SQL ordered by Gets']:
                sql_list = top_sql.get(section_name, [])
                if sql_list:
                    p.append(f"{section_name} (Top 5):")
                    for i, sql in enumerate(sql_list[:5], 1):
                        sql_id = sql.get('sql_id', sql.get('SQL Id', 'N/A'))
                        elapsed = sql.get('Elapsed Time (s)', sql.get('elapsed_time', ''))
                        cpu = sql.get('CPU Time (s)', sql.get('cpu_time', ''))
                        gets = sql.get('Buffer Gets', sql.get('buffer_gets', ''))
                        execs = sql.get('Executions', sql.get('executions', ''))
                        text = (sql.get('sql_text', sql.get('SQL Text', '')) or '')[:80]
                        p.append(f"  {i}. SQL_ID={sql_id} Elapsed={elapsed}s CPU={cpu}s "
                                 f"Gets={gets} Execs={execs}")
                        if text:
                            p.append(f"     SQL: {text}...")
                    p.append("")

        # === Section 6: Instance Efficiency ===
        instance_eff = parsed_data.get('instance_efficiency', {})
        if instance_eff:
            p.append("实例效率:")
            if isinstance(instance_eff, dict):
                for name, val in instance_eff.items():
                    p.append(f"  {name}: {val}%")
            elif isinstance(instance_eff, list):
                for item in instance_eff:
                    p.append(f"  {item.get('name', item.get('metric', ''))}: {item.get('value', '')}%")
            p.append("")

        # === Section 7: Time Model ===
        time_model = parsed_data.get('time_model', {})
        if time_model:
            p.append("Time Model (DB Time分解):")
            for key, tm in time_model.items():
                if isinstance(tm, dict) and tm.get('time_seconds', 0) > 0:
                    p.append(f"  {tm.get('name', key)}: {tm['time_seconds']}s "
                             f"({tm.get('pct_db_time', 0)}% DB Time)")
            p.append("")

        # === Section 8: Identified Problems ===
        p.append(f"发现的问题({len(problems)}个):")
        for i, prob in enumerate(problems[:15], 1):
            level = prob.get('health_level', prob.get('severity', 'warning'))
            title = prob.get('title', 'N/A')
            evidence = prob.get('evidence', '')
            p.append(f"  {i}. [{level}] {title}")
            if evidence:
                p.append(f"     证据: {evidence[:120]}")
        p.append("")

        # === Section 9: Correlation Analysis ===
        if correlations:
            p.append(f"关联分析({len(correlations)}条):")
            for i, c in enumerate(correlations[:8], 1):
                p.append(f"  {i}. {c.get('title', 'N/A')}: {c.get('root_cause', '')}")
            p.append("")

        # === Section 10: SQL Anti-Patterns ===
        if anti_patterns:
            p.append(f"SQL反模式({len(anti_patterns)}个):")
            for i, ap in enumerate(anti_patterns[:5], 1):
                p.append(f"  {i}. [{ap.get('severity', '')}] {ap.get('anti_pattern', '')}: "
                         f"{ap.get('description', '')}")
            p.append("")

        # === Section 11: Parameter Recommendations ===
        if param_recommendations:
            p.append(f"建议调整的参数({len(param_recommendations)}个):")
            for rec in param_recommendations[:5]:
                p.append(f"  {rec['parameter']}: {rec['recommendation']}")
            p.append("")

        # === Output Format ===
        p.append("请以下面的JSON格式输出分析结果，不要包含任何markdown标记:")
        p.append('{"summary": "总体分析摘要", '
                 '"problems": [{"title": "", "severity": "", "root_cause": "", "evidence": [], "suggestion": []}], '
                 '"learned_patterns": [{"pattern_name": "", "conditions": [{"metric": "", "op": "", "value": 0}], "solution": ""}], '
                 '"parameter_suggestions": [{"parameter": "", "current_issue": "", "recommended_value": "", "reason": ""}]}')
        p.append("")
        p.append("注意: 只输出合法的JSON，不要用```包裹。")
        return "\n".join(p)

    def _parse_llm_response(self, response_text: str) -> dict:
        """Parse LLM response, trying to extract JSON."""
        if not response_text:
            return {'summary': '', 'problems': [], 'learned_patterns': []}
        # Try direct JSON parse
        try:
            return json.loads(response_text)
        except (json.JSONDecodeError, TypeError):
            pass
        # Try to find JSON between ``` markers
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except (json.JSONDecodeError, TypeError):
                pass
        # Try to find JSON between first { and last }
        first_brace = response_text.find('{')
        last_brace = response_text.rfind('}')
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            try:
                return json.loads(response_text[first_brace:last_brace + 1])
            except (json.JSONDecodeError, TypeError):
                pass
        return {'summary': response_text, 'problems': [], 'learned_patterns': []}

    def _call_api(self, prompt: str) -> str:
        """Call LLM API (supports openai, deepseek, custom)."""
        import requests
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}'
        }
        if self.provider == 'openai':
            url = self.api_url or 'https://api.openai.com/v1/chat/completions'
            model = self.model or 'gpt-4o'
        elif self.provider == 'deepseek':
            url = self.api_url or 'https://api.deepseek.com/v1/chat/completions'
            model = self.model or 'deepseek-chat'
        elif self.provider == 'custom':
            url = self.api_url
            model = self.model or 'default'
        else:
            raise ValueError(f"Unsupported LLM provider: {self.provider}")
        payload = {
            'model': model,
            'temperature': 0.3,
            'messages': [{'role': 'user', 'content': prompt}]
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        return data['choices'][0]['message']['content']


# ---------------------------------------------------------------------------
# LEARNING ENGINE
# ---------------------------------------------------------------------------

class LearningEngine:
    """Self-learning engine for knowledge rule lifecycle management."""

    INITIAL_CONFIDENCE = 0.35
    HIT_BOOST = 0.05
    MISS_DECAY = -0.03
    MISS_STREAK_THRESHOLD = 3
    STALE_DAYS = 90
    STALE_DECAY = -0.10
    ACTIVE_THRESHOLD = 0.65
    REJECT_THRESHOLD = 0.20

    def process_analysis(self, report, problems: list, correlations: list,
                         llm_patterns: list, db_session):
        """Process analysis results: update existing rules, create new candidates."""
        from app.models import KnowledgeRule
        matched_rules, unmatched = self._match_rules(problems, db_session)
        matched_ids = {r.id for r in matched_rules}
        all_non_builtin_rules = db_session.query(KnowledgeRule).filter(
            KnowledgeRule.source != 'builtin').all()
        self._update_hit_rules(matched_rules, report, db_session)
        self._update_miss_rules(all_non_builtin_rules, matched_ids, db_session)
        self._create_candidates(unmatched, llm_patterns or [], db_session)
        db_session.flush()

    def _match_rules(self, problems: list, db_session) -> tuple:
        """Match problems against existing knowledge rules.
        Returns (matched_rules, unmatched_problems)."""
        from app.models import KnowledgeRule
        all_rules = db_session.query(KnowledgeRule).filter(
            KnowledgeRule.status != 'rejected').all()
        # Build metrics context from problems
        metrics_context = {}
        for p in problems:
            metric_name = p.get('metric_name', '')
            metric_value = p.get('metric_value', 0)
            if metric_name:
                metrics_context[metric_name] = metric_value
            event_name = p.get('event_name', '')
            if event_name:
                metrics_context['_event_' + metric_name] = event_name
            # Also store pct_db_time if available
            pct = p.get('pct_db_time', p.get('metric_value', 0))
            if event_name:
                metrics_context['pct_db_time'] = pct
                metrics_context['_current_event'] = event_name
        matched_rules = []
        matched_problem_keys = set()
        for rule in all_rules:
            conds = rule.conditions_json if rule.conditions_json else '[]'
            if self.evaluate_conditions(conds, metrics_context):
                matched_rules.append(rule)
                # Mark related problems as matched
                try:
                    conditions = json.loads(conds) if isinstance(conds, str) else conds
                    for cond in conditions:
                        matched_problem_keys.add(cond.get('metric', ''))
                except Exception:
                    pass
        unmatched = [p for p in problems if p.get('metric_name', '') not in matched_problem_keys]
        return (matched_rules, unmatched)

    def _update_hit_rules(self, matched_rules: list, report, db_session):
        """Boost confidence for matched rules."""
        from app.models import KnowledgeHitLog
        for rule in matched_rules:
            rule.hit_count = (rule.hit_count or 0) + 1
            rule.miss_streak = 0
            rule.confidence = min(1.0, (rule.confidence or 0) + self.HIT_BOOST)
            rule.last_hit_at = datetime.utcnow()
            hit_log = KnowledgeHitLog(rule_id=rule.id, report_id=report.id)
            db_session.add(hit_log)
            self._update_status(rule, db_session)

    def _update_miss_rules(self, all_rules, matched_rule_ids: set, db_session):
        """Increment miss streak for unmatched rules, decay if needed."""
        for rule in all_rules:
            if rule.id in matched_rule_ids:
                continue
            if rule.source == 'builtin':
                continue
            rule.miss_streak = (rule.miss_streak or 0) + 1
            if rule.miss_streak >= self.MISS_STREAK_THRESHOLD:
                rule.confidence = (rule.confidence or 0) + self.MISS_DECAY
            if rule.last_hit_at and (datetime.utcnow() - rule.last_hit_at).days > self.STALE_DAYS:
                rule.confidence = (rule.confidence or 0) + self.STALE_DECAY
            self._update_status(rule, db_session)

    def _create_candidates(self, unmatched_problems: list, llm_patterns: list, db_session):
        """Create new candidate rules from unmatched problems and LLM suggestions."""
        from app.models import KnowledgeRule
        # From unmatched problems
        for problem in unmatched_problems:
            name = problem.get('title', '')
            if not name:
                continue
            existing = db_session.query(KnowledgeRule).filter(
                KnowledgeRule.name == name).first()
            if existing:
                continue
            metric_name = problem.get('metric_name', '')
            threshold = problem.get('threshold_warning', problem.get('metric_value', 0))
            conditions = [{"metric": metric_name, "op": ">", "value": threshold}]
            rule = KnowledgeRule(
                name=name,
                category=problem.get('problem_type', 'unknown'),
                conditions_json=json.dumps(conditions),
                root_cause=problem.get('evidence', ''),
                solution='\u9700\u8981\u8fdb\u4e00\u6b65\u5206\u6790',
                confidence=self.INITIAL_CONFIDENCE,
                status='candidate',
                source='learned',
                is_active=False
            )
            db_session.add(rule)
        # From LLM patterns
        for pattern in llm_patterns:
            name = pattern.get('pattern_name', '')
            if not name:
                continue
            existing = db_session.query(KnowledgeRule).filter(
                KnowledgeRule.name == name).first()
            if existing:
                continue
            conditions = pattern.get('conditions', [])
            rule = KnowledgeRule(
                name=name,
                category='llm_learned',
                conditions_json=json.dumps(conditions),
                root_cause=pattern.get('solution', ''),
                solution=pattern.get('solution', ''),
                confidence=self.INITIAL_CONFIDENCE + 0.05,
                status='candidate',
                source='llm',
                is_active=False
            )
            db_session.add(rule)

    def _update_status(self, rule, db_session):
        """Update rule status based on confidence thresholds."""
        if rule.source == 'builtin':
            rule.status = 'active'
            rule.is_active = True
            return
        confidence = rule.confidence or 0
        if confidence >= self.ACTIVE_THRESHOLD:
            rule.status = 'active'
            rule.is_active = True
        elif confidence >= 0.50:
            rule.status = 'observed'
            rule.is_active = True
        elif confidence < self.REJECT_THRESHOLD:
            rule.status = 'rejected'
            rule.is_active = False
        elif confidence < 0.35:
            rule.status = 'stale'
            rule.is_active = False
        else:
            rule.status = 'candidate'
            rule.is_active = False

    def evaluate_conditions(self, conditions_json: str, metrics_context: dict) -> bool:
        """Evaluate structured conditions against current metrics."""
        try:
            if not conditions_json or not metrics_context:
                return False
            if isinstance(conditions_json, str):
                conditions = json.loads(conditions_json)
            else:
                conditions = conditions_json
            if not conditions:
                return False
            for condition in conditions:
                metric = condition.get('metric', '')
                op = condition.get('op', '>')
                value = condition.get('value', 0)
                event = condition.get('event', '')
                # Check if metric exists in context
                if metric not in metrics_context:
                    return False
                current = metrics_context[metric]
                # If event specified, check event name matches
                if event:
                    ctx_event = metrics_context.get('_event_' + metric, '')
                    current_event = metrics_context.get('_current_event', '')
                    if event.lower() not in ctx_event.lower() and event.lower() not in current_event.lower():
                        return False
                # Apply operator
                try:
                    current = float(current)
                    value = float(value)
                except (ValueError, TypeError):
                    return False
                if op == '>':
                    if not (current > value):
                        return False
                elif op == '<':
                    if not (current < value):
                        return False
                elif op == '>=':
                    if not (current >= value):
                        return False
                elif op == '<=':
                    if not (current <= value):
                        return False
                elif op == '==':
                    if not (current == value):
                        return False
                else:
                    return False
            return True
        except Exception:
            return False
