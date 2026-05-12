import os
import json
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from .models import db, AWRReport, AWRAnalysis, KnowledgeBase, AuditLog, SystemSetting
from .awr_engine import AWRParser, AWRAnalyzer, LLMIntegration

awr_bp = Blueprint('awr', __name__, url_prefix='/awr')


def _allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ('html', 'htm', 'txt')


@awr_bp.route('/')
@login_required
def list_reports():
    page = request.args.get('page', 1, type=int)
    query = AWRReport.query
    if current_user.role == 'viewer':
        query = query.filter_by(upload_user_id=current_user.id)
    reports = query.order_by(AWRReport.created_at.desc()).paginate(page=page, per_page=15)
    return render_template('awr/list.html', reports=reports)


@awr_bp.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('请选择文件', 'error')
            return redirect(request.url)

        file = request.files['file']
        if file.filename == '':
            flash('未选择文件', 'error')
            return redirect(request.url)

        if not _allowed_file(file.filename):
            flash('仅支持 HTML/HTM/TXT 格式的AWR报告', 'error')
            return redirect(request.url)

        filename = secure_filename(file.filename)
        timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
        safe_name = f"{timestamp}_{filename}"
        filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], safe_name)
        file.save(filepath)
        file_size = os.path.getsize(filepath)

        # Parse the AWR report
        parser = AWRParser()
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                html_content = f.read()
            parsed = parser.parse(html_content)
            db_info = parsed.get('db_info', {})
            snap_info = parsed.get('snap_info', {})

            report = AWRReport(
                title=request.form.get('title', filename),
                filename=filename,
                file_path=filepath,
                file_size=file_size,
                db_name=db_info.get('db_name', ''),
                instance_name=db_info.get('instance_name', ''),
                snap_begin=snap_info.get('begin_id', ''),
                snap_end=snap_info.get('end_id', ''),
                snap_duration=snap_info.get('duration', ''),
                db_version=db_info.get('db_version', ''),
                host_name=db_info.get('host_name', ''),
                platform=db_info.get('platform', ''),
                raw_metrics=json.dumps(parsed, ensure_ascii=False),
                parsed_sections=json.dumps(list(parsed.keys()), ensure_ascii=False),
                upload_user_id=current_user.id,
                status='parsed',
            )
            db.session.add(report)
            db.session.add(AuditLog(user_id=current_user.id, action='upload_awr',
                                    detail=filename, ip_address=request.remote_addr))
            db.session.commit()
            flash('AWR报告上传并解析成功', 'success')
            return redirect(url_for('awr.view_report', report_id=report.id))

        except Exception as e:
            report = AWRReport(
                title=request.form.get('title', filename),
                filename=filename, file_path=filepath, file_size=file_size,
                upload_user_id=current_user.id, status='error',
                raw_metrics=json.dumps({'error': str(e)}, ensure_ascii=False),
            )
            db.session.add(report)
            db.session.commit()
            flash(f'AWR报告解析出错: {str(e)}', 'error')
            return redirect(url_for('awr.list_reports'))

    return render_template('awr/upload.html')


@awr_bp.route('/<int:report_id>')
@login_required
def view_report(report_id):
    report = AWRReport.query.get_or_404(report_id)
    if current_user.role == 'viewer' and report.upload_user_id != current_user.id:
        flash('无权查看此报告', 'error')
        return redirect(url_for('awr.list_reports'))

    parsed = json.loads(report.raw_metrics) if report.raw_metrics else {}
    analyses = report.analyses.order_by(AWRAnalysis.created_at.desc()).all()
    return render_template('awr/view.html', report=report, parsed=parsed, analyses=analyses)


