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

    def _call(self, prompt: str, max_tokens: int = 4096) -> str:
        """Call OpenAI-compatible chat completions API."""
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
                    "\n"
                    "关键原则：\n"
                    "- 区分根因和症状：CPU 高可能是根因（SQL 差），也可能是症状（等待导致堆积）\n"
                    "- AAS > CPU 核数 = 系统饱和，需要关注等待事件而非只看 CPU\n"
                    "- db file sequential read 延迟 > 10ms = 存储层可能有问题\n"
                    "- log file sync > 5ms = redo 写入需要优化\n"
                    "- 给出建议时必须包含具体操作步骤，不要只说'优化 SQL'\n"
                    "请用中文回答。"
                )},
                {"role": "user", "content": prompt},
            ],
        }

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=180)
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            # Try to extract error message from response
            try:
                error_data = resp.json()
                error_msg = error_data.get("error", {}).get("message", str(e))
            except Exception:
                error_msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
            raise Exception(f"API 请求失败: {error_msg}") from e
        except requests.exceptions.RequestException as e:
            raise Exception(f"网络请求失败: {str(e)}") from e

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
                for i, sql in enumerate(sql_list[:5], 1):
                    sql_id = sql.get("sql_id", "")
                    elapsed_s = sql.get("elapsed_time", "")
                    execs = sql.get("executions", "")
                    gets = sql.get("buffer_gets", "")
                    reads = sql.get("physical_reads", "")
                    text = (sql.get("sql_text", "") or "")[:200]
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

        # === 10. Known Patterns ===
        if active_patterns:
            lines.append("【已知诊断模式（历史积累）】")
            for p in active_patterns[:5]:
                lines.append(f"  - {p.get('name', '')}: {p.get('conditions', '')} → {p.get('solution', '')}")
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

    def _parse_response(self, text: str) -> dict[str, Any]:
        """Parse LLM response with three-tier fallback."""
        empty = {"expert_analysis": "", "key_findings": [], "sql_recommendations": [], "parameter_suggestions": [], "learned_patterns": []}
        if not text:
            return empty

        # Tier 1: direct JSON
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass

        # Tier 2: code block
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except (json.JSONDecodeError, TypeError):
                pass

        # Tier 3: first { to last }
        first = text.find("{")
        last = text.rfind("}")
        if first != -1 and last > first:
            try:
                return json.loads(text[first:last + 1])
            except (json.JSONDecodeError, TypeError):
                pass

        # Fallback: treat entire response as expert_analysis
        empty["expert_analysis"] = text
        return empty
