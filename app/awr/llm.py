"""LLM integration for enhanced AWR analysis."""
from __future__ import annotations

import json
import re
import logging
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM INTEGRATION
# ---------------------------------------------------------------------------

class LLMIntegration:
    """Interface for LLM-enhanced analysis with structured output."""

    def __init__(self, provider: str = 'none', api_key: str = '', api_url: str = '', model: str = '') -> None:
        self.provider = provider
        self.api_key = api_key
        self.api_url = api_url
        self.model = model

    def enhance_analysis(self, parsed_data: dict[str, Any], problems: list[dict], correlations: list[dict],
                         anti_patterns: list[dict] | None = None, wait_class_summary: dict[str, float] | None = None,
                         param_recommendations: list[dict] | None = None) -> dict[str, Any] | None:
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

    def _build_prompt(self, parsed_data: dict[str, Any], problems: list[dict], correlations: list[dict],
                      anti_patterns: list[dict] | None = None, wait_class_summary: dict[str, float] | None = None,
                      param_recommendations: list[dict] | None = None) -> str:
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

    def _parse_llm_response(self, response_text: str) -> dict[str, Any]:
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


