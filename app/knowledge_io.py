"""
知识导出/导入模块

将平台所有知识层导出为结构化 JSON，方便交给其他 AI 优化后再导入。
"""
from __future__ import annotations

import json
import os
import yaml
from datetime import datetime

KNOWLEDGE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "knowledge")


def export_all_knowledge() -> dict:
    """Export all knowledge layers to a single dict."""
    base = os.path.dirname(os.path.dirname(__file__))

    knowledge = {
        "_meta": {
            "exported_at": datetime.utcnow().isoformat(),
            "version": "1.0",
            "description": "Oracle AWR 诊断平台知识库完整导出",
        },
        "layers": {}
    }

    # Layer 1: Patterns
    patterns_path = os.path.join(KNOWLEDGE_DIR, "patterns.json")
    try:
        with open(patterns_path, "r", encoding="utf-8") as f:
            patterns_data = json.load(f)
        knowledge["layers"]["patterns"] = {
            "description": "诊断模式库 — 含 builtin 预置模式和 LLM 学习模式",
            "count": len(patterns_data.get("patterns", [])),
            "data": patterns_data.get("patterns", []),
            "schema": {
                "id": "唯一标识",
                "name": "模式名称",
                "conditions": "触发条件（含具体指标阈值）",
                "solution": "解决方案",
                "source": "来源（builtin/llm/distillation）",
                "confidence": "置信度 0-1",
                "status": "状态（active/observed/candidate/rejected/stale/suppressed）",
            }
        }
    except (FileNotFoundError, json.JSONDecodeError):
        knowledge["layers"]["patterns"] = {"description": "诊断模式库", "count": 0, "data": []}

    # Layer 2: Rules (from YAML)
    rules_path = os.path.join(base, "app", "analyzers", "oracle_awr", "rules.yaml")
    try:
        with open(rules_path, "r", encoding="utf-8") as f:
            rules_data = yaml.safe_load(f) or []
        knowledge["layers"]["rules"] = {
            "description": "规则引擎规则 — 基于指标阈值的自动检测规则",
            "count": len(rules_data),
            "data": rules_data,
            "schema": {
                "id": "规则标识",
                "category": "分类（CPU/IO/Redo/Parse/TEMP/RAC等）",
                "severity": "严重级别（HIGH/WARNING/OBSERVE）",
                "metric": "关联指标名",
                "condition": "触发条件（metric + op + value）",
                "finding": "发现描述",
                "description": "详细说明",
                "reason": "原因分析",
                "recommendation": "建议操作",
            }
        }
    except (FileNotFoundError, yaml.YAMLError):
        knowledge["layers"]["rules"] = {"description": "规则引擎规则", "count": 0, "data": []}

    # Layer 3: Event Semantics
    event_sem_path = os.path.join(base, "app", "analyzers", "oracle_awr", "event_semantics.py")
    try:
        from app.analyzers.oracle_awr.event_semantics import EVENT_SEMANTICS, SEMANTIC_DISPLAY_NAMES
        event_groups = []
        for key, patterns in EVENT_SEMANTICS.items():
            event_groups.append({
                "key": key,
                "display_name": SEMANTIC_DISPLAY_NAMES.get(key, key),
                "event_patterns": patterns,
            })
        knowledge["layers"]["event_semantics"] = {
            "description": "等待事件语义分类 — 将 Oracle 等待事件归类到问题域",
            "count": len(event_groups),
            "data": event_groups,
            "schema": {
                "key": "语义组标识",
                "display_name": "显示名称",
                "event_patterns": "匹配的等待事件关键词列表",
            }
        }
    except ImportError:
        knowledge["layers"]["event_semantics"] = {"description": "事件语义分类", "count": 0, "data": []}

    # Layer 4: Cases
    cases_path = os.path.join(KNOWLEDGE_DIR, "cases.json")
    try:
        with open(cases_path, "r", encoding="utf-8") as f:
            cases_data = json.load(f)
        knowledge["layers"]["cases"] = {
            "description": "历史诊断案例 — 用于 RAG 检索和蒸馏参考",
            "count": len(cases_data.get("cases", [])),
            "data": cases_data.get("cases", []),
        }
    except (FileNotFoundError, json.JSONDecodeError):
        knowledge["layers"]["cases"] = {"description": "历史案例", "count": 0, "data": []}

    # Layer 5: LLM Prompt
    knowledge["layers"]["llm_prompt"] = {
        "description": "LLM 系统提示词 — 定义 AI 分析专家人设和方法论",
        "count": 1,
        "data": {
            "system_prompt": _get_system_prompt(),
            "output_format": "JSON with keys: expert_analysis, key_findings, sql_recommendations, parameter_suggestions, learned_patterns",
        },
    }

    return knowledge


