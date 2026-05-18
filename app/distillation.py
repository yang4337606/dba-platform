"""
知识蒸馏引擎 — 使用 LLM 定期审查和优化诊断模式库

功能：
- 合并重复/相似模式
- 精炼模糊模式，添加具体阈值
- 从案例中发现未捕获的模式
- 基于案例证据调整模式置信度
- 淘汰低质量模式
"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

DISTILLATION_CONFIDENCE = 0.50


class DistillationEngine:
    """知识库蒸馏器"""

    def __init__(self, knowledge_base, llm_client) -> None:
        self.kb = knowledge_base
        self.llm = llm_client

    def run_distillation(self) -> dict:
        """Run distillation. Returns report dict (not yet applied)."""
        patterns = self.kb.get_all_patterns()

        # Load cases
        cases_path = os.path.join(self.kb.knowledge_dir, "cases.json")
        try:
            with open(cases_path, "r", encoding="utf-8") as f:
                all_cases = json.load(f).get("cases", [])
        except (FileNotFoundError, json.JSONDecodeError):
            all_cases = []

        recent_cases = all_cases[-20:] if len(all_cases) > 20 else all_cases

        prompt = self._build_prompt(patterns, recent_cases)

        try:
            response_text = self.llm._call(prompt, max_tokens=8192)
        except Exception as e:
            logger.error("Distillation LLM call failed: %s", e)
            return {"success": False, "error": str(e)}

        report = self._parse_response(response_text)
        if not report:
            return {"success": False, "error": "LLM 返回了无法解析的内容"}

        report["success"] = True
        report["pattern_count_before"] = len(patterns)
        report["case_count_reviewed"] = len(recent_cases)
        return report

    def apply_distillation(self, report: dict) -> dict:
        """Apply a reviewed distillation report. Returns summary."""
        if not report.get("success"):
            return {"success": False, "error": "无效的蒸馏报告"}

        # Backup before any changes
        backup_path = self.kb.backup_knowledge("before_distill")

        # cases_path reserved for future case-level distillation
        patterns_path = os.path.join(self.kb.knowledge_dir, "patterns.json")

        with open(patterns_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        patterns = {p["id"]: p for p in data.get("patterns", [])}

        summary = {"merged": 0, "refined": 0, "new": 0, "adjusted": 0, "suppressed": 0, "protected": 0}

        # 1. Merge groups (skip if any builtin pattern involved)
        for group in report.get("merge_groups", []):
            ids = group.get("pattern_ids", [])
            merged_data = group.get("merged_pattern", {})
            if not ids or not merged_data:
                continue

            # Protect builtin patterns from merging
            involved = [(pid, patterns[pid]) for pid in ids if pid in patterns]
            builtin_ids = {pid for pid, p in involved if p.get("source") == "builtin"}
            non_builtin = [(pid, p) for pid, p in involved if pid not in builtin_ids]

            if builtin_ids:
                summary["protected"] += len(builtin_ids)
                # If there are non-builtin patterns left, merge them among themselves
                if len(non_builtin) < 2:
                    continue
                involved = non_builtin

            # Find survivor (highest hit_count)
            survivors = involved
            if not survivors:
                continue
            survivors.sort(key=lambda x: x[1].get("hit_count", 0), reverse=True)
            survivor_id, survivor = survivors[0]

            # Merge stats
            total_hits = sum(p.get("hit_count", 0) for _, p in survivors)
            # Parse timestamps to datetime for correct comparison
            parsed_timestamps = []
            for _, p in survivors:
                ts = p.get("last_hit_at", "")
                if ts:
                    try:
                        parsed_timestamps.append(datetime.fromisoformat(ts))
                    except (ValueError, TypeError):
                        pass
            latest_hit = (
                max(parsed_timestamps).isoformat()
                if parsed_timestamps
                else survivor.get("last_hit_at", "")
            )

            survivor["name"] = merged_data.get("name", survivor["name"])
            survivor["conditions"] = merged_data.get("conditions", survivor["conditions"])
            survivor["solution"] = merged_data.get("solution", survivor["solution"])
            survivor["hit_count"] = total_hits
            survivor["last_hit_at"] = latest_hit
            survivor["miss_streak"] = 0
            self.kb._update_pattern_status(survivor)

            # Remove merged patterns
            for pid, _ in survivors:
                if pid != survivor_id:
                    patterns.pop(pid, None)

            summary["merged"] += 1

        # 2. Refinements
        for ref in report.get("refinements", []):
            pid = ref.get("pattern_id")
            if pid not in patterns:
                continue
            changes = ref.get("changes", {})
            if changes.get("conditions"):
                patterns[pid]["conditions"] = changes["conditions"]
            if changes.get("solution"):
                patterns[pid]["solution"] = changes["solution"]
            patterns[pid]["miss_streak"] = 0
            self.kb._update_pattern_status(patterns[pid])
            summary["refined"] += 1

        # 3. New patterns
        for np in report.get("new_patterns", []):
            new_id = str(uuid.uuid4())[:8]
            now_iso = datetime.utcnow().isoformat()
            patterns[new_id] = {
                "id": new_id,
                "name": np.get("name", ""),
                "conditions": np.get("conditions", ""),
                "solution": np.get("solution", ""),
                "source": "distillation",
                "confidence": DISTILLATION_CONFIDENCE,
                "hit_count": 0,
                "miss_streak": 0,
                "created_at": now_iso,
                "last_hit_at": now_iso,
                "status": "candidate",
            }
            summary["new"] += 1

        # 4. Confidence adjustments
        for adj in report.get("confidence_adjustments", []):
            pid = adj.get("pattern_id")
            if pid not in patterns:
                continue
            new_conf = adj.get("new_confidence")
            if new_conf is not None:
                patterns[pid]["confidence"] = max(0.0, min(1.0, float(new_conf)))
                self.kb._update_pattern_status(patterns[pid])
                summary["adjusted"] += 1

        # 5. Suppressed patterns (protect builtin patterns from suppression)
        for sp in report.get("suppressed_patterns", []):
            pid = sp.get("pattern_id")
            if pid not in patterns:
                continue
            if patterns[pid].get("source") == "builtin":
                summary["protected"] += 1
                continue
            patterns[pid]["status"] = "suppressed"
            summary["suppressed"] += 1

        # Write back
        new_pattern_list = list(patterns.values())
        self.kb.replace_patterns(new_pattern_list)

        # Log
        self.kb.save_distillation_log({
            "summary": report.get("summary", ""),
            "pattern_count_before": report.get("pattern_count_before", 0),
            "pattern_count_after": len(new_pattern_list),
            "changes": summary,
            "backup_path": backup_path,
        })

        return {"success": True, "changes": summary, "backup_path": backup_path}

    def undo_distillation(self) -> bool:
        """Restore from the most recent backup."""
        backup_path = self.kb.get_latest_backup_path()
        if not backup_path:
            return False
        return self.kb.restore_from_backup(backup_path)

    def _build_prompt(self, patterns: list[dict], cases: list[dict]) -> str:
        """Build the distillation prompt for LLM."""
        lines = []
        lines.append("你正在进行知识库蒸馏（Knowledge Distillation）。")
        lines.append("请审查以下 Oracle AWR 诊断模式库和历史案例，完成以下任务：")
        lines.append("")
        lines.append("1. 合并重复/相似的模式（名称或条件含义相近的）")
        lines.append("2. 精炼过于模糊的模式，补充具体的指标阈值和判断条件")
        lines.append("3. 从案例中发现尚未被捕获的新诊断模式")
        lines.append("4. 基于案例证据，对模式的置信度提出调整建议")
        lines.append("5. 指出应当被淘汰的低质量模式（过于通用、已被其他覆盖等）")
        lines.append("")
        lines.append("【重要规则】")
        lines.append("- source 为 \"builtin\" 的模式是专家预置的核心知识，**不允许合并或淘汰**，只允许精炼其条件描述")
        lines.append("- 蒸馏应侧重处理 source 为 \"llm\" 的低质量模式（status=rejected/stale）")
        lines.append("")

        # Patterns
        lines.append(f"【当前诊断模式库】（共 {len(patterns)} 个）")
        for p in patterns:
            status = p.get("status", "?")
            conf = p.get("confidence", 0)
            hits = p.get("hit_count", 0)
            source = p.get("source", "unknown")
            lines.append(
                f'- ID={p.get("id", "")} | {p.get("name", "")} | '
                f'来源={source} | 状态={status} | 置信度={conf:.2f} | 命中={hits}'
            )
            lines.append(f'  条件: {p.get("conditions", "无")}')
            lines.append(f'  方案: {p.get("solution", "无")}')
        lines.append("")

        # Cases
        lines.append(f"【近期诊断案例】（最近 {len(cases)} 个）")
        for c in cases:
            lines.append(
                f'- {c.get("created_at", "")[:10]} | '
                f'严重级别={c.get("severity", "")} | '
                f'主要瓶颈={c.get("main_bottleneck", "")}'
            )
            metrics = c.get("key_metrics", {})
            if metrics:
                lines.append(
                    f'  指标: AAS={metrics.get("aas", "N/A")}, '
                    f'CPU%={metrics.get("db_cpu_pct", "N/A")}'
                )
            summary = c.get("llm_summary", "")
            if summary:
                lines.append(f'  摘要: {summary[:300]}')
        lines.append("")

        # Output format
        lines.append("请以下面的 JSON 格式输出蒸馏结果（不要用 ``` 包裹，直接输出 JSON）：")
        lines.append(json.dumps({
            "merge_groups": [
                {
                    "pattern_ids": ["被合并模式的ID列表"],
                    "merged_pattern": {
                        "name": "合并后的模式名",
                        "conditions": "精确的触发条件，包含具体数值阈值",
                        "solution": "具体的解决方案"
                    },
                    "reason": "合并理由"
                }
            ],
            "refinements": [
                {
                    "pattern_id": "模式ID",
                    "changes": {
                        "conditions": "更精确的条件描述",
                        "solution": "更具体的解决方案"
                    },
                    "reason": "精炼理由"
                }
            ],
            "new_patterns": [
                {
                    "name": "新发现的模式名",
                    "conditions": "触发条件",
                    "solution": "解决方案",
                    "evidence": "从哪些案例中推断出此模式"
                }
            ],
            "confidence_adjustments": [
                {
                    "pattern_id": "模式ID",
                    "new_confidence": 0.7,
                    "reason": "调整理由"
                }
            ],
            "suppressed_patterns": [
                {
                    "pattern_id": "模式ID",
                    "reason": "淘汰理由"
                }
            ],
            "summary": "本次蒸馏的整体总结"
        }, ensure_ascii=False, indent=2))

        return "\n".join(lines)

    def _parse_response(self, text: str) -> dict | None:
        """Parse LLM distillation response with fallback."""
        if not text:
            return None

        # Tier 1: direct JSON
        try:
            result = json.loads(text)
            if isinstance(result, dict) and "summary" in result:
                return result
        except (json.JSONDecodeError, TypeError):
            pass

        # Tier 2: code block — use bracket matching for nested JSON
        code_block_match = re.search(r"```(?:json)?\s*", text)
        if code_block_match:
            block_start = code_block_match.end()
            json_str = self._extract_balanced_json(text[block_start:])
            if json_str:
                try:
                    result = json.loads(json_str)
                    if isinstance(result, dict):
                        return result
                except (json.JSONDecodeError, TypeError):
                    pass

        # Tier 3: first { to last } (with configurable size limit)
        max_json_size = int(os.environ.get("MAX_DISTILL_JSON_SIZE", 500_000))
        first = text.find("{")
        last = text.rfind("}")
        if first != -1 and last > first and (last - first) < max_json_size:
            try:
                result = json.loads(text[first:last + 1])
                if isinstance(result, dict):
                    return result
            except (json.JSONDecodeError, TypeError):
                pass

        return None

    @staticmethod
    def _extract_balanced_json(text: str) -> str | None:
        """Extract a balanced JSON object from text using bracket matching."""
        first = text.find("{")
        if first == -1:
            return None
        depth = 0
        in_string = False
        escape = False
        for i, c in enumerate(text[first:], first):
            if escape:
                escape = False
                continue
            if c == "\\":
                if in_string:
                    escape = True
                continue
            if c == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return text[first:i + 1]
        return None
