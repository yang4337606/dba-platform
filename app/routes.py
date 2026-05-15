import io
import json
import logging

from flask import Blueprint, flash, jsonify, redirect, render_template, request, send_file, url_for

from app.core.registry import get_analyzer, list_analyzers
from app.core.renderer import render_markdown
from app.knowledge import KnowledgeBase
from app.models import db
from app.rag import get_retriever
from app.advisor import advisor

logger = logging.getLogger(__name__)


bp = Blueprint("main", __name__)
kb = KnowledgeBase()


@bp.route("/", methods=["GET"])
def index():
    return render_template("upload.html", analyzers=list_analyzers())


@bp.route("/analyze", methods=["POST"])
def analyze():
    analyzer_type = request.form.get("analyzer_type")
    file = request.files.get("file")

    if not analyzer_type:
        flash("请选择分析类型")
        return redirect(url_for("main.index"))

    if not file or not file.filename:
        flash("请上传文件")
        return redirect(url_for("main.index"))

    # Validate file extension
    import os
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".html", ".htm", ".txt"):
        flash("仅支持 .html、.htm、.txt 文件")
        return redirect(url_for("main.index"))

    analyzer = get_analyzer(analyzer_type)
    content = file.read()

    # Validate file content is not empty
    if not content:
        flash("文件内容为空")
        return redirect(url_for("main.index"))

    try:
        result = analyzer.analyze(content)
    except NotImplementedError as exc:
        flash(str(exc))
        return redirect(url_for("main.index"))

    markdown = render_markdown(result)

    # LLM enhancement (optional)
    llm_result = None
    learning_feedback = None
    llm_config = kb.load_config()
    if llm_config.get("api_key"):
        try:
            from app.llm import LLMClient
            client = LLMClient(**llm_config)
            active_patterns = kb.get_active_patterns()
            llm_result = client.analyze(result, result.raw_metrics or {}, active_patterns)
            if llm_result and not llm_result.get("error"):
                # Save case and learn patterns
                kb.save_case(result, llm_result)
                learned_pattern_ids = kb.learn_patterns(llm_result.get("learned_patterns", []))

                # 生成学习反馈信息
                learning_feedback = {
                    "new_patterns_count": len([pid for pid in learned_pattern_ids if pid]),
                    "new_patterns": llm_result.get("learned_patterns", []),
                    "total_patterns": len(kb.get_all_patterns()),
                    "active_patterns": len(kb.get_active_patterns()),
                }
        except Exception as exc:
            logger.warning("LLM enhancement failed: %s", exc)

    # 保存到历史记录
    record_id = None
    try:
        record_id = db.save_analysis(
            filename=file.filename,
            analyzer_type=analyzer_type,
            result=result.to_dict() if hasattr(result, 'to_dict') else {},
            llm_result=llm_result if llm_result and not llm_result.get("error") else None,
            markdown=markdown
        )
    except Exception as e:
        logger.warning("Failed to save history: %s", e)

    # 检索相似案例（使用RAG向量检索）
    similar_cases = []
    try:
        result_dict = result.to_dict() if hasattr(result, 'to_dict') else {}
        main_problem = result_dict.get("main_bottleneck", "")
        diagnosis_summary = result_dict.get("summary", "")

        # 组合查询文本
        query_text = f"{main_problem} {diagnosis_summary}"

        if query_text.strip():
            # 使用RAG检索
            retriever = get_retriever(db)
            rag_results = retriever.search(query_text, limit=3, min_similarity=0.1)

            # 增量添加当前记录到索引，避免下次全量重建
            if record_id:
                retriever.add_record({
                    'id': record_id,
                    'main_problem': main_problem,
                    'diagnosis_summary': diagnosis_summary,
                    'load_type': result_dict.get("diagnosis", {}).get("load_type", ""),
                    'filename': file.filename,
                    'analyzer_type': analyzer_type,
                })

            # 转换为相似案例格式
            for item in rag_results:
                record = item['record']
                record['similarity'] = item['similarity']
                similar_cases.append(record)
    except Exception as e:
        logger.warning("Failed to get similar cases: %s", e)

    # 生成智能建议
    smart_recommendations = []
    try:
        smart_recommendations = advisor.generate_recommendations(result, db_identifier=None)
    except Exception as e:
        logger.warning("Failed to generate smart recommendations: %s", e)

    # 获取知识库统计
    kb_stats = kb.get_stats()

    return render_template(
        "result.html",
        result=result,
        markdown=markdown,
        llm_result=llm_result,
        similar_cases=similar_cases,
        smart_recommendations=smart_recommendations,
        learning_feedback=learning_feedback,
        kb_stats=kb_stats,
    )


