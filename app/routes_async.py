"""
异步分析路由 - 支持后台任务
"""
from flask import Blueprint, jsonify, request, render_template, redirect, url_for, flash

from app.core.registry import get_analyzer
from app.core.renderer import render_markdown
from app.knowledge import KnowledgeBase
from app.models import db
from app.rag import get_retriever
from app.advisor import advisor
from app.task_manager import task_manager
import logging

logger = logging.getLogger(__name__)

bp_async = Blueprint("async", __name__, url_prefix="/async")
kb = KnowledgeBase()


def analyze_file_task(file_content, filename, analyzer_type):
    """
    后台分析任务
    即使用户关闭页面，这个任务也会继续执行
    """
    try:
        # 1. 分析文件
        analyzer = get_analyzer(analyzer_type)
        result = analyzer.analyze(file_content)
        markdown = render_markdown(result)

        # 2. LLM增强（可选）
        llm_result = None
        llm_config = kb.load_config()
        if llm_config.get("api_key"):
            try:
                from app.llm import LLMClient
                client = LLMClient(**llm_config)
                active_patterns = kb.get_active_patterns()
                llm_result = client.analyze(result, result.raw_metrics or {}, active_patterns)
                if llm_result and not llm_result.get("error"):
                    kb.save_case(result, llm_result)
                    kb.learn_patterns(llm_result.get("learned_patterns", []))
            except Exception as exc:
                logger.warning("LLM enhancement failed: %s", exc)

        # 3. 保存到历史记录
        record_id = None
        try:
            record_id = db.save_analysis(
                filename=filename,
                analyzer_type=analyzer_type,
                result=result.to_dict() if hasattr(result, 'to_dict') else {},
                llm_result=llm_result if llm_result and not llm_result.get("error") else None,
                markdown=markdown
            )
        except Exception as e:
            logger.warning("Failed to save history: %s", e)

        # 4. 检索相似案例
        similar_cases = []
        try:
            result_dict = result.to_dict() if hasattr(result, 'to_dict') else {}
            main_problem = result_dict.get("main_bottleneck", "")
            diagnosis_summary = result_dict.get("summary", "")
            query_text = f"{main_problem} {diagnosis_summary}"

            if query_text.strip():
                retriever = get_retriever(db)
                rag_results = retriever.search(query_text, limit=3, min_similarity=0.1)

                # 增量添加当前记录到索引
                if record_id:
                    retriever.add_record({
                        'id': record_id,
                        'main_problem': main_problem,
                        'diagnosis_summary': diagnosis_summary,
                        'load_type': result_dict.get("diagnosis", {}).get("load_type", ""),
                        'filename': filename,
                        'analyzer_type': analyzer_type,
                    })

                for item in rag_results:
                    record = item['record']
                    record['similarity'] = item['similarity']
                    similar_cases.append(record)
        except Exception as e:
            logger.warning("Failed to get similar cases: %s", e)

        # 5. 生成智能建议
        smart_recommendations = []
        try:
            smart_recommendations = advisor.generate_recommendations(result, db_identifier=None)
        except Exception as e:
            logger.warning("Failed to generate smart recommendations: %s", e)

        return {
            "success": True,
            "record_id": record_id,
            "result": result.to_dict() if hasattr(result, 'to_dict') else {},
            "markdown": markdown,
            "llm_result": llm_result,
            "similar_cases": similar_cases,
            "smart_recommendations": smart_recommendations,
        }

    except Exception as e:
        logger.error(f"Analysis task failed: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }


@bp_async.route("/analyze", methods=["POST"])
def analyze_async():
    """异步分析接口"""
    analyzer_type = request.form.get("analyzer_type")
    file = request.files.get("file")

    if not analyzer_type:
        return jsonify({"success": False, "error": "请选择分析类型"}), 400

    if not file or not file.filename:
        return jsonify({"success": False, "error": "请上传文件"}), 400

    # Validate file extension
    import os
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".html", ".htm", ".txt"):
        return jsonify({"success": False, "error": "仅支持 .html、.htm、.txt 文件"}), 400

    # 读取文件内容
    file_content = file.read()
    if not file_content:
        return jsonify({"success": False, "error": "文件内容为空"}), 400
    filename = file.filename

    # 提交后台任务
    task_id = task_manager.submit(
        name=f"分析 {filename}",
        func=analyze_file_task,
        file_content=file_content,
        filename=filename,
        analyzer_type=analyzer_type
    )

    return jsonify({
        "success": True,
        "task_id": task_id,
        "message": "分析任务已提交，即使关闭页面也会继续执行"
    })


@bp_async.route("/task/<task_id>", methods=["GET"])
def get_task_status(task_id):
    """获取任务状态"""
    task = task_manager.get_task(task_id)
    if not task:
        return jsonify({"success": False, "error": "任务不存在"}), 404

    response = task.to_dict()

    # 如果任务完成，添加结果
    if task.status == "completed" and task.result:
        response["result"] = task.result

    return jsonify(response)


@bp_async.route("/tasks", methods=["GET"])
def list_tasks():
    """列出所有任务"""
    tasks = task_manager.get_all_tasks()
    return jsonify({"success": True, "tasks": tasks})


@bp_async.route("/result/<task_id>", methods=["GET"])
def view_result(task_id):
    """查看任务结果"""
    task = task_manager.get_task(task_id)
    if not task:
        flash("任务不存在")
        return redirect(url_for("main.index"))

    if task.status == "pending" or task.status == "running":
        return render_template("task_progress.html", task=task.to_dict())

    if task.status == "failed":
        flash(f"分析失败: {task.error}")
        return redirect(url_for("main.index"))

    # 任务完成，显示结果
    if task.result and task.result.get("record_id"):
        # 重定向到历史记录详情页
        return redirect(url_for("main.view_history", record_id=task.result["record_id"]))
    else:
        flash("分析结果不可用")
        return redirect(url_for("main.index"))
