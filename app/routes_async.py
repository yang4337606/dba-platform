"""
异步分析路由 - 支持后台任务
"""
import os
import logging

from flask import Blueprint, jsonify, request, render_template, redirect, url_for, flash
from werkzeug.utils import secure_filename

from app.analysis_pipeline import run_analysis
from app.task_manager import task_manager

logger = logging.getLogger(__name__)

bp_async = Blueprint("async", __name__, url_prefix="/async")


def analyze_file_task(file_content, filename, analyzer_type):
    """
    后台分析任务
    即使用户关闭页面，这个任务也会继续执行
    """
    try:
        pipeline_result = run_analysis(file_content, filename, analyzer_type)
        return {
            "success": True,
            "record_id": pipeline_result.get("record_id"),
            "result": (pipeline_result["result"].to_dict()
                       if hasattr(pipeline_result["result"], 'to_dict')
                       else pipeline_result["result"]),
            "markdown": pipeline_result.get("markdown"),
            "llm_result": pipeline_result.get("llm_result"),
            "similar_cases": pipeline_result.get("similar_cases", []),
            "smart_recommendations": pipeline_result.get("smart_recommendations", []),
        }
    except Exception as e:
        logger.error("Analysis task failed: %s", e, exc_info=True)
        return {"success": False, "error": str(e)}


@bp_async.route("/analyze", methods=["POST"])
def analyze_async():
    """异步分析接口"""
    analyzer_type = request.form.get("analyzer_type")
    file = request.files.get("file")

    if not analyzer_type:
        return jsonify({"success": False, "error": "请选择分析类型"}), 400

    if not file or not file.filename:
        return jsonify({"success": False, "error": "请上传文件"}), 400

    safe_name = secure_filename(file.filename)
    if not safe_name:
        return jsonify({"success": False, "error": "文件名不合法"}), 400
    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in (".html", ".htm", ".txt"):
        return jsonify({"success": False, "error": "仅支持 .html、.htm、.txt 文件"}), 400

    file_content = file.read()
    if not file_content:
        return jsonify({"success": False, "error": "文件内容为空"}), 400

    try:
        task_id = task_manager.submit(
            name=f"分析 {safe_name}",
            func=analyze_file_task,
            file_content=file_content,
            filename=safe_name,
            analyzer_type=analyzer_type
        )
    except RuntimeError as e:
        return jsonify({"success": False, "error": str(e)}), 429

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

    if task.status in ("pending", "running"):
        return render_template("task_progress.html", task=task.to_dict())

    if task.status == "failed":
        flash(f"分析失败: {task.error}")
        return redirect(url_for("main.index"))

    if task.result and task.result.get("record_id"):
        return redirect(url_for("main.view_history", record_id=task.result["record_id"]))
    else:
        flash("分析结果不可用")
        return redirect(url_for("main.index"))