@bp.route("/export", methods=["POST"])
def export_markdown():
    markdown = request.form.get("markdown", "")
    buffer = io.BytesIO(markdown.encode("utf-8"))

    return send_file(
        buffer,
        as_attachment=True,
        download_name="diagnosis_result.md",
        mimetype="text/markdown",
    )


# === Settings Routes ===

@bp.route("/settings", methods=["GET"])
def settings():
    config = kb.load_config()
    masked_key = ""
    if config.get("api_key"):
        key = config["api_key"]
        masked_key = key[:8] + "****" + key[-4:] if len(key) > 12 else "****"
    return render_template("settings.html", config=config, masked_key=masked_key)


@bp.route("/settings/knowledge", methods=["GET"])
def settings_knowledge():
    stats = kb.get_stats()
    distillation_logs = kb.get_distillation_logs()
    has_backup = kb.get_latest_backup_path() is not None
    suggest_distill = stats["total_patterns"] > 10 and not kb.has_recent_distillation(hours=24)
    builtin_count = sum(1 for p in kb.get_all_patterns() if p.get("source") == "builtin")
    return render_template(
        "settings_knowledge.html", stats=stats,
        distillation_logs=distillation_logs, has_backup=has_backup,
        suggest_distill=suggest_distill, builtin_count=builtin_count,
    )


@bp.route("/settings/io", methods=["GET"])
def settings_io():
    return render_template("settings_io.html")


@bp.route("/settings", methods=["POST"])
def save_settings():
    base_url = request.form.get("base_url", "").strip()
    api_key = request.form.get("api_key", "").strip()
    model = request.form.get("model", "").strip()

    # Don't overwrite with masked key
    if api_key and "****" in api_key:
        api_key = ""

    kb.save_config(base_url, api_key, model)
    flash("LLM 配置已保存")
    return redirect(url_for("main.settings"))


@bp.route("/settings/seed", methods=["POST"])
def seed_knowledge():
    """手动注入专家知识种子"""
    from app.seed_patterns import BUILTIN_PATTERNS
    added = kb.seed_builtin_patterns(BUILTIN_PATTERNS)
    if added:
        flash(f"已注入 {added} 条专家诊断模式")
    else:
        flash("专家模式已存在，无需重复注入")
    return redirect(url_for("main.settings_knowledge"))


@bp.route("/settings/export", methods=["GET"])
def export_knowledge():
    """导出全部知识为 JSON 文件下载"""
    from app.knowledge_io import export_all_knowledge
    knowledge = export_all_knowledge()
    buffer = io.BytesIO(json.dumps(knowledge, ensure_ascii=False, indent=2).encode("utf-8"))
    ts = __import__("datetime").datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"awr_knowledge_{ts}.json",
        mimetype="application/json",
    )


@bp.route("/settings/import", methods=["POST"])
def import_knowledge():
    """从 JSON 文件导入知识"""
    file = request.files.get("knowledge_file")
    if not file or not file.filename:
        flash("请选择知识库 JSON 文件")
        return redirect(url_for("main.settings_io"))

    try:
        content = file.read().decode("utf-8")
        data = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        flash(f"文件解析失败: {e}")
        return redirect(url_for("main.settings_io"))

    # Get selected layers
    layers = request.form.getlist("layers")

    from app.knowledge_io import import_knowledge as do_import
    result = do_import(data, layers=layers or None)

    if result.get("success"):
        parts = []
        for name, detail in result["results"].items():
            if detail.get("status") == "ok":
                parts.append(f"{name}: 导入 {detail.get('imported', 0)} 条")
            elif detail.get("status") == "skipped":
                parts.append(f"{name}: 跳过")
        flash(f"知识导入完成 — {', '.join(parts)}")
    else:
        flash(f"导入失败: {result.get('error')}")

    return redirect(url_for("main.settings_io"))


@bp.route("/api/llm-test", methods=["POST"])
def test_llm():
    config = kb.load_config()
    if not config.get("api_key"):
        return jsonify({"success": False, "error": "API Key 未配置"})

    from app.llm import LLMClient
    client = LLMClient(**config)
    result = client.test_connection()
    return jsonify(result)