def import_knowledge(data: dict, layers: list[str] | None = None) -> dict:
    """Import knowledge from exported dict. Returns summary of what was imported."""
    if not isinstance(data, dict) or "layers" not in data:
        return {"success": False, "error": "无效的知识库格式，缺少 layers 字段"}

    results = {}
    target_layers = layers or list(data["layers"].keys())

    for layer_name in target_layers:
        layer = data["layers"].get(layer_name)
        if not layer:
            results[layer_name] = {"status": "skipped", "reason": "不存在"}
            continue

        layer_data = layer.get("data", [])

        if layer_name == "patterns":
            results[layer_name] = _import_patterns(layer_data)
        elif layer_name == "rules":
            results[layer_name] = _import_rules(layer_data)
        elif layer_name == "event_semantics":
            results[layer_name] = _import_event_semantics(layer_data)
        else:
            results[layer_name] = {"status": "skipped", "reason": "该层不支持导入"}

    return {"success": True, "results": results}


def _import_patterns(patterns_data: list) -> dict:
    """Import patterns into patterns.json."""
    if not isinstance(patterns_data, list):
        return {"status": "error", "reason": "patterns 数据格式错误"}

    patterns_path = os.path.join(KNOWLEDGE_DIR, "patterns.json")
    try:
        with open(patterns_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        existing = {"patterns": []}

    existing_names = {p["name"] for p in existing.get("patterns", [])}
    imported = 0
    skipped = 0

    for p in patterns_data:
        if not isinstance(p, dict) or not p.get("name"):
            continue
        if p["name"] in existing_names:
            skipped += 1
            continue
        existing["patterns"].append(p)
        existing_names.add(p["name"])
        imported += 1

    # Atomic write
    tmp_path = patterns_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, patterns_path)

    return {"status": "ok", "imported": imported, "skipped": skipped}


def _import_rules(rules_data: list) -> dict:
    """Import rules into rules.yaml."""
    if not isinstance(rules_data, list):
        return {"status": "error", "reason": "rules 数据格式错误"}

    base = os.path.dirname(os.path.dirname(__file__))
    rules_path = os.path.join(base, "app", "analyzers", "oracle_awr", "rules.yaml")

    # Backup existing
    backup_path = rules_path + ".bak"
    if os.path.exists(rules_path):
        import shutil
        shutil.copy2(rules_path, backup_path)

    with open(rules_path, "w", encoding="utf-8") as f:
        yaml.dump(rules_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    return {"status": "ok", "imported": len(rules_data)}


def _import_event_semantics(events_data: list) -> dict:
    """Import event semantics — generates Python source code."""
    if not isinstance(events_data, list):
        return {"status": "error", "reason": "event_semantics 数据格式错误"}

    base = os.path.dirname(os.path.dirname(__file__))
    sem_path = os.path.join(base, "app", "analyzers", "oracle_awr", "event_semantics.py")

    # Backup existing
    backup_path = sem_path + ".bak"
    if os.path.exists(sem_path):
        import shutil
        shutil.copy2(sem_path, backup_path)

    # Build the new Python source
    event_dict = {}
    display_dict = {}
    for group in events_data:
        key = group.get("key", "")
        if not key:
            continue
        event_dict[key] = group.get("event_patterns", [])
        display_dict[key] = group.get("display_name", key)

    lines = [
        "EVENT_SEMANTICS = {",
    ]
    for key, patterns in event_dict.items():
        lines.append(f'    "{key}": [')
        for p in patterns:
            lines.append(f'        "{p}",')
        lines.append("    ],")
    lines.append("}")
    lines.append("")
    lines.append("")
    lines.append("SEMANTIC_DISPLAY_NAMES = {")
    for key, display in display_dict.items():
        lines.append(f'    "{key}": "{display}",')
    lines.append("}")

    # Append the functions from the original file
    lines.append("""
\n\ndef classify_event_semantics(events):
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
                break

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
""")

    with open(sem_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return {"status": "ok", "imported": len(events_data)}


def _get_system_prompt() -> str:
    """Extract the current system prompt from LLM client."""
    try:
        import inspect
        from app.llm import LLMClient
        src = inspect.getsource(LLMClient._call)
        # Extract the system prompt string
        start = src.find('"content": (')
        if start == -1:
            return "（无法提取）"
        end = src.find(')', start + 12)
        prompt_section = src[start + 12:end]
        # Clean up the Python string concatenation
        lines = []
        for line in prompt_section.split("\\n"):
            line = line.strip().strip('"').strip("'+")
            if line:
                lines.append(line)
        return "\n".join(lines)
    except Exception:
        return "（无法提取）"
