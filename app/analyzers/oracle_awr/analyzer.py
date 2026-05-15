from app.analyzers.oracle_awr.metrics import extract_awr_metrics, safe_float
from app.analyzers.oracle_awr.parser import parse_awr
from app.analyzers.oracle_awr.event_semantics import SEMANTIC_DISPLAY_NAMES
from app.core.analyzer_base import AnalyzerBase
from app.core.models import (
    AnalysisContext,
    CauseFlow,
    DiagnosisResult,
    EvidenceItem,
    Finding,
    ProblemDomain,
    Recommendation,
)


SEVERITY_RANK = {"NORMAL": 0, "OBSERVE": 1, "WARNING": 2, "HIGH": 3}
CAUSE_GRAPH = {
    "access_path": ["temp", "redo", "hot_block"],
    "temp": ["redo"],
    "storage": ["redo", "hot_block"],
    "redo": ["hot_block"],
    "sql_cpu": ["temp", "redo", "hot_block"],
    "parse_cpu": ["redo"],
    "rac_gc": ["hot_block"],
    "hot_block": [],
}


class OracleAwrAnalyzer(AnalyzerBase):
    analyzer_type = "oracle_awr"
    display_name = "Oracle AWR 报告分析"
    description = "上传 Oracle AWR HTML 报告，分析数据库性能瓶颈、异常指标、原因和优化建议。"

    def parse(self, input_data):
        return parse_awr(input_data)

    def extract_metrics(self, parsed_data):
        return extract_awr_metrics(parsed_data)

    def diagnose(self, metrics):
        if not metrics.get("parse_success", True):
            return self.build_parse_failed_result(metrics)

        context = self.build_analysis_context(metrics)
        domains = self.build_problem_domains(metrics, context)
        self.deduplicate_commit_redo(domains, metrics)
        context.problem_domains = self.assign_domain_roles(domains)
        main_domains = [domain for domain in context.problem_domains if domain.role == "main"]
        active_domains = [domain for domain in context.problem_domains if domain.severity != "NORMAL"]

        main_bottleneck = self.describe_main_bottleneck(context)
        severity = self.detect_result_severity(context.problem_domains)
        summary = self.build_summary(context)

        result = DiagnosisResult(
            analyzer_type=self.analyzer_type,
            title="Oracle AWR 智能诊断结果",
            severity=severity,
            main_bottleneck=main_bottleneck,
            summary=summary,
            raw_metrics=metrics,
        )
        result.conclusions = self.build_conclusions(context, main_domains, active_domains, metrics)
        result.abnormal_findings = self.build_findings(context)
        result.root_causes = self.build_root_causes(metrics, context)
        result.root_cause_flows = self.build_cause_flows(context)
        result.evidence = self.build_evidence(metrics, context)
        result.recommendations = self.build_recommendations(metrics, context)
        return result

    def build_parse_failed_result(self, metrics):
        message = metrics.get("parse_error") or "未解析出有效 AWR 诊断内容。"
        return DiagnosisResult(
            analyzer_type=self.analyzer_type,
            title="Oracle AWR 智能诊断结果",
            severity="WARNING",
            main_bottleneck="无法解析有效 AWR 内容",
            summary=message,
            conclusions=[
                "当前上传文件没有解析出 AWR 关键诊断段，不能据此判断数据库是否存在性能瓶颈。",
                "请确认上传的是 Oracle AWR HTML 原始报告，且文件内容未损坏。",
            ],
            abnormal_findings=[
                Finding(
                    name="AWR 报告解析失败",
                    severity="WARNING",
                    description=message,
                    reason="未读取到 Top Events、Wait Classes、Time Model 或 Top SQL 等关键 AWR 表格。",
                )
            ],
            root_causes=[
                "上传文件可能不是有效 HTML AWR 报告。",
                "文件可能是同步盘占位文件、加密缓存文件、损坏文件，或不是原始 AWR HTML 内容。",
            ],
            evidence={
                "解析状态": [
                    EvidenceItem("Top Events", "未解析到"),
                    EvidenceItem("Wait Classes", "未解析到"),
                    EvidenceItem("Time Model Statistics", "未解析到"),
                    EvidenceItem("Top SQL", "未解析到"),
                ]
            },
            recommendations=[
                Recommendation("P1", "重新选择原始 Oracle AWR HTML 报告上传", "当前文件没有有效 AWR 表格，继续分析会得到误导性的 0 值。"),
            ],
            raw_metrics=metrics,
        )

    def build_analysis_context(self, metrics):
        return AnalysisContext(
            elapsed_minutes=metrics.get("elapsed_minutes", 0) or 0,
            db_time_minutes=metrics.get("db_time_minutes", 0) or 0,
            aas=metrics.get("aas", 0) or 0,
            workload_type=metrics.get("workload_type", "Mixed"),
            waiting_vs_cpu_model=metrics.get("waiting_vs_cpu_model", "mixed"),
            time_breakdown=[
                EvidenceItem("DB CPU", metrics.get("db_cpu_pct_db_time", 0), "占 DB Time 百分比"),
                EvidenceItem("User I/O", metrics.get("user_io_pct_db_time", 0), "占 DB Time 百分比"),
                EvidenceItem("Commit", metrics.get("commit_pct_db_time", 0), "占 DB Time 百分比"),
                EvidenceItem("Configuration", metrics.get("configuration_pct_db_time", 0), "占 DB Time 百分比"),
                EvidenceItem("Concurrency", metrics.get("concurrency_pct_db_time", 0), "占 DB Time 百分比"),
                EvidenceItem("Application", metrics.get("application_pct_db_time", 0), "占 DB Time 百分比"),
                EvidenceItem("Network", metrics.get("network_pct_db_time", 0), "占 DB Time 百分比"),
                EvidenceItem("Parse", metrics.get("parse_time_pct_db_time", 0), "占 DB Time 百分比"),
            ],
            top_events=metrics.get("top_events") or [],
            top_sql_elapsed=metrics.get("top_sql_elapsed") or [],
            top_sql_cpu=metrics.get("top_sql_cpu") or [],
            top_sql_gets=metrics.get("top_sql_gets") or [],
            top_sql_reads=metrics.get("top_sql_reads") or [],
        )

    def build_problem_domains(self, metrics, context):
        domains = [
            self.make_domain(
                "CPU",
                metrics.get("db_cpu_pct_db_time", 0),
                {"observe": 30, "warning": 40, "critical": 70},
                "DB CPU 占 DB Time 较高，说明 SQL 执行计算、逻辑读或执行计划效率需要关注。",
                "检查 Top SQL 的 CPU Time、Buffer Gets、Executions 和执行计划。",
            ),
            self.make_domain(
                "User I/O",
                metrics.get("user_io_pct_db_time", 0),
                {"observe": 5, "warning": 15, "critical": 30},
                "User I/O 等待占比较高，说明物理读或访问路径可能影响响应时间。",
                "检查 SQL ordered by Reads、Physical Reads 和相关对象访问路径。",
            ),
            self.make_domain(
                "Commit",
                metrics.get("commit_pct_db_time", 0),
                {"observe": 5, "warning": 10, "critical": 20},
                "Commit 等待占比较高，可能与 log file sync、频繁提交或 redo 写入延迟有关。",
                "检查 log file sync、log file parallel write、redo 写入和应用提交频率。",
            ),
            self.make_domain(
                "Configuration",
                metrics.get("configuration_pct_db_time", 0),
                {"observe": 1, "warning": 3, "critical": 10},
                "Configuration 等待偏高，常见原因包括 redo/checkpoint、日志切换或参数配置问题。",
                "检查 redo log 大小、切换频率、checkpoint 和 DBWR 写出能力。",
            ),
            self.make_domain(
                "Concurrency",
                metrics.get("concurrency_pct_db_time", 0),
                {"observe": 2, "warning": 10, "critical": 20},
                "Concurrency 等待偏高，可能存在锁、闩锁或共享资源争用。",
                "检查 enq、latch、buffer busy、read by other session 等等待事件。",
            ),
            self.make_domain(
                "Application",
                metrics.get("application_pct_db_time", 0),
                {"observe": 2, "warning": 10, "critical": 20},
                "Application 等待偏高，可能存在应用锁、行锁或业务侧等待。",
                "检查 enq: TX、行锁、应用事务边界和热点对象。",
            ),
            self.make_domain(
                "Network",
                metrics.get("network_pct_db_time", 0),
                {"observe": 2, "warning": 10, "critical": 20},
                "Network 等待偏高，可能存在客户端取数、网络传输或 SQL 返回大量数据问题。",
                "检查 SQL 返回行数、客户端 fetch 行为和网络延迟。",
            ),
            self.make_domain(
                "Parse",
                metrics.get("parse_time_pct_db_time", 0),
                {"observe": 5, "warning": 10, "critical": 20},
                "Parse 时间占比较高，可能存在硬解析、绑定变量不足或游标共享问题。",
                "检查 Parse Calls、Hard Parses、绑定变量和 cursor sharing。",
            ),
            self.make_domain(
                "Memory",
                100 if metrics.get("memory_pressure") else 0,
                {"observe": 1, "warning": 50, "critical": 100},
                "Memory Statistics 中出现内存压力信号。",
                "检查 PGA/SGA、排序/Hash 工作区和内存 Advisory。",
            ),
        ]
        domains.extend(self.build_semantic_domains(metrics))
        return domains

    def build_semantic_domains(self, metrics):
        semantics = metrics.get("event_semantics", {})
        configs = {
            "redo_pipeline": (
                {"observe": 1, "warning": 3, "critical": 10},
                "Redo/LGWR 写入链路存在等待，需要关注日志写入、日志切换、checkpoint 或 log buffer。",
                "检查 log file sync、log file parallel write、log buffer space、redo log 大小、LGWR 和存储写延迟。",
            ),
            "temp_pressure": (
                {"observe": 1, "warning": 3, "critical": 10},
                "存在 TEMP/PGA 压力，SQL 可能发生大量排序、Hash Join 或 PGA 溢写。",
                "检查消耗 TEMP 的 SQL、PGA 配置、排序/Hash 工作区、并行查询和执行计划。",
            ),
            "oltp_random_read": (
                {"observe": 2, "warning": 8, "critical": 20},
                "存在较明显 OLTP 随机读，通常与索引访问、单块读或高频点查有关。",
                "检查高频 SQL 的索引选择性、执行次数、Buffer Gets 和单块读。",
            ),
            "full_scan": (
                {"observe": 2, "warning": 8, "critical": 20},
                "存在全表扫描或直接路径读迹象，可能来自报表、大查询、批处理或并行查询。",
                "检查 SQL ordered by Reads、direct path read、db file scattered read 和大表访问路径。",
            ),
            "hot_block": (
                {"observe": 1, "warning": 5, "critical": 15},
                "存在热点块或读竞争迹象，可能出现 buffer busy/read by other session 等等待。",
                "检查热点对象、索引块争用、并发访问模式和相关 SQL。",
            ),
            "hot_object": (
                {"observe": 1, "warning": 5, "critical": 15},
                "存在热点对象、锁或闩锁竞争迹象。",
                "检查 enq/latch/cursor 等等待、阻塞会话、热点对象和事务边界。",
            ),
            "lock_contention": (
                {"observe": 1, "warning": 5, "critical": 15},
                "存在锁争用迹象，可能是事务锁、DDL 锁、游标锁或热点更新。",
                "检查 enq: TX、row lock contention、library cache lock、cursor pin 等等待和阻塞链路。",
            ),
            "parse_pressure": (
                {"observe": 1, "warning": 5, "critical": 15},
                "存在 Parse/Library Cache 压力迹象，可能与硬解析、绑定变量或游标共享有关。",
                "检查 hard parse、library cache、cursor mutex、绑定变量和共享池状态。",
            ),
            "network_wait": (
                {"observe": 2, "warning": 8, "critical": 20},
                "存在网络等待迹象，可能与客户端取数慢、网络延迟或返回数据量大有关。",
                "检查 SQL 返回行数、客户端 fetch 行为、网络延迟和应用处理速度。",
            ),
            "storage_io": (
                {"observe": 5, "warning": 15, "critical": 30},
                "存在存储 I/O 链路等待，需要结合读写吞吐、IOPS 和平均等待判断。",
                "检查 Read/Write IO MB/s、等待事件平均延迟、存储队列和 SQL 访问路径。",
            ),
            "rac_global_cache": (
                {"observe": 3, "warning": 8, "critical": 20},
                "RAC Global Cache 等待偏高，可能存在跨实例缓存争用、热点块跨节点传输或互联网络瓶颈。",
                "检查 gc 等待事件、互联网络延迟、热点对象跨节点访问和 SQL 执行计划。",
            ),
        }

        domains = []
        for name, (thresholds, reason, recommendation) in configs.items():
            group = semantics.get(name, {})
            value = group.get("pct_db_time", 0) or 0
            domain = self.make_domain(
                name,
                value,
                thresholds,
                reason,
                recommendation,
            )
            domain.evidence = [
                EvidenceItem(
                    SEMANTIC_DISPLAY_NAMES.get(name, name),
                    value,
                    "由 Top Events 语义分类汇总",
                )
            ]
            domains.append(domain)
        return domains

    def make_domain(self, name, value, thresholds, reason, recommendation):
        value = value or 0
        severity = self.classify_severity(value, thresholds)
        score = SEVERITY_RANK[severity] * 100 + value
        return ProblemDomain(
            name=name,
            value=value,
            severity=severity,
            role="normal",
            score=score,
            evidence=[EvidenceItem(name, value, "占 DB Time 百分比" if name != "Memory" else "内存压力信号")],
            reason=reason,
            recommendation=recommendation,
        )

    def classify_severity(self, value, thresholds):
        if value >= thresholds["critical"]:
            return "HIGH"
        if value >= thresholds["warning"]:
            return "WARNING"
        if value >= thresholds["observe"]:
            return "OBSERVE"
        return "NORMAL"

    def assign_domain_roles(self, domains):
        sorted_domains = sorted(domains, key=lambda domain: domain.score, reverse=True)
        first_active_assigned = False
        for domain in sorted_domains:
            if domain.severity == "NORMAL":
                domain.role = "normal"
            elif not first_active_assigned:
                domain.role = "main"
                first_active_assigned = True
            elif domain.severity in ("HIGH", "WARNING"):
                domain.role = "secondary"
            else:
                domain.role = "observe"
        return sorted_domains

    def should_activate_access_path(self, domain_map):
        full_scan = domain_map.get("full_scan")
        oltp_random = domain_map.get("oltp_random_read")
        fs_active = full_scan and full_scan.severity in ("WARNING", "HIGH")
        oltp_active = oltp_random and (safe_float(oltp_random.value) >= 5 or oltp_random.severity == "HIGH")
        return fs_active or oltp_active

    def deduplicate_commit_redo(self, domains, metrics):
        domain_map = {d.name: d for d in domains}
        redo = domain_map.get("redo_pipeline")
        commit = domain_map.get("Commit")
        if redo and commit and redo.severity != "NORMAL" and commit.severity != "NORMAL":
            log_sync_pct = safe_float(metrics.get("log_file_sync_pct_db_time", 0))
            commit_pct = safe_float(commit.value)
            if commit_pct > 0 and log_sync_pct / commit_pct > 0.8:
                commit.severity = "OBSERVE"
                commit.score = SEVERITY_RANK["OBSERVE"] * 100 + commit.value

    def detect_result_severity(self, domains):
        severities = [domain.severity for domain in domains]
        if "HIGH" in severities:
            return "HIGH"
        if "WARNING" in severities:
            return "WARNING"
        if "OBSERVE" in severities:
            return "INFO"
        return "INFO"

    def describe_main_bottleneck(self, context):
        if all(domain.severity == "NORMAL" for domain in context.problem_domains):
            return "未发现明显单一瓶颈"

        chains = self.build_root_cause_chains(context)
        if chains:
            if chains[0]["key"] in ("sql_cpu", "parse_cpu"):
                return "CPU"
            if chains[0]["key"] == "rac_gc":
                return "RAC Global Cache"
            return chains[0]["name"]

        main = next(domain for domain in context.problem_domains if domain.role == "main")
        secondary_names = [domain.name for domain in context.problem_domains if domain.role == "secondary"]

        if main.name == "CPU" and ("Configuration" in secondary_names or "redo_pipeline" in secondary_names) and self.has_event(context, "log file switch"):
            return "CPU 偏高，伴随 Redo/Checkpoint 配置异常"
        if main.name in ("Configuration", "redo_pipeline") and self.has_event(context, "log file switch"):
            return "Redo/Checkpoint 配置异常"
        if main.name == "temp_pressure":
            return "TEMP/PGA 压力"
        if main.severity == "OBSERVE":
            return f"{main.name} 偏高，需要关注"
        if secondary_names:
            return f"{main.name} 为主问题，伴随 {', '.join(secondary_names)}"
        return main.name

    def build_summary(self, context):
        if all(domain.severity == "NORMAL" for domain in context.problem_domains):
            return "当前 AWR 报告未发现明显单一主瓶颈，需要结合业务时间段和 SQL 明细继续分析。"

        chains = self.build_root_cause_chains(context)
        if chains:
            main = chains[0]
            secondary = chains[1:4]
            parts = [f"当前最主要的问题是 {main['name']}。"]
            if secondary:
                parts.append("伴随问题包括：" + "、".join(chain["name"] for chain in secondary) + "。")
            parts.append(f"{main['summary']}。")
            first_action = self.first_chain_action(main)
            if first_action:
                parts.append(f"第一优先排查方向是 {first_action}。")
            return "\n".join(parts)

        main = next(domain for domain in context.problem_domains if domain.role == "main")
        parts = [f"当前最主要的问题是 {self.display_domain_name(main)}。"]
        parts.append(f"{self.summary_metric_name(main)} 是最大的时间消耗来源，需要优先通过 Top SQL 解释其来源。")
        top_sql_ids = self.top_sql_ids(context)
        if top_sql_ids:
            parts.append("第一优先排查方向是 Top SQL。")
        return "\n".join(parts)

    def build_conclusions(self, context, main_domains, active_domains, metrics=None):
        if not active_domains:
            return [
                "当前报告未发现明显单一主瓶颈。",
                f"DB Time {context.db_time_minutes} 分钟，Elapsed {context.elapsed_minutes} 分钟，AAS 约 {context.aas}。",
                "建议结合 Top Events、Top SQL、Load Profile 和业务时间段进一步判断。",
            ]

        chains = self.build_root_cause_chains(context)

        if chains:
            main_chain = chains[0]
            conclusions = [
                f"当前最主要的问题是 {main_chain['name']}。",
                f"AWR 时间段内 DB Time 为 {context.db_time_minutes} 分钟，Elapsed 为 {context.elapsed_minutes} 分钟，平均活跃会话约 {context.aas}。",
                f"负载类型判断为 {context.workload_type}，数据库时间模型为 {self.waiting_model_text(context.waiting_vs_cpu_model)}。",
            ]
            # Phase 4C: add data-driven detail
            if metrics:
                detail = self.chain_data_detail(main_chain, metrics)
                if detail:
                    conclusions.append(detail)
            if len(chains) > 1:
                conclusions.append("伴随问题：" + "、".join(chain["name"] for chain in chains[1:4]) + "。")
            conclusions.append(main_chain["reason"])
            top_sql_ids = self.top_sql_ids(context)
            if top_sql_ids:
                conclusions.append("排查入口：存在多个高耗时 Top SQL，需要作为第一批排查对象：" + "、".join(top_sql_ids[:3]) + "。")
            return conclusions

        main = main_domains[0]
        conclusions = [
            f"当前最主要的问题是 {self.display_domain_name(main)}。",
            f"AWR 时间段内 DB Time 为 {context.db_time_minutes} 分钟，Elapsed 为 {context.elapsed_minutes} 分钟，平均活跃会话约 {context.aas}。",
            f"负载类型判断为 {context.workload_type}，数据库时间模型为 {self.waiting_model_text(context.waiting_vs_cpu_model)}。",
        ]
        secondary = self.visible_domains([domain for domain in active_domains if domain.role == "secondary"])
        observe = self.visible_domains([domain for domain in active_domains if domain.role == "observe"])
        normal = [domain for domain in context.problem_domains if domain.role == "normal" and domain.name in ("Commit", "Network", "Application")]
        if secondary:
            conclusions.append("伴随问题：" + "、".join(self.display_domain_name(domain) for domain in secondary) + "。")
        if observe:
            conclusions.append("需要关注：" + "、".join(self.display_domain_name(domain) for domain in observe) + "。")
        top_sql_ids = self.top_sql_ids(context)
        if top_sql_ids:
            conclusions.append("排查入口：存在多个高耗时 Top SQL，需要作为第一批排查对象：" + "、".join(top_sql_ids[:3]) + "。")
        if normal:
            conclusions.append("非主因：" + "、".join(domain.name for domain in normal[:3]) + " 当前占比不高。")
        return conclusions

    def chain_data_detail(self, chain, metrics):
        key = chain["key"]
        if key == "redo":
            log_sync_pct = self.format_number(metrics.get("log_file_sync_pct_db_time", 0))
            log_sync_avg = self.format_number(metrics.get("log_file_sync_avg_ms", 0))
            detail = f"log file sync 占 {log_sync_pct}% DB Time，平均等待 {log_sync_avg}ms"
            if safe_float(metrics.get("log_file_sync_avg_ms", 0)) > 5:
                detail += "（建议 < 5ms，当前明显偏高）"
            detail += f"。提交频率 {self.format_number(metrics.get('commits_per_sec', 0))}/s。"
            return detail
        if key == "sql_cpu":
            db_cpu = self.format_number(metrics.get("db_cpu_pct_db_time", 0))
            cpu_count = metrics.get("cpu_count", 0)
            host_idle = self.format_number(metrics.get("host_cpu_idle_pct", 0))
            detail = f"DB CPU 占 {db_cpu}% DB Time"
            if cpu_count:
                detail += f"，主机 {int(cpu_count)} CPU"
            if host_idle:
                detail += f"，Host CPU Idle {host_idle}%"
            detail += "。"
            return detail
        if key in ("access_path", "storage"):
            phys_reads = self.format_number(metrics.get("physical_read_blocks_per_sec", 0))
            read_io = self.format_number(metrics.get("read_io_mb_per_sec", 0))
            return f"Physical Reads {phys_reads} blocks/s，Read IO {read_io} MB/s。"
        if key == "temp":
            return "TEMP/PGA 压力导致排序或 Hash Join 溢写到磁盘。"
        if key == "hot_block":
            return "并发热点或锁等待正在放大响应时间。"
        if key == "parse_cpu":
            parse_pct = self.format_number(metrics.get("parse_time_pct_db_time", 0))
            hard_parses = self.format_number(metrics.get("hard_parses_per_sec", 0))
            return f"Parse 占 {parse_pct}% DB Time，Hard Parses {hard_parses}/s。"
        if key == "rac_gc":
            gc_pct = self.format_number(metrics.get("event_semantics", {}).get("rac_global_cache", {}).get("pct_db_time", 0))
            return f"RAC Global Cache 等待占 {gc_pct}% DB Time，需要检查跨实例热点和互联网络。"
        return ""

    def build_findings(self, context):
        findings = []
        chains = self.build_root_cause_chains(context)
        if chains:
            for index, chain in enumerate(chains[:5]):
                finding_name = chain["name"] if index else f"{chain['name']}是当前主问题"
                findings.append(
                    Finding(
                        name=finding_name,
                        severity=chain["severity"],
                        value=chain["value"],
                        description=chain["reason"],
                        reason=chain["recommendation"],
                    )
                )
            self.append_sql_finding(context, findings)
            return findings

        visible_names = {domain.name for domain in self.visible_domains(context.problem_domains)}
        for domain in context.problem_domains:
            if domain.severity == "NORMAL":
                continue
            if domain.name not in visible_names:
                continue
            findings.append(
                Finding(
                    name=self.domain_finding_name(domain),
                    severity=domain.severity,
                    value=self.format_domain_value(domain),
                    description=self.build_domain_reason(domain),
                    reason=domain.recommendation,
                )
            )

        checkpoint = self.find_event(context, "log file switch (checkpoint incomplete)")
        if checkpoint:
            findings.append(
                Finding(
                    name="log file switch (checkpoint incomplete) 明显异常",
                    severity="WARNING",
                    value=f"{checkpoint.get('pct_db_time')}% DB Time",
                    description=f"等待 {checkpoint.get('time_s')} 秒，平均等待 {checkpoint.get('avg_wait_ms')}ms。",
                    reason="通常说明 redo log 切换过快、redo 日志组偏小、checkpoint 跟不上，或 DBWR/存储写入能力不足。",
                )
            )

        self.append_sql_finding(context, findings)
        return findings

    def build_root_causes(self, metrics, context):
        flows = self.build_cause_flows(context)
        if flows:
            causes = []
            for flow in flows[:2]:
                path = " → ".join([flow.root] + flow.amplifiers + flow.symptoms)
                causes.append(f"{flow.title}：{path}。{flow.explanation}")
            return causes

        chains = self.build_root_cause_chains(context)
        if chains:
            causes = [chain["reason"] for chain in chains[:5]]
            if context.waiting_vs_cpu_model == "waiting_dominant":
                causes.append("当前数据库主要时间消耗在等待而不是计算，应该优先分析等待事件背后的链路含义。")
            if metrics.get("commit_pct_db_time", 0) < 5 and not any(chain["key"] == "redo" for chain in chains[:2]):
                causes.append("Commit 当前占比不高，不应把提交慢作为第一优先方向。")
            return causes

        causes = []
        domain_names = {domain.name: domain for domain in context.problem_domains if domain.severity != "NORMAL"}
        cpu_active = "CPU" in domain_names
        io_active = "User I/O" in domain_names
        commit_active = "Commit" in domain_names
        config_active = "Configuration" in domain_names
        parse_active = "Parse" in domain_names

        if cpu_active and self.logical_reads_high(metrics):
            causes.append("CPU 消耗可能由高逻辑读 SQL 引起：DB CPU 占比较高，同时 Logical read blocks/s 很高。")
        elif cpu_active:
            causes.append("CPU 消耗需要优先结合 Top SQL CPU Time、Buffer Gets、Executions 和执行计划继续确认。")

        if io_active and self.physical_reads_high(metrics):
            causes.append("I/O 等待可能由大量物理读或访问路径不合理引起，需要检查 SQL ordered by Reads 和相关对象。")
        elif self.physical_reads_high(metrics):
            causes.append("物理读吞吐较高，虽然 User I/O 未必是主因，但需要关注大查询、报表或批处理 SQL。")

        if config_active and self.has_event(context, "log file switch"):
            causes.append("存在 redo log 切换或 checkpoint 写出跟不上的问题，通常与 redo log 偏小、切换频繁、DBWR 或存储写能力不足有关。")

        if self.semantic_active(context, "redo_pipeline"):
            causes.append("Redo/LGWR 写入链路存在等待，需要检查 log buffer、LGWR 写延迟、redo log 切换和 checkpoint。")

        if self.semantic_active(context, "temp_pressure"):
            causes.append("存在明显 TEMP/PGA 压力，SQL 可能发生大量排序、Hash Join 或 PGA 溢写。")

        if self.semantic_active(context, "hot_block"):
            causes.append("存在热点块或读竞争迹象，需要结合 read by other session、buffer busy waits 和热点对象继续分析。")

        if self.semantic_active(context, "hot_object"):
            causes.append("存在热点对象、锁或闩锁竞争迹象，需要检查 enq/latch/cursor 等等待事件。")

        if context.waiting_vs_cpu_model == "waiting_dominant":
            causes.append("当前数据库主要时间消耗在等待而不是计算，需要优先分析等待事件语义和对应链路。")

        if self.semantic_active(context, "lock_contention"):
            causes.append("锁争用信号明显，可能存在事务锁、DDL 锁、游标锁或热点更新。")

        if self.semantic_active(context, "parse_pressure"):
            causes.append("Parse/Library Cache 压力明显，可能由硬解析、绑定变量不足或游标共享问题引起。")

        if self.semantic_active(context, "network_wait"):
            causes.append("网络等待明显，可能是客户端取数慢、网络慢或 SQL 返回数据量过大。")

        if self.semantic_active(context, "storage_io"):
            causes.append("存储 I/O 链路存在等待，需要结合 Read/Write IO、平均等待和 SQL 访问路径判断。")

        if commit_active and self.has_event(context, "log file sync"):
            causes.append("事务提交等待可能由频繁提交或 redo 写入延迟引起，需要结合 log file sync 平均等待和提交频率判断。")
        elif metrics.get("commit_pct_db_time", 0) < 5:
            causes.append("Commit 本身不是主因：Commit 占 DB Time 不高，log file sync 不应作为第一优先级。")

        if parse_active and metrics.get("parse_time_pct_db_time", 0) >= 10:
            causes.append("解析压力可能由硬解析或绑定变量不足引起，需要检查 Hard Parses、Parse Calls 和 cursor sharing。")

        if not causes:
            causes.append("当前没有单一压倒性问题域，需要结合 Top Events、Top SQL 和业务时段交叉判断。")
        return causes

    def build_evidence(self, metrics, context):
        evidence = {
            "负载强度": [
                EvidenceItem("Elapsed", f"{context.elapsed_minutes} 分钟"),
                EvidenceItem("DB Time", f"{context.db_time_minutes} 分钟"),
                EvidenceItem("AAS", f"约 {context.aas}"),
                EvidenceItem("负载强度", metrics.get("load_intensity")),
                EvidenceItem("负载类型", context.workload_type),
                EvidenceItem("时间模型", self.waiting_model_text(context.waiting_vs_cpu_model)),
                EvidenceItem("CPU 饱和风险", "YES" if metrics.get("cpu_saturation_risk") else "NO"),
            ],
            "OS/主机信息": self.host_info_evidence(metrics),
            "DB Time 构成": [
                EvidenceItem(item.name, item.value, item.description)
                for item in self.core_time_breakdown(context)
            ],
            "Top Events": [
                EvidenceItem(
                    f"{item.get('event', 'unknown')}" + (f" [{item.get('wait_class', '')}]" if item.get("wait_class") else ""),
                    self.format_event_value(item),
                    "占 DB Time 百分比",
                )
                for item in context.top_events[:10]
            ],
            "Top SQL": [
                EvidenceItem(item.get("sql_id", "unknown"), item.get("elapsed_time"), "SQL ordered by Elapsed Time")
                for item in context.top_sql_elapsed[:5]
            ],
            "Load Profile": [
                EvidenceItem("Logical read", f"{metrics.get('logical_read_blocks_per_sec')} blocks/s"),
                EvidenceItem("Physical read", f"{metrics.get('physical_read_blocks_per_sec')} blocks/s"),
                EvidenceItem("Read IO", f"{metrics.get('read_io_mb_per_sec')} MB/s"),
                EvidenceItem("Write IO", f"{metrics.get('write_io_mb_per_sec')} MB/s"),
                EvidenceItem("Redo size", f"{self.format_number(metrics.get('redo_size_per_sec', 0))} bytes/s"),
                EvidenceItem("Commits", f"{self.format_number(metrics.get('commits_per_sec', 0))}/s"),
                EvidenceItem("Executes", f"{self.format_number(metrics.get('executes_per_sec', 0))}/s"),
                EvidenceItem("Hard Parses", f"{self.format_number(metrics.get('hard_parses_per_sec', 0))}/s"),
            ],
        }

        # SQL detail evidence
        sql_detail = self.sql_detail_evidence(context)
        if sql_detail:
            evidence["Top SQL 详情"] = sql_detail

        # Segment statistics
        segment_evidence = self.segment_evidence(metrics)
        if segment_evidence:
            evidence["热点对象 (Segment Statistics)"] = segment_evidence

        # Latch statistics
        latch_evidence = self.latch_evidence(metrics)
        if latch_evidence:
            evidence["闩锁统计 (Latch)"] = latch_evidence

        # Enqueue activity
        enqueue_evidence = self.enqueue_evidence(metrics)
        if enqueue_evidence:
            evidence["锁活动 (Enqueue)"] = enqueue_evidence

        # Existing detail sections
        evidence["诊断明细 - 问题域"] = [
            EvidenceItem(domain.name, self.format_domain_detail(domain), self.build_domain_reason(domain))
            for domain in context.problem_domains
        ]
        evidence["诊断明细 - 事件语义"] = self.semantic_evidence(metrics)
        evidence["诊断明细 - Top SQL 行为"] = self.sql_behavior_evidence(metrics)

        return evidence

    def build_recommendations(self, metrics, context):
        recommendations = []
        chains = self.build_root_cause_chains(context)

        if chains:
            recommendations.append(self.build_p1_recommendation(chains[0], metrics, context))
            priority = 2
            for chain in chains[1:4]:
                if chain["key"] == "sql_cpu":
                    continue
                recommendations.append(
                    Recommendation(
                        priority=f"P{priority}",
                        action=chain["recommendation"],
                        reason=chain["reason"],
                    )
                )
                priority += 1
        else:
            active = self.visible_domains([d for d in context.problem_domains if d.severity != "NORMAL"])
            recommendations.append(
                Recommendation(
                    priority="P1",
                    action="优先分析 Top SQL 的执行计划、CPU Time、Buffer Gets、Physical Reads 和 Executions",
                    reason="Top SQL 是解释 CPU、I/O 和 DB Time 消耗的第一批排查入口。",
                )
            )
            priority = 2
            for domain in active[:5]:
                if domain.name == "CPU":
                    continue
                recommendations.append(
                    Recommendation(
                        priority=f"P{priority}",
                        action=domain.recommendation,
                        reason=self.build_domain_reason(domain),
                    )
                )
                priority += 1

            has_redo_recommendation = any(domain.name in ("Configuration", "redo_pipeline") for domain in active)
            if self.has_event(context, "log file switch") and not has_redo_recommendation:
                recommendations.append(
                    Recommendation(
                        priority=f"P{priority}",
                        action="检查 redo log 大小、日志切换频率、checkpoint 参数、DBWR 和存储写能力",
                        reason="Top Events 中出现 log file switch/checkpoint incomplete，说明 redo/checkpoint 链路需要专项排查。",
                    )
                )
                priority += 1

        recommendations.append(
            Recommendation(
                priority="P9",
                action="优化后重新生成 AWR，对比主问题链路、Top Events、Top SQL、逻辑读和物理读是否下降",
                reason="AWR 前后对比可以验证优化是否真正降低了数据库工作量和等待链路压力。",
            )
        )
        return recommendations

    def build_p1_recommendation(self, chain, metrics, context):
        key = chain["key"]
        top_sql_ids = self.top_sql_ids(context)
        sql_hint = f"（重点排查：{'、'.join(top_sql_ids[:3])}）" if top_sql_ids else ""

        if key == "redo":
            log_sync_avg = self.format_number(metrics.get("log_file_sync_avg_ms", 0))
            log_sync_pct = self.format_number(metrics.get("log_file_sync_pct_db_time", 0))
            return Recommendation(
                priority="P1",
                action=f"优先分析 Redo/LGWR 写入链路：log file sync 平均等待 {log_sync_avg}ms，占 {log_sync_pct}% DB Time{sql_hint}",
                reason="Redo/LGWR 链路是当前主瓶颈，需要检查 redo log 大小、LGWR 写延迟、log buffer 和应用提交频率。",
            )
        if key == "sql_cpu":
            return Recommendation(
                priority="P1",
                action=f"优先分析 Top SQL 的 CPU Time、Buffer Gets 和执行计划{sql_hint}",
                reason="DB CPU 是最大时间消耗来源，需要通过 Top SQL 解释。",
            )
        if key in ("access_path", "storage"):
            phys_reads = self.format_number(metrics.get("physical_read_blocks_per_sec", 0))
            return Recommendation(
                priority="P1",
                action=f"优先分析 Top SQL 的 Physical Reads（当前 {phys_reads} blocks/s）和访问路径{sql_hint}",
                reason="I/O 等待是主要瓶颈，需要检查执行计划是否合理。",
            )
        if key == "temp":
            return Recommendation(
                priority="P1",
                action=f"优先分析消耗 TEMP/PGA 的 SQL、排序和 Hash Join{sql_hint}",
                reason="TEMP/PGA 压力正在放大 I/O 和 SQL 响应时间。",
            )
        if key == "hot_block":
            return Recommendation(
                priority="P1",
                action=f"优先定位热点对象和阻塞链路{sql_hint}",
                reason="并发热点或锁等待正在放大响应时间。",
            )
        if key == "parse_cpu":
            parse_pct = self.format_number(metrics.get("parse_time_pct_db_time", 0))
            hard_parses = self.format_number(metrics.get("hard_parses_per_sec", 0))
            return Recommendation(
                priority="P1",
                action=f"优先分析 SQL 解析消耗：Parse 占 {parse_pct}% DB Time，Hard Parses {hard_parses}/s{sql_hint}",
                reason="SQL 解析消耗过高，需要检查绑定变量、cursor_sharing 和共享池配置。",
            )
        if key == "rac_gc":
            return Recommendation(
                priority="P1",
                action=f"优先分析 RAC Global Cache 等待：检查 gc 等待事件、互联网络和热点跨实例对象{sql_hint}",
                reason="RAC Global Cache 等待偏高，可能存在跨实例热点或互联网络瓶颈。",
            )
        return Recommendation(
            priority="P1",
            action=f"优先分析 Top SQL{sql_hint}",
            reason=chain["reason"],
        )

    def build_root_cause_chains(self, context):
        domain_map = {domain.name: domain for domain in context.problem_domains}
        chains = []
        chain_configs = [
            {
                "key": "redo",
                "name": "Redo/LGWR 写入链路异常",
                "domains": ["redo_pipeline", "Configuration", "Commit"],
                "events": ["log buffer space", "log file sync", "log file parallel write", "log file switch", "checkpoint incomplete"],
                "reason": "Redo/LGWR 写入链路出现等待信号，可能存在 log buffer 压力、LGWR 写入慢、redo log 偏小、checkpoint 跟不上或频繁提交问题。",
                "recommendation": "检查 log buffer space、log file sync、log file parallel write、redo log 大小、日志切换频率、checkpoint 进度和 LGWR/存储写延迟。",
                "summary": "Redo/LGWR 或 checkpoint 链路是当前需要优先解释的等待来源",
            },
            {
                "key": "temp",
                "name": "TEMP/PGA 写入压力",
                "domains": ["temp_pressure", "Memory"],
                "events": ["direct path write temp", "direct path read temp"],
                "reason": "存在 TEMP/PGA 压力信号，SQL 可能发生大量排序、Hash Join、并行查询或 PGA 溢写。",
                "recommendation": "检查消耗 TEMP 的 SQL、PGA 配置、workarea 执行情况、排序/Hash Join、并行度和执行计划。",
                "summary": "TEMP/PGA 溢写可能正在放大 I/O 等待和 SQL 响应时间",
            },
            {
                "key": "access_path",
                "name": "大查询/批处理访问路径问题",
                "domains": ["full_scan", "oltp_random_read"],
                "events": ["direct path read", "db file scattered read"],
                "reason": "AWR 中出现大范围读、直接路径读或随机读信号，问题可能来自报表、大查询、批处理 SQL、索引选择不佳或访问路径不合理。",
                "recommendation": "检查 SQL ordered by Reads、Elapsed Time、Buffer Gets 和执行计划，确认是否存在全表扫描、大范围扫描、并行查询或索引选择性问题。",
                "summary": "访问路径和 Top SQL 是解释读 I/O 与 DB Time 消耗的重要入口",
                "top_sql_reads": True,
            },
            {
                "key": "storage",
                "name": "存储 I/O 链路等待",
                "domains": ["storage_io", "User I/O"],
                "events": ["direct path write", "direct path read", "db file sequential read", "db file scattered read"],
                "reason": "存储 I/O 链路存在等待，需要结合读写吞吐、IOPS、平均等待和 SQL 访问路径判断是存储能力问题还是 SQL 工作量问题。",
                "recommendation": "检查 Read/Write IO MB/s、Top Events 平均等待、SQL ordered by Reads、对象访问路径和存储侧延迟。",
                "summary": "存储读写等待需要结合 Top SQL 与存储延迟共同解释",
            },
            {
                "key": "hot_block",
                "name": "并发/热点块等待",
                "domains": ["hot_block", "hot_object", "lock_contention", "Concurrency"],
                "events": ["buffer busy waits", "read by other session", "enq:", "latch", "gc buffer busy"],
                "reason": "存在并发、热点块、热点对象或锁/闩锁竞争信号，可能由高并发访问同一对象、热点更新或阻塞链路引起。",
                "recommendation": "检查 buffer busy waits、read by other session、enq/latch 等等待事件，定位热点对象、阻塞会话、热点 SQL 和事务边界。",
                "summary": "并发热点或锁等待可能正在放大响应时间",
            },
            {
                "key": "sql_cpu",
                "name": "SQL/CPU 执行消耗",
                "domains": ["CPU", "Parse", "parse_pressure"],
                "events": ["DB CPU", "library cache", "cursor mutex"],
                "reason": "数据库 CPU 或解析消耗偏高，需要通过 Top SQL 的 CPU Time、Buffer Gets、Executions 和执行计划解释其来源。",
                "recommendation": "优先检查 Top SQL by CPU、Gets、Elapsed Time，以及统计信息、索引、绑定变量和执行计划稳定性。",
                "summary": "DB CPU 是最大的时间消耗来源，需要优先通过 Top SQL 解释其来源",
            },
            {
                "key": "parse_cpu",
                "name": "SQL 解析消耗过高",
                "domains": ["Parse", "parse_pressure"],
                "events": ["library cache", "cursor", "hard parse"],
                "reason": "Parse 时间占 DB Time 比例很高，可能存在硬解析、绑定变量缺失、游标共享问题或共享池争用。",
                "recommendation": "检查 Hard Parses、Parse Calls、绑定变量使用、cursor_sharing 参数和共享池大小。",
                "summary": "SQL 解析消耗是 DB Time 的重要组成部分，需要检查绑定变量和游标共享",
            },
            {
                "key": "rac_gc",
                "name": "RAC Global Cache 等待",
                "domains": ["rac_global_cache", "Concurrency"],
                "events": ["gc current block", "gc cr block", "gc buffer busy", "gc current grant"],
                "reason": "RAC Global Cache 等待偏高，可能存在跨实例缓存争用、热点块跨节点传输或互联网络瓶颈。",
                "recommendation": "检查 gc 等待事件、互联网络延迟、热点对象跨节点访问、并行查询跨实例执行和 SQL 执行计划。",
                "summary": "RAC Global Cache 等待需要结合互联网络和热点对象分析",
            },
        ]

        for config in chain_configs:
            # Phase 3A: access_path requires meaningful activity
            if config["key"] == "access_path" and not self.should_activate_access_path(domain_map):
                continue

            domains = [domain_map[name] for name in config["domains"] if name in domain_map]
            active_domains = [domain for domain in domains if domain.severity != "NORMAL"]
            events = self.find_events(context, config["events"])
            has_sql_reads = bool(config.get("top_sql_reads") and context.top_sql_reads)
            if not active_domains and not events and not has_sql_reads:
                continue

            event_pct = sum(safe_float(event.get("pct_db_time")) for event in events)
            # For non-primary chains, require meaningful severity (not just OBSERVE)
            has_warning_plus = any(d.severity in ("WARNING", "HIGH") for d in active_domains)
            is_primary = config["key"] in ("sql_cpu", "parse_cpu", "redo")
            if not is_primary and not has_warning_plus and event_pct < 3 and not has_sql_reads:
                continue

            value = sum(safe_float(domain.value) for domain in active_domains) + event_pct
            severity = self.chain_severity(active_domains, event_pct, has_sql_reads)
            if severity == "NORMAL":
                continue
            evidence = self.chain_evidence(active_domains, events, has_sql_reads)
            chains.append(
                {
                    "key": config["key"],
                    "name": config["name"],
                    "severity": severity,
                    "score": SEVERITY_RANK[severity] * 100 + value,
                    "value": evidence,
                    "reason": config["reason"],
                    "recommendation": config["recommendation"],
                    "summary": config["summary"],
                    "domains": active_domains,
                    "events": events,
                }
            )

        return sorted(chains, key=lambda chain: chain["score"], reverse=True)

    def build_cause_flows(self, context):
        chains = self.build_root_cause_chains(context)
        if not chains:
            return []

        chain_map = {chain["key"]: chain for chain in chains}
        flows = []
        for root in self.flow_roots(chains):
            path_keys = self.expand_flow_path(root["key"], chain_map)
            if len(path_keys) < 2:
                continue
            path_chains = [chain_map[key] for key in path_keys if key in chain_map]
            amplifiers = [chain["name"] for chain in path_chains[1:-1]]
            symptoms = [path_chains[-1]["name"]]
            flows.append(
                CauseFlow(
                    title=self.flow_title(path_chains),
                    severity=self.chain_severity_from_path(path_chains),
                    root=root["name"],
                    amplifiers=amplifiers,
                    symptoms=symptoms,
                    evidence=self.flow_evidence(path_chains),
                    explanation=self.flow_explanation(path_chains),
                )
            )

        return flows

    def flow_roots(self, chains):
        chain_map = {chain["key"]: chain for chain in chains}
        # If redo is dominant (HIGH with substantial value), make it the root
        redo_chain = chain_map.get("redo")
        if redo_chain and redo_chain["severity"] == "HIGH":
            redo_value = sum(safe_float(d.value) for d in redo_chain.get("domains", []))
            if redo_value >= 30:
                return [redo_chain]
        # Otherwise prefer sql_cpu, parse_cpu, redo, temp, access_path as root
        for key in ("sql_cpu", "parse_cpu", "rac_gc", "redo", "temp", "access_path", "storage"):
            if key in chain_map:
                return [chain_map[key]]
        return chains[:1]

    def expand_flow_path(self, root_key, chain_map):
        path = [root_key]
        current = root_key
        visited = {root_key}
        while True:
            next_key = None
            for candidate in CAUSE_GRAPH.get(current, []):
                if candidate in chain_map and candidate not in visited:
                    next_key = candidate
                    break
            if not next_key:
                break
            path.append(next_key)
            visited.add(next_key)
            current = next_key
        return path

    def chain_severity_from_path(self, chains):
        severities = [chain["severity"] for chain in chains]
        for severity in ("HIGH", "WARNING", "OBSERVE"):
            if severity in severities:
                return severity
        return "NORMAL"

    def flow_title(self, chains):
        return f"{chains[0]['name']}传播链"

    def flow_evidence(self, chains):
        return [
            EvidenceItem(
                chain["name"],
                chain["value"],
                chain["reason"],
            )
            for chain in chains
        ]

    def flow_explanation(self, chains):
        root_name = chains[0]["name"]
        downstream = [c["name"] for c in chains[1:]]
        explanations = {
            "大查询/批处理访问路径问题": "大查询或批处理 SQL 先制造大量读写工作量，随后放大 TEMP、存储、redo 和并发等待。",
            "TEMP/PGA 写入压力": "排序、Hash Join 或 PGA 溢写会把内存问题转化为 TEMP I/O，进一步推高存储写和 redo/checkpoint 压力。",
            "Redo/LGWR 写入链路异常": "redo 写入链路阻塞会表现为 log buffer、log file sync 或日志切换等待，并可能继续放大提交和并发等待。",
            "SQL/CPU 执行消耗": "高 CPU 或高逻辑读 SQL 会制造更多访问路径和 I/O 压力，最终体现为 DB Time 上升。",
            "存储 I/O 链路等待": "存储 I/O 等待可能源自 SQL 访问路径问题或存储能力不足，并向 redo/checkpoint 和并发等待传播。",
            "并发/热点块等待": "热点对象或锁竞争会放大其他等待事件的影响，导致响应时间恶化。",
            "SQL 解析消耗过高": "大量硬解析或游标共享问题直接消耗 CPU 和共享池资源，可能间接影响其他 SQL 的解析性能。",
            "RAC Global Cache 等待": "跨实例缓存争用增加了数据块传输延迟，可能因热点对象或不当的数据分区策略导致。",
        }
        if root_name in explanations:
            return explanations[root_name]
        if downstream:
            return f"{root_name} 是上游问题，向 {'、'.join(downstream)} 传播放大。"
        return f"{root_name} 是当前需要优先解决的问题。"

    def chain_severity(self, domains, event_pct, has_sql_reads=False):
        severities = [domain.severity for domain in domains]
        if event_pct >= 10:
            severities.append("HIGH")
        elif event_pct >= 3:
            severities.append("WARNING")
        elif event_pct >= 1 or has_sql_reads:
            severities.append("OBSERVE")
        for severity in ("HIGH", "WARNING", "OBSERVE"):
            if severity in severities:
                return severity
        return "NORMAL"

    def chain_evidence(self, domains, events, has_sql_reads=False):
        parts = []
        for domain in domains:
            parts.append(f"{self.display_domain_name(domain)} {self.format_domain_value(domain)}")
        for event in events[:3]:
            event_name = event.get("event", "unknown")
            pct = self.format_number(event.get("pct_db_time"))
            parts.append(f"{event_name} {pct}%")
        if has_sql_reads:
            parts.append("SQL ordered by Reads 存在排查对象")
        return "；".join(parts)

    def first_chain_action(self, chain):
        actions = {
            "redo": "Redo/LGWR 与 checkpoint 链路",
            "temp": "TEMP/PGA 与发生溢写的 SQL",
            "access_path": "Top SQL by Reads 和访问路径",
            "storage": "存储等待与 Top SQL by Reads",
            "hot_block": "热点对象、阻塞链路和并发等待",
            "sql_cpu": "Top SQL",
            "parse_cpu": "绑定变量、Hard Parses 和游标共享",
            "rac_gc": "RAC 互联网络和跨实例热点对象",
        }
        return actions.get(chain["key"], "Top SQL")

    def append_sql_finding(self, context, findings):
        top_sql = context.top_sql_elapsed
        if top_sql:
            findings.append(
                Finding(
                    name="存在多个高耗时 Top SQL",
                    severity="OBSERVE",
                    value="、".join(self.top_sql_ids(context)[:5]),
                    description="Top SQL 是解释 CPU、I/O 和 DB Time 的排查入口，不作为独立 DB Time 问题域参与主瓶颈排序。",
                    reason="需要结合 Elapsed Time、CPU Time、Buffer Gets、Physical Reads 和 Executions 判断具体原因。",
                )
            )

    def find_events(self, context, keywords):
        matches = []
        for item in context.top_events:
            event_name = str(item.get("event", "")).lower()
            if any(keyword.lower() in event_name for keyword in keywords):
                matches.append(item)
        return matches

    def visible_domains(self, domains):
        names = {domain.name for domain in domains}
        visible = []
        for domain in domains:
            if domain.name == "Configuration" and "redo_pipeline" in names:
                continue
            visible.append(domain)
        return visible

    def core_time_breakdown(self, context):
        names = {"DB CPU", "User I/O", "Configuration", "Commit", "Parse"}
        return [item for item in context.time_breakdown if item.name in names]

    def domain_finding_name(self, domain):
        if domain.role == "main":
            return f"{self.display_domain_name(domain)}是当前主问题"
        if domain.role == "secondary":
            return f"{self.display_domain_name(domain)}是伴随问题"
        return f"{self.display_domain_name(domain)}需要关注"

    def display_domain_name(self, domain):
        names = {
            "CPU": "CPU 消耗偏高",
            "User I/O": "User I/O 等待",
            "Commit": "Commit 等待",
            "Configuration": "Redo/Checkpoint 配置异常" if domain.name == "Configuration" else "Configuration 等待",
            "Concurrency": "并发等待",
            "Application": "应用等待",
            "Network": "网络等待",
            "Parse": "SQL 解析压力",
            "Memory": "内存压力",
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
            "rac_global_cache": "RAC Global Cache",
        }
        return names.get(domain.name, domain.name)

    def summary_metric_name(self, domain):
        if domain.name == "CPU":
            return "DB CPU"
        return domain.name

    def build_domain_reason(self, domain):
        if domain.severity == "NORMAL":
            if domain.name == "Memory":
                return "未发现明显内存压力信号。"
            if domain.name in SEMANTIC_DISPLAY_NAMES:
                return f"未发现明显{SEMANTIC_DISPLAY_NAMES[domain.name]}信号。"
            return f"{domain.name} 当前占比不高，不是本次 AWR 的主要问题。"
        return domain.reason

    def format_domain_detail(self, domain):
        if domain.name == "Memory":
            return f"{domain.severity} / {self.role_text(domain.role)}"
        return f"{self.format_number(domain.value)}% DB Time / {domain.severity} / {self.role_text(domain.role)}"

    def role_text(self, role):
        return {
            "main": "主问题",
            "secondary": "伴随问题",
            "observe": "需要关注",
            "normal": "非主因",
        }.get(role, role)

    def format_domain_value(self, domain):
        if domain.name == "Memory":
            return "存在内存压力信号" if domain.value else "无明显内存压力"
        return f"{self.format_number(domain.value)}%"

    def format_number(self, value):
        number = safe_float(value)
        text = f"{number:.2f}".rstrip("0").rstrip(".")
        return text or "0"

    def format_event_value(self, item):
        value = item.get("pct_db_time")
        time_s = item.get("time_s")
        if time_s not in (None, "", 0, "0"):
            return f"{time_s} 秒，{value}%"
        return value

    def has_event(self, context, keyword):
        return self.find_event(context, keyword) is not None

    def find_event(self, context, keyword):
        keyword = keyword.lower()
        for item in context.top_events:
            if keyword in str(item.get("event", "")).lower():
                return item
        return None

    def logical_reads_high(self, metrics):
        return (metrics.get("logical_read_blocks_per_sec", 0) or 0) >= 100000

    def physical_reads_high(self, metrics):
        return (metrics.get("physical_read_blocks_per_sec", 0) or 0) >= 50000 or (metrics.get("read_io_mb_per_sec", 0) or 0) >= 500

    def semantic_active(self, context, name):
        return any(domain.name == name and domain.severity != "NORMAL" for domain in context.problem_domains)

    def semantic_evidence(self, metrics):
        evidence = []
        for name, group in (metrics.get("event_semantics") or {}).items():
            events = group.get("events") or []
            pct = round(group.get("pct_db_time", 0), 2)
            if not events or pct <= 0:
                continue
            evidence.append(
                EvidenceItem(
                    SEMANTIC_DISPLAY_NAMES.get(name, name),
                    f"{pct}% DB Time",
                    "、".join(item.get("event", "unknown") for item in events[:5]),
                )
            )
        return evidence

    def sql_behavior_evidence(self, metrics):
        return [
            EvidenceItem(
                item.get("sql_id"),
                item.get("category"),
                item.get("reason"),
            )
            for item in metrics.get("top_sql_behaviors", [])
        ]

    def sql_detail_evidence(self, context):
        evidence = []
        seen = set()
        for category, rows in [
            ("Elapsed", context.top_sql_elapsed),
            ("CPU", context.top_sql_cpu),
            ("Gets", context.top_sql_gets),
            ("Reads", context.top_sql_reads),
        ]:
            for row in rows[:5]:
                sql_id = row.get("sql_id")
                if not sql_id or sql_id in seen:
                    continue
                seen.add(sql_id)
                text = row.get("sql_text", "")
                executions = safe_float(row.get("executions"))
                gets = safe_float(row.get("buffer_gets"))
                reads = safe_float(row.get("physical_reads"))
                parts = [f"Elapsed: {row.get('elapsed_time', 'N/A')}"]
                if executions:
                    parts.append(f"Execs: {int(executions)}")
                if gets and executions:
                    parts.append(f"Gets/Exec: {int(gets / executions)}")
                if reads and executions:
                    parts.append(f"Reads/Exec: {int(reads / executions)}")
                if text:
                    parts.append(f"SQL: {text}")
                evidence.append(EvidenceItem(
                    sql_id,
                    " | ".join(parts),
                    f"来源: SQL ordered by {category}",
                ))
        return evidence

    def segment_evidence(self, metrics):
        evidence = []
        for seg in (metrics.get("segments_logical_reads") or [])[:10]:
            name = seg.get("object_name", "")
            if not name:
                continue
            owner = seg.get("owner", "")
            pct = seg.get("pct_total", "")
            obj_type = seg.get("obj_type", "")
            evidence.append(EvidenceItem(
                f"{owner}.{name}",
                f"{pct}% of Logical Reads",
                f"类型: {obj_type}",
            ))
        return evidence

    def latch_evidence(self, metrics):
        evidence = []
        for latch in (metrics.get("latch_activity") or []):
            miss_pct = safe_float(latch.get("pct_get_miss"))
            wait_time = safe_float(latch.get("wait_time_s"))
            if miss_pct < 1 and wait_time < 1:
                continue
            name = latch.get("latch_name", "unknown")
            evidence.append(EvidenceItem(
                name,
                f"Miss: {miss_pct}%, Wait: {wait_time}s",
                f"Get Requests: {latch.get('get_requests', 'N/A')}",
            ))
        return evidence[:15]

    def enqueue_evidence(self, metrics):
        evidence = []
        for eq in (metrics.get("enqueue_activity") or [])[:15]:
            wt_time = safe_float(eq.get("wt_time_s"))
            if wt_time < 1:
                continue
            eq_type = eq.get("enqueue_type", "unknown")
            evidence.append(EvidenceItem(
                eq_type,
                f"Waits: {eq.get('waits', 'N/A')}, Wait Time: {self.format_number(wt_time)}s",
                f"Avg: {eq.get('av_wt_time_ms', 'N/A')}ms",
            ))
        return evidence

    def host_info_evidence(self, metrics):
        evidence = []
        cpu_count = metrics.get("cpu_count", 0)
        if cpu_count:
            evidence.append(EvidenceItem("CPU Count", int(cpu_count)))
        idle = metrics.get("host_cpu_idle_pct", 0)
        if idle:
            evidence.append(EvidenceItem("Host CPU Idle", f"{idle}%"))
        load_begin = metrics.get("load_average_begin", 0)
        load_end = metrics.get("load_average_end", 0)
        if load_begin or load_end:
            evidence.append(EvidenceItem("Load Average", f"Begin: {load_begin}, End: {load_end}"))
        db_cpu_pct = metrics.get("db_instance_cpu_pct", 0)
        if db_cpu_pct:
            evidence.append(EvidenceItem("DB Instance CPU%", f"{db_cpu_pct}%"))
        return evidence

    def waiting_model_text(self, model):
        return {
            "waiting_dominant": "等待型数据库",
            "cpu_dominant": "CPU 型数据库",
            "mixed": "混合型数据库",
        }.get(model, model)

    def top_sql_pct_total(self, rows):
        if not rows:
            return 0
        raw = rows[0].get("raw") or {}
        return max(safe_float(raw.get("pcttotal")), safe_float(rows[0].get("pct_total")))

    def top_sql_numeric(self, rows, fields):
        if not rows:
            return 0
        row = rows[0]
        raw = row.get("raw") or {}
        values = []
        for field in fields:
            values.append(safe_float(row.get(field)))
            values.append(safe_float(raw.get(field)))
        return max(values)

    def top_sql_ids(self, context):
        ids = []
        for rows in (context.top_sql_elapsed, context.top_sql_cpu, context.top_sql_gets, context.top_sql_reads):
            for row in rows:
                sql_id = row.get("sql_id")
                if sql_id and sql_id not in ids:
                    ids.append(sql_id)
        return ids

    # Compatibility helpers kept for older tests and callers.
    def detect_main_bottleneck(self, metrics):
        candidates = []
        db_cpu = metrics.get("db_cpu_pct_db_time", 0) or 0
        user_io = metrics.get("user_io_pct_db_time", 0) or 0
        commit = metrics.get("commit_pct_db_time", 0) or 0
        parse_time = metrics.get("parse_time_pct_db_time", 0) or 0
        if db_cpu >= 40:
            candidates.append(("CPU", db_cpu))
        if user_io >= 15:
            candidates.append(("I/O", user_io))
        if commit >= 10:
            candidates.append(("Commit", commit))
        if parse_time >= 10:
            candidates.append(("Parse", parse_time))
        if not candidates:
            return "未发现明显单一瓶颈"
        candidates.sort(key=lambda item: item[1], reverse=True)
        return candidates[0][0]