@bp.route("/history", methods=["GET"])
def history():
    """历史记录列表"""
    history_records = db.get_all_history(limit=50)
    return render_template("history.html", history=history_records)


@bp.route("/history/<int:record_id>", methods=["GET"])
def view_history(record_id):
    """查看历史记录详情"""
    record = db.get_by_id(record_id)
    if not record:
        flash("记录不存在")
        return redirect(url_for("main.history"))

    # Reconstruct result for template
    raw_result = record.get("raw_result", {})
    if not raw_result:
        # Backward compat: old records with empty raw_result
        raw_result = {
            "title": record.get("filename", ""),
            "severity": "INFO",
            "main_bottleneck": record.get("main_problem", ""),
            "summary": record.get("diagnosis_summary", ""),
            "conclusions": [],
            "abnormal_findings": [],
            "root_causes": [],
            "evidence": {},
            "recommendations": [],
            "root_cause_flows": [],
        }
    llm_result = record.get("llm_result", None)

    # Compute smart recommendations
    smart_recommendations = []
    try:
        # Wrap dict so advisor can call .to_dict()
        class _Result:
            def __init__(self, d):
                self._d = d
            def to_dict(self):
                return self._d
            def __getattr__(self, name):
                return self._d.get(name)
        smart_recommendations = advisor.generate_recommendations(_Result(raw_result), db_identifier=None)
    except Exception:
        pass

    # Build similar_cases from RAG
    similar_cases = []
    try:
        main_problem = record.get("main_problem", "")
        diagnosis_summary = record.get("diagnosis_summary", "")
        query_text = f"{main_problem} {diagnosis_summary}"
        if query_text.strip():
            retriever = get_retriever(db)
            rag_results = retriever.search(query_text, limit=3, min_similarity=0.1)
            for item in rag_results:
                r = item['record']
                r['similarity'] = item['similarity']
                similar_cases.append(r)
    except Exception:
        pass

    return render_template(
        "history_detail.html",
        record=record,
        result=raw_result,
        llm_result=llm_result,
        similar_cases=similar_cases,
        smart_recommendations=smart_recommendations,
        markdown=record.get("markdown_content", ""),
    )


@bp.route("/history/<int:record_id>/delete", methods=["POST"])
def delete_history(record_id):
    """删除历史记录"""
    db.delete_by_id(record_id)
    flash("记录已删除")
    return redirect(url_for("main.history"))


@bp.route("/history/compare", methods=["GET"])
def compare_select():
    """选择两条记录进行对比"""
    history_records = db.get_all_history(limit=100)
    return render_template("compare_select.html", history=history_records)


@bp.route("/history/compare/result", methods=["GET"])
def compare_result():
    """显示对比结果"""
    record1_id = request.args.get("record1", type=int)
    record2_id = request.args.get("record2", type=int)

    if not record1_id or not record2_id:
        flash("请选择两条记录进行对比")
        return redirect(url_for("main.compare_select"))

    if record1_id == record2_id:
        flash("请选择不同的记录进行对比")
        return redirect(url_for("main.compare_select"))

    record1 = db.get_by_id(record1_id)
    record2 = db.get_by_id(record2_id)

    if not record1 or not record2:
        flash("记录不存在")
        return redirect(url_for("main.compare_select"))

    comparison = db.compare_records(record1, record2)

    return render_template(
        "compare_result.html",
        record1=record1,
        record2=record2,
        comparison=comparison
    )


@bp.route("/history/trends", methods=["GET"])
def trends():
    """性能趋势分析"""
    days = request.args.get("days", default=30, type=int)
    analyzer_type = request.args.get("analyzer_type", default=None)

    # 获取趋势数据
    trend_data = db.get_trend_data(days=days, analyzer_type=analyzer_type)

    # 检测异常
    anomalies = {}
    if len(trend_data) >= 3:
        anomalies["db_time"] = db.detect_anomalies(trend_data, "db_time")
        anomalies["aas"] = db.detect_anomalies(trend_data, "aas")
        anomalies["db_cpu_percent"] = db.detect_anomalies(trend_data, "db_cpu_percent")

    # 获取统计信息
    stats = db.get_statistics()

    return render_template(
        "trends.html",
        trend_data=trend_data,
        anomalies=anomalies,
        stats=stats,
        days=days,
        analyzer_type=analyzer_type
    )