@awr_bp.route('/<int:report_id>/analyze', methods=['POST'])
@login_required
def analyze_report(report_id):
    if not current_user.can_analyze:
        flash('无分析权限', 'error')
        return redirect(url_for('awr.view_report', report_id=report_id))

    report = AWRReport.query.get_or_404(report_id)
    parsed = json.loads(report.raw_metrics) if report.raw_metrics else {}

    # Fetch knowledge base entries
    kb_entries = KnowledgeBase.query.filter_by(is_active=True).all()
    kb_list = [{'category': k.category, 'title': k.title, 'pattern': k.pattern,
                'description': k.description, 'solution': k.solution,
                'severity': k.severity, 'source': k.source} for k in kb_entries]

    analyzer = AWRAnalyzer()
    result = analyzer.analyze(parsed, kb_list)

    # LLM enhancement if configured
    use_llm = request.form.get('use_llm') == 'on'
    llm_result = None
    if use_llm:
        llm_provider = SystemSetting.get('llm_provider', 'none')
        llm_key = SystemSetting.get('llm_api_key', '')
        llm_url = SystemSetting.get('llm_api_url', '')
        llm_model = SystemSetting.get('llm_model', '')
        if llm_provider != 'none' and llm_key:
            llm = LLMIntegration(llm_provider, llm_key, llm_url, llm_model)
            llm_result = llm.enhance_analysis(parsed, result)

    analysis = AWRAnalysis(
        report_id=report.id,
        analysis_type='llm' if llm_result else 'auto',
        summary=result.get('summary', ''),
        performance_score=result.get('performance_score', 0),
        wait_events_analysis=result.get('wait_events_analysis', ''),
        sql_analysis=result.get('sql_analysis', ''),
        io_analysis=result.get('io_analysis', ''),
        memory_analysis=result.get('memory_analysis', ''),
        recommendations=result.get('recommendations', ''),
        llm_provider=SystemSetting.get('llm_provider') if llm_result else None,
        llm_analysis=llm_result,
        analyst_id=current_user.id,
    )
    db.session.add(analysis)
    report.status = 'analyzed'

    # Self-learning: extract new patterns
    new_patterns = analyzer.learn_from_analysis(parsed, result)
    for p in new_patterns:
        existing = KnowledgeBase.query.filter_by(title=p['title']).first()
        if not existing:
            entry = KnowledgeBase(**p)
            db.session.add(entry)
        else:
            existing.match_count += 1
            existing.confidence = min(1.0, existing.confidence + 0.05)

    # Update match counts for matched KB entries
    for kb in kb_entries:
        if kb.pattern:
            for evt in parsed.get('top_events', []):
                evt_text = ' '.join(str(v) for v in evt.values()).lower()
                import re
                if re.search(kb.pattern, evt_text, re.IGNORECASE):
                    kb.match_count += 1
                    kb.confidence = min(1.0, kb.confidence + 0.02)
                    break

    db.session.add(AuditLog(user_id=current_user.id, action='analyze_awr',
                            detail=f'Report #{report.id}', ip_address=request.remote_addr))
    db.session.commit()
    flash('分析完成', 'success')
    return redirect(url_for('awr.view_analysis', report_id=report.id, analysis_id=analysis.id))


@awr_bp.route('/<int:report_id>/analysis/<int:analysis_id>')
@login_required
def view_analysis(report_id, analysis_id):
    report = AWRReport.query.get_or_404(report_id)
    analysis = AWRAnalysis.query.get_or_404(analysis_id)
    if current_user.role == 'viewer' and report.upload_user_id != current_user.id:
        flash('无权查看', 'error')
        return redirect(url_for('awr.list_reports'))

    # Parse JSON fields for template
    summary = json.loads(analysis.summary) if analysis.summary else {}
    wait_events = json.loads(analysis.wait_events_analysis) if analysis.wait_events_analysis else []
    sql_data = json.loads(analysis.sql_analysis) if analysis.sql_analysis else []
    io_data = json.loads(analysis.io_analysis) if analysis.io_analysis else []
    memory_data = json.loads(analysis.memory_analysis) if analysis.memory_analysis else {}
    recommendations = json.loads(analysis.recommendations) if analysis.recommendations else []

    return render_template('awr/analysis.html', report=report, analysis=analysis,
                           summary=summary, wait_events=wait_events, sql_data=sql_data,
                           io_data=io_data, memory_data=memory_data, recommendations=recommendations)


@awr_bp.route('/<int:report_id>/delete', methods=['POST'])
@login_required
def delete_report(report_id):
    if not current_user.is_admin:
        flash('仅管理员可删除', 'error')
        return redirect(url_for('awr.list_reports'))

    report = AWRReport.query.get_or_404(report_id)
    if os.path.exists(report.file_path):
        os.remove(report.file_path)
    db.session.delete(report)
    db.session.add(AuditLog(user_id=current_user.id, action='delete_awr',
                            detail=report.title, ip_address=request.remote_addr))
    db.session.commit()
    flash('报告已删除', 'success')
    return redirect(url_for('awr.list_reports'))
