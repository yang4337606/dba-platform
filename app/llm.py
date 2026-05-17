"""LLM client for enhanced AWR analysis. OpenAI-compatible API."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests

logger = logging.getLogger(__name__)


class LLMClient:
    """OpenAI-compatible LLM client for AWR expert analysis."""

    def __init__(self, base_url: str = "", api_key: str = "", model: str = "") -> None:
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.api_key = api_key
        self.model = model or "gpt-4o"

    def test_connection(self) -> dict[str, Any]:
        """Test LLM connection with a simple prompt."""
        if not self.api_key:
            return {"success": False, "error": "API Key 未配置"}

        if not self.base_url:
            return {"success": False, "error": "Base URL 未配置"}

        try:
            response = self._call("请回复'连接成功'四个字。", max_tokens=50)
            return {"success": True, "model": self.model, "response": response[:100]}
        except Exception as e:
            error_msg = str(e)
            # Provide helpful hints based on error type
            if "HTML" in error_msg or "Unexpected token" in error_msg:
                error_msg += "\n提示: Base URL 可能不正确，请确保是 API 端点而不是网页地址"
            elif "401" in error_msg or "Unauthorized" in error_msg:
                error_msg += "\n提示: API Key 可能无效或已过期"
            elif "404" in error_msg:
                error_msg += "\n提示: API 端点不存在，请检查 Base URL 和模型名称"
            elif "timeout" in error_msg.lower():
                error_msg += "\n提示: 请求超时，请检查网络连接"

            return {"success": False, "error": error_msg}

    def analyze(self, result: Any, metrics: dict[str, Any], active_patterns: list[dict] | None = None) -> dict[str, Any] | None:
        """Send structured AWR data to LLM for expert analysis."""
        if not self.api_key:
            return None
        try:
            prompt = self._build_prompt(result, metrics, active_patterns)
            response_text = self._call(prompt)
            parsed = self._parse_response(response_text)
            parsed["_raw_response"] = response_text
            return parsed
        except Exception as e:
            logger.error("LLM analysis failed: %s", e)
            return {"error": str(e), "expert_analysis": "", "key_findings": [], "sql_recommendations": [], "parameter_suggestions": [], "learned_patterns": []}

    def deep_analyze(self, result: Any, metrics: dict[str, Any], active_patterns: list[dict] | None = None) -> dict[str, Any] | None:
        """Enhanced deep analysis with comprehensive prompt and larger output."""
        if not self.api_key:
            return None
        try:
            prompt = self._build_deep_prompt(result, metrics, active_patterns)
            response_text = self._call(prompt, max_tokens=8192)
            parsed = self._parse_response(response_text)
            parsed["_raw_response"] = response_text
            return parsed
        except Exception as e:
            logger.error("LLM deep analysis failed: %s", e)
            return {"error": str(e)}

    def _call(self, prompt: str, max_tokens: int = 4096) -> str:
        """Call OpenAI-compatible chat completions API with retry."""
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.model,
            "temperature": 0.3,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": (
                    "你是一位拥有 20 年经验的资深 Oracle DBA 专家，专长领域包括：\n"
                    "1. Oracle 性能调优（AWR/ASH/ADDM 分析、等待事件解读、SQL 优化）\n"
                    "2. 数据库架构设计（分区策略、存储架构、RAC/ADG 高可用）\n"
                    "3. SQL 执行计划优化（索引设计、统计信息管理、SPM 计划基线）\n"
                    "4. 内存与 I/O 调优（SGA/PGA 配置、存储子系统、ASM）\n"
                    "\n"
                    "分析方法论：\n"
                    "- 先看 Wait Events → 确定主要瓶颈方向（CPU/IO/锁/网络/并发）\n"
                    "- 再看 Top SQL → 定位具体问题 SQL 和执行计划\n"
                    "- 结合 Load Profile → 判断工作负载特征（OLTP/批处理/混合）\n"
                    "- 参考 OS Stats → 验证资源瓶颈（CPU/内存/IO）\n"
                    "- 分析问题传播链 → 区分根因和症状\n"
                    "\n"
                    "关键原则：\n"
                    "- 区分根因和症状：CPU 高可能是根因（SQL 差），也可能是症状（等待导致堆积）\n"
                    "- AAS > CPU 核数 = 系统饱和，需要关注等待事件而非只看 CPU\n"
                    "- db file sequential read 延迟 > 10ms = 存储层可能有问题\n"
                    "- log file sync > 5ms = redo 写入需要优化\n"
                    "- 给出建议时必须包含具体操作步骤，不要只说'优化 SQL'\n"
                    "- SQL 建议需包含执行计划级别的建议（如添加索引列、改写JOIN方式）\n"
                    "- 参数建议必须给出具体推荐值（如 PGA_AGGREGATE_TARGET = 8G）\n"
                    "- 分析问题因果传播链：根因 → 中间效应 → 最终症状\n"
                    "- 识别事件语义分组的关联性，如 redo_pipeline + commit 的因果关系\n"
                    "请用中文回答。"
                )},
                {"role": "user", "content": prompt},
            ],
        }

        # Retry with exponential backoff (up to 2 retries)
        max_retries = 2
        timeout = 60  # 60 seconds per attempt
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
                resp.raise_for_status()
                break
            except requests.exceptions.HTTPError as e:
                try:
                    error_data = resp.json()
                    error_msg = error_data.get("error", {}).get("message", str(e))
                except Exception:
                    error_msg = f"HTTP {resp.status_code}: {resp.text[:200]}"

                # Don't retry on auth errors or bad requests
                if resp.status_code in (400, 401, 403, 404):
                    raise Exception(f"API 请求失败: {error_msg}") from e

                last_error = Exception(f"API 请求失败: {error_msg}")
                if attempt < max_retries:
                    import time
                    time.sleep(2 ** attempt)  # 1s, 2s
                    continue
                raise last_error from e

            except requests.exceptions.Timeout as e:
                last_error = Exception(f"请求超时 ({timeout}s)，请检查网络或减少输入数据量")
                if attempt < max_retries:
                    import time
                    time.sleep(2 ** attempt)
                    continue
                raise last_error from e

            except requests.exceptions.RequestException as e:
                last_error = Exception(f"网络请求失败: {str(e)}")
                if attempt < max_retries:
                    import time
                    time.sleep(2 ** attempt)
                    continue
                raise last_error from e

        # Parse JSON response
        try:
            data = resp.json()
        except json.JSONDecodeError as e:
            content_preview = resp.text[:200]
            if resp.text.strip().startswith("<"):
                raise Exception(f"API 返回了 HTML 而不是 JSON，请检查 Base URL 是否正确。URL: {url}") from e
            raise Exception(f"API 返回了无效的 JSON: {content_preview}") from e

        # Extract message content
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise Exception(f"API 响应格式不正确: {json.dumps(data, ensure_ascii=False)[:200]}") from e

    def _build_prompt(self, result: Any, metrics: dict[str, Any], active_patterns: list[dict] | None = None) -> str:
        """Build comprehensive AWR analysis prompt."""
        lines = []
        lines.append("请分析以下 Oracle AWR 报告数据，给出专家级诊断建议。")
        lines.append("")

        # === 1. DB Info ===
        db_info = metrics.get("db_info", {}) or {}
        if db_info:
            lines.append(f"【数据库信息】DB={db_info.get('db_name', 'N/A')}, Instance={db_info.get('instance_name', 'N/A')}")

        elapsed = metrics.get("elapsed_minutes", 0)
        db_time = metrics.get("db_time_minutes", 0)
        aas = metrics.get("aas", 0)
        lines.append(f"【快照时段】Elapsed={elapsed} 分钟, DB Time={db_time} 分钟, AAS={aas}")
        cpu_count = metrics.get("cpu_count", 0)
        host_idle = metrics.get("host_cpu_idle_pct", 0)
        if cpu_count:
            lines.append(f"【主机】CPU={int(cpu_count)}核, Host Idle={host_idle}%")
        lines.append("")

        # === 2. Rule Engine Summary (as reference) ===
        lines.append("【规则引擎初步诊断（仅供参考，请独立判断）】")
        lines.append(f"  主瓶颈: {result.main_bottleneck}")
        lines.append(f"  严重级别: {result.severity}")
        for c in (result.conclusions or [])[:3]:
            lines.append(f"  - {c}")
        lines.append("")

        # === 3. Top Events ===
        top_events = metrics.get("top_events", [])
        if top_events:
            lines.append("【Top 等待事件】")
            for i, evt in enumerate(top_events[:15], 1):
                name = evt.get("event", "")
                pct = evt.get("pct_db_time", 0)
                time_s = evt.get("time_s", "")
                avg = evt.get("avg_wait_ms", "")
                wclass = evt.get("wait_class", "")
                lines.append(f"  {i}. {name} | %DB Time={pct} | Time={time_s}s | Avg Wait={avg} | Class={wclass}")
            lines.append("")

        # === 4. Wait Classes ===
        wait_classes = metrics.get("wait_classes", [])
        if wait_classes:
            lines.append("【Wait Class 汇总】")
            for wc in wait_classes:
                name = wc.get("wait_class", "")
                pct = wc.get("pct_db_time", 0)
                if pct and float(str(pct).replace(",", "")) > 0.1:
                    lines.append(f"  {name}: {pct}% DB Time")
            lines.append("")

        # === 5. Top SQL ===
        for label, key in [("Elapsed Time", "top_sql_elapsed"), ("CPU Time", "top_sql_cpu"), ("Buffer Gets", "top_sql_gets"), ("Physical Reads", "top_sql_reads")]:
            sql_list = metrics.get(key, [])
            if sql_list:
                lines.append(f"【Top SQL by {label}】")
                for i, sql in enumerate(sql_list[:10], 1):
                    sql_id = sql.get("sql_id", "")
                    elapsed_s = sql.get("elapsed_time", "")
                    execs = sql.get("executions", "")
                    gets = sql.get("buffer_gets", "")
                    reads = sql.get("physical_reads", "")
                    text = (sql.get("sql_text", "") or "")[:500]
                    parts = [f"SQL_ID={sql_id}", f"Elapsed={elapsed_s}s", f"Execs={execs}"]
                    if gets:
                        parts.append(f"Gets={gets}")
                    if reads:
                        parts.append(f"Reads={reads}")
                    lines.append(f"  {i}. {' | '.join(parts)}")
                    if text:
                        lines.append(f"     SQL: {text}")
                lines.append("")

        # === 6. Load Profile ===
        lines.append("【Load Profile (Per Second)】")
        for name, key in [
            ("Logical Read", "logical_read_blocks_per_sec"),
            ("Physical Read", "physical_read_blocks_per_sec"),
            ("Read IO", "read_io_mb_per_sec"),
            ("Write IO", "write_io_mb_per_sec"),
            ("Redo Size", "redo_size_per_sec"),
            ("Commits", "commits_per_sec"),
            ("Executes", "executes_per_sec"),
            ("Hard Parses", "hard_parses_per_sec"),
        ]:
            val = metrics.get(key, 0)
            if val:
                lines.append(f"  {name}: {val}")
        lines.append("")

        # === 7. Segment Statistics ===
        segments = metrics.get("segments_logical_reads", [])
        if segments:
            lines.append("【热点对象 (Top Logical Reads)】")
            for seg in segments[:8]:
                owner = seg.get("owner", "")
                obj = seg.get("object_name", "")
                pct = seg.get("pct_total", "")
                obj_type = seg.get("obj_type", "")
                lines.append(f"  {owner}.{obj} ({obj_type}) - {pct}% Logical Reads")
            lines.append("")

        # === 8. Latch & Enqueue ===
        latches = metrics.get("latch_activity", [])
        if latches:
            lines.append("【异常 Latch】")
            for l in latches[:8]:
                lines.append(f"  {l.get('latch_name', '')} | Miss={l.get('pct_get_miss', '')}% | Wait={l.get('wait_time_s', '')}s")
            lines.append("")

        enqueues = metrics.get("enqueue_activity", [])
        if enqueues:
            lines.append("【Enqueue 活动】")
            for eq in enqueues[:8]:
                lines.append(f"  {eq.get('enqueue_type', '')} | Waits={eq.get('waits', '')} | Wait Time={eq.get('wt_time_s', '')}s")
            lines.append("")

        # === 9. Instance Activity ===
        ia = metrics.get("instance_activity", {})
        if ia:
            lines.append("【关键实例活动】")
            for name in ["user commits", "user rollbacks", "redo size", "redo writes", "execute count", "parse count (hard)", "parse count (total)", "sorts (disk)", "table scans (long tables)", "table fetch continued row"]:
                data = ia.get(name.lower(), {})
                if data:
                    lines.append(f"  {name}: total={data.get('total', '')}, per_sec={data.get('per_second', '')}")
            lines.append("")

        # === 10. Instance Efficiency ===
        ie_keys = [
            ("Buffer Hit Ratio", "buffer_hit_ratio"),
            ("Library Cache Hit Ratio", "library_cache_hit_ratio"),
            ("Dictionary Hit Ratio", "dict_hit_ratio"),
            ("Latch Hit Ratio", "latch_hit_ratio"),
            ("Soft Parse Ratio", "soft_parse_ratio"),
            ("In-memory Sort Ratio", "in_memory_sort_ratio"),
            ("Redo NoWait Ratio", "redo_nowait_ratio"),
            ("Non-Parse CPU", "non_parse_cpu_ratio"),
        ]
        ie_lines = []
        for name, key in ie_keys:
            val = metrics.get(key, 0)
            if val:
                ie_lines.append(f"  {name}: {val}%")
        if ie_lines:
            lines.append("【Instance Efficiency】")
            lines.extend(ie_lines)
            lines.append("")

        # === 11. Top SQL Behaviors (text analysis) ===
        behaviors = metrics.get("top_sql_behaviors", [])
        if behaviors:
            lines.append("【Top SQL 行为分析】")
            for beh in behaviors[:10]:
                sql_id = beh.get("sql_id", "")
                category = beh.get("category", "")
                reason = beh.get("reason", "")
                score = beh.get("efficiency_score", 0)
                text_info = beh.get("text_analysis", {})
                plan_info = beh.get("plan_analysis", {})
                lines.append(f"  {sql_id} [{category}] 效率={score}/100")
                lines.append(f"    分析: {reason}")
                for diag in text_info.get("diagnostics", []):
                    lines.append(f"    问题: {diag}")
                if plan_info.get("access_path"):
                    lines.append(f"    访问路径: {plan_info['access_path']}")
                if plan_info.get("join_strategy"):
                    lines.append(f"    JOIN 策略: {plan_info['join_strategy']}")
                for issue in plan_info.get("issues", []):
                    lines.append(f"    计划问题: {issue}")
                for hint in plan_info.get("hints", []):
                    lines.append(f"    计划建议: {hint}")
                n1 = beh.get("n1_pattern")
                if n1:
                    lines.append(f"    N+1: {n1.get('diagnosis', '')}")
            lines.append("")

        # === 12. Known Patterns ===
        if active_patterns:
            lines.append("【已知诊断模式（历史积累）】")
            for p in active_patterns[:5]:
                lines.append(f"  - {p.get('name', '')}: {p.get('conditions', '')} → {p.get('solution', '')}")
            lines.append("")

        # === 13. Detailed Execution Plans ===
        exec_plans = metrics.get("execution_plans", {})
        if exec_plans:
            lines.append("【详细执行计划（层级结构）】")
            for sql_id, nodes in list(exec_plans.items())[:5]:
                lines.append(f"  SQL_ID={sql_id}:")
                for node in nodes[:15]:
                    indent = "  " * (node.get("depth", 0) + 2)
                    op = node.get("operation", "")
                    opts = node.get("options", "")
                    obj = node.get("object_name", "")
                    cost = node.get("cost", "")
                    card = node.get("cardinality", "")
                    pstart = node.get("pstart", "")
                    pstop = node.get("pstop", "")
                    filters = node.get("filter_predicates", "")
                    line = f"{indent}{op} {opts} {obj}"
                    if cost:
                        line += f" cost={cost}"
                    if card:
                        line += f" card={card}"
                    if pstart:
                        line += f" Pstart={pstart}"
                    if pstop:
                        line += f" Pstop={pstop}"
                    lines.append(f"  {line}")
                    if filters:
                        lines.append(f"{indent}  FILTER: {filters}")
            lines.append("")

        # === 14. SQL Plan Baselines ===
        baselines = metrics.get("sql_plan_baselines", [])
        if baselines:
            lines.append("【SQL Plan Baseline 信息】")
            for bl in baselines[:10]:
                lines.append(f"  SQL_ID={bl.get('sql_id', '')} Plan={bl.get('plan_hash_value', '')} Enabled={bl.get('enabled', '')} Origin={bl.get('origin', '')}")
            lines.append("")

        # === Output Format ===
        lines.append("请以下面的 JSON 格式输出分析结果（不要用 ``` 包裹，直接输出 JSON）：")
        lines.append(json.dumps({
            "expert_analysis": "请用 2-5 个段落给出综合诊断分析。不要简单重复上面的数据，而是像资深 DBA 一样分析这些数据之间的关联、根因和优化方向。请特别关注 SQL 文本的语义含义。",
            "key_findings": [
                {"title": "发现标题", "detail": "详细说明，包含具体数值", "severity": "high/medium/low"}
            ],
            "sql_recommendations": [
                {"sql_id": "SQL_ID", "issue": "具体问题描述", "recommendation": "具体优化建议，如加索引、改写SQL、调整参数等"}
            ],
            "parameter_suggestions": [
                {"parameter": "参数名", "current": "当前问题", "recommended": "建议值或调整方向", "reason": "原因"}
            ],
            "learned_patterns": [
                {"pattern_name": "模式名", "conditions": "触发条件（用自然语言描述指标和阈值）", "solution": "解决方案"}
            ]
        }, ensure_ascii=False, indent=2))

        return "\n".join(lines)

    def _build_deep_prompt(self, result: Any, metrics: dict[str, Any], active_patterns: list[dict] | None = None) -> str:
        """Build comprehensive deep analysis prompt with all available data."""
        lines = []
        lines.append("请对以下 Oracle AWR 报告数据进行深度专家级分析。要求：")
        lines.append("1. 分析各指标之间的因果关联，构建问题传播链")
        lines.append("2. 对 Top SQL 给出执行计划级别的优化建议（索引设计、JOIN 方式、分区策略）")
        lines.append("3. 对参数调整给出具体推荐值")
        lines.append("4. 区分根因和症状，避免把症状当根因")
        lines.append("")

        # Use the standard prompt as base
        lines.append(self._build_prompt(result, metrics, active_patterns))

        # === Additional sections for deep analysis ===

        # Event Semantic Groups
        semantics = metrics.get("event_semantics", {})
        if semantics:
            lines.append("【事件语义分组分析】")
            for name, group in semantics.items():
                pct = group.get("pct_db_time", 0)
                events = group.get("events", [])
                if pct > 0 and events:
                    event_names = ", ".join(e.get("event", "") for e in events[:5])
                    lines.append(f"  {name}: {pct}% DB Time → {event_names}")
            lines.append("")

        # PGA/SGA Advisory
        pga_benefit = metrics.get("pga_advisory_benefit_pct", 0)
        sga_benefit = metrics.get("sga_advisory_benefit_pct", 0)
        if pga_benefit or sga_benefit:
            lines.append("【PGA/SGA Advisory】")
            if pga_benefit:
                lines.append(f"  PGA: 当前 {metrics.get('pga_advisory_current_mb', 0)}MB, 建议最优 {metrics.get('pga_advisory_estimated_optimal_mb', 0)}MB, 改进空间 {pga_benefit}%")
            if sga_benefit:
                lines.append(f"  SGA: 当前 {metrics.get('sga_advisory_current_mb', 0)}MB, 建议最优 {metrics.get('sga_advisory_estimated_optimal_mb', 0)}MB, 改进空间 {sga_benefit}%")
            lines.append("")

        # IO Stats by tablespace
        avg_read = metrics.get("io_stats_avg_read_latency_ms", 0)
        if avg_read:
            lines.append("【IO Stats (按表空间)】")
            lines.append(f"  平均读延迟: {avg_read}ms, 平均写延迟: {metrics.get('io_stats_avg_write_latency_ms', 0)}ms")
            lines.append(f"  热点表空间: {metrics.get('io_stats_hot_tablespace', 'N/A')}")
            for ts in (metrics.get("io_stats_high_latency_tablespaces") or [])[:5]:
                lines.append(f"  高延迟: {ts.get('tablespace', '')} - 读延迟 {ts.get('read_latency_ms', 0)}ms")
            lines.append("")

        # Foreground Wait Class
        fg_cpu = metrics.get("foreground_db_cpu_pct", 0)
        fg_top = metrics.get("fg_top_wait_class", "")
        if fg_cpu or fg_top:
            lines.append("【Foreground Wait Class】")
            lines.append(f"  前台 DB CPU: {fg_cpu}%")
            lines.append(f"  前台 Top Wait: {fg_top} ({metrics.get('fg_top_wait_pct', 0)}%)")
            lines.append("")

        # Segment Physical Reads and Scans
        seg_phys = metrics.get("segments_physical_reads_top3", [])
        seg_scans = metrics.get("segments_table_scans_top3", [])
        if seg_phys or seg_scans:
            lines.append("【热点对象 (Physical Reads + Scans)】")
            for s in seg_phys:
                lines.append(f"  物理读: {s.get('owner', '')}.{s.get('object_name', '')} - {s.get('pct_total', 0)}%")
            for s in seg_scans:
                lines.append(f"  表扫描: {s.get('owner', '')}.{s.get('object_name', '')} - {s.get('pct_total', 0)}%")
            lines.append("")

        # More Instance Activity
        lines.append("【扩展实例活动指标】")
        for name, key in [
            ("Total Parses/s", "parse_total_per_sec"),
            ("Hard Parse%", "parse_ratio_hard_pct"),
            ("Logons/s", "logons_per_sec"),
            ("Open Cursors/s", "open_cursors_per_sec"),
            ("Session Logical Reads/s", "session_logical_reads_per_sec"),
            ("Physical Reads/s", "physical_reads_per_sec"),
            ("Redo Writes/s", "redo_writes_per_sec"),
            ("Avg Redo Write Size", "avg_redo_write_size"),
        ]:
            val = metrics.get(key, 0)
            if val:
                lines.append(f"  {name}: {val}")
        lines.append("")

        # Workload type info
        lines.append(f"【工作负载判断】类型={metrics.get('workload_type', 'N/A')}, 负载强度={metrics.get('load_intensity', 'N/A')}, 时间模型={metrics.get('waiting_vs_cpu_model', 'N/A')}")

        # OS Stats expanded
        os_stats = metrics.get("os_stats", {})
        if os_stats:
            lines.append("【OS Stats (完整)】")
            for key, val in os_stats.items():
                if isinstance(val, dict):
                    v = val.get("value", val.get("end_value", ""))
                    if v:
                        lines.append(f"  {key}: {v}")
                elif val:
                    lines.append(f"  {key}: {val}")
            lines.append("")

        # Output format for deep analysis
        lines.append("")
        lines.append("请以下面的 JSON 格式输出深度分析结果（不要用 ``` 包裹，直接输出 JSON）：")
        lines.append(json.dumps({
            "root_cause_analysis": "用 2-3 段详细分析根因。区分根因和症状，说明因果关系。参考事件语义分组、PGA/SGA Advisory、IO Stats 等额外数据。",
            "problem_propagation_chain": [
                {"cause": "根因描述", "effect": "中间效应", "evidence": "支持数据（具体指标值）"}
            ],
            "expert_analysis": "综合诊断分析，像资深 DBA 一样分析数据之间的关联、根因和优化方向。",
            "key_findings": [
                {"title": "发现标题", "detail": "详细说明，包含具体数值", "severity": "high/medium/low"}
            ],
            "sql_recommendations": [
                {
                    "sql_id": "SQL_ID",
                    "issue": "具体问题描述",
                    "recommendation": "具体优化建议",
                    "execution_plan_hint": "执行计划级别建议，如添加索引 (col1, col2)、改用 HASH JOIN、使用分区裁剪等",
                    "estimated_impact": "high/medium/low"
                }
            ],
            "parameter_suggestions": [
                {
                    "parameter": "参数名",
                    "current_value": "当前配置或表现",
                    "recommended_value": "具体推荐值，如 PGA_AGGREGATE_TARGET=8G",
                    "reason": "调整原因"
                }
            ],
            "learned_patterns": [
                {"pattern_name": "模式名", "conditions": "触发条件", "solution": "解决方案"}
            ]
        }, ensure_ascii=False, indent=2))

        return "\n".join(lines)

    def _parse_response(self, text: str) -> dict[str, Any]:
        """Parse LLM response with three-tier fallback and schema validation."""
        required_keys = {"expert_analysis", "key_findings", "sql_recommendations",
                         "parameter_suggestions", "learned_patterns"}
        empty = {k: "" if k == "expert_analysis" else [] for k in required_keys}

        if not text:
            return empty

        parsed = None

        # Tier 1: direct JSON
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass

        # Tier 2: code block
        if parsed is None:
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group(1))
                except (json.JSONDecodeError, TypeError):
                    pass

        # Tier 3: first { to last } (with size limit to prevent JSON bombs)
        if parsed is None:
            first = text.find("{")
            last = text.rfind("}")
            if first != -1 and last > first and (last - first) < 100_000:
                try:
                    parsed = json.loads(text[first:last + 1])
                except (json.JSONDecodeError, TypeError):
                    pass

        # Validate and normalize
        if parsed is not None and isinstance(parsed, dict):
            # Ensure all required keys exist with correct types
            for key in required_keys:
                if key not in parsed:
                    parsed[key] = "" if key == "expert_analysis" else []
                elif key != "expert_analysis" and not isinstance(parsed[key], list):
                    parsed[key] = []
            return parsed

        # Fallback: treat entire response as expert_analysis
        empty["expert_analysis"] = text
        return empty