# === Distillation Routes ===

@bp.route("/distill", methods=["POST"])
def trigger_distillation():
    """触发知识蒸馏（异步）"""
    config = kb.load_config()
    if not config.get("api_key"):
        return jsonify({"success": False, "error": "请先配置 LLM API Key"})

    from app.task_manager import task_manager
    from app.distillation import DistillationEngine
    from app.llm import LLMClient

    def distill_task():
        client = LLMClient(**config)
        engine = DistillationEngine(kb, client)
        return engine.run_distillation()

    task_id = task_manager.submit(name="知识蒸馏", func=distill_task)
    return jsonify({"success": True, "task_id": task_id})


@bp.route("/distill/status/<task_id>", methods=["GET"])
def distill_status(task_id):
    """轮询蒸馏任务状态"""
    from app.task_manager import task_manager
    task = task_manager.get_task(task_id)
    if not task:
        return jsonify({"success": False, "error": "任务不存在"}), 404
    response = task.to_dict()
    if task.status == "completed" and task.result:
        response["result"] = task.result
    return jsonify(response)


@bp.route("/distill/review/<task_id>", methods=["GET"])
def distill_review(task_id):
    """审查蒸馏结果"""
    from app.task_manager import task_manager
    task = task_manager.get_task(task_id)
    if not task:
        flash("任务不存在")
        return redirect(url_for("main.settings_knowledge"))

    if task.status in ("pending", "running"):
        return render_template("distillation.html", task_id=task_id, status="running")

    if task.status == "failed":
        flash(f"蒸馏失败: {task.error}")
        return redirect(url_for("main.settings_knowledge"))

    report = task.result
    if not report or not report.get("success"):
        flash(f"蒸馏失败: {report.get('error', '未知错误') if report else '无结果'}")
        return redirect(url_for("main.settings_knowledge"))

    # Enrich report with pattern names for display
    all_patterns = {p["id"]: p for p in kb.get_all_patterns()}
    for group in report.get("merge_groups", []):
        group["_originals"] = [all_patterns.get(pid, {}) for pid in group.get("pattern_ids", [])]
    for ref in report.get("refinements", []):
        ref["_original"] = all_patterns.get(ref.get("pattern_id"), {})
    for adj in report.get("confidence_adjustments", []):
        adj["_original"] = all_patterns.get(adj.get("pattern_id"), {})
    for sp in report.get("suppressed_patterns", []):
        sp["_original"] = all_patterns.get(sp.get("pattern_id"), {})

    return render_template("distillation.html", task_id=task_id, status="completed", report=report)


@bp.route("/distill/apply", methods=["POST"])
def distill_apply():
    """应用蒸馏结果"""
    task_id = request.form.get("task_id")
    if not task_id:
        flash("缺少任务 ID")
        return redirect(url_for("main.settings_knowledge"))

    from app.task_manager import task_manager
    from app.distillation import DistillationEngine
    from app.llm import LLMClient

    task = task_manager.get_task(task_id)
    if not task or not task.result or not task.result.get("success"):
        flash("蒸馏结果不可用")
        return redirect(url_for("main.settings_knowledge"))

    config = kb.load_config()
    client = LLMClient(**config)
    engine = DistillationEngine(kb, client)

    try:
        result = engine.apply_distillation(task.result)
    except Exception as e:
        logger.error("Distillation apply failed: %s", e, exc_info=True)
        flash(f"应用失败: {e}")
        return redirect(url_for("main.settings_knowledge"))

    if result.get("success"):
        changes = result["changes"]
        flash(f"蒸馏已应用：合并 {changes['merged']}、精炼 {changes['refined']}、"
              f"新增 {changes['new']}、调整 {changes['adjusted']}、淘汰 {changes['suppressed']}")
    else:
        flash(f"应用失败: {result.get('error')}")

    return redirect(url_for("main.settings_knowledge"))


@bp.route("/distill/undo", methods=["POST"])
def distill_undo():
    """撤销上次蒸馏"""
    from app.distillation import DistillationEngine
    from app.llm import LLMClient

    config = kb.load_config()
    client = LLMClient(**config)
    engine = DistillationEngine(kb, client)

    if engine.undo_distillation():
        flash("已撤销上次蒸馏，模式库已恢复")
    else:
        flash("没有可恢复的备份")

    return redirect(url_for("main.settings_knowledge"))
