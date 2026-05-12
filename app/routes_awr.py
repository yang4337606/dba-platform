import os
import json
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from .models import db, AWRReport, AWRMetric, AWRProblem, AWRAnalysisResult, KnowledgeRule, AuditLog, SystemSetting
from .awr_engine import AWRParser, MetricScorer, CorrelationAnalyzer, BaselineComparer, LLMIntegration, LearningEngine

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

        # Read file content
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                html_content = f.read()
        except Exception as e:
            flash(f'文件读取失败: {str(e)}', 'error')
            return redirect(request.url)

        # Parse the AWR report
        parser = AWRParser()
        try:
            parsed = parser.parse(html_content)
            db_info = parsed.get('db_info', {})
            snap_info = parsed.get('snap_info', {})

            # Create AWRReport record
            report = AWRReport(
                title=request.form.get('title') or filename,
                filename=filename,
                file_path=filepath,
                file_size=file_size,
                db_name=db_info.get('db_name', ''),
                instance_name=db_info.get('instance_name', ''),
                db_version=db_info.get('db_version', ''),
                host_name=db_info.get('host_name', ''),
                platform=db_info.get('platform', ''),
                snap_begin_id=snap_info.get('begin_id'),
                snap_end_id=snap_info.get('end_id'),
                snap_begin_time=snap_info.get('begin_time'),
                snap_end_time=snap_info.get('end_time'),
                elapsed_seconds=snap_info.get('elapsed_seconds'),
                raw_html=html_content,
                upload_user_id=current_user.id,
                status='parsed',
            )
            db.session.add(report)
            db.session.flush()  # Get report.id for metric foreign keys

            # Store parsed metrics into AWRMetric table
            _store_metrics(report.id, parsed)

            db.session.add(AuditLog(user_id=current_user.id, action='upload_awr',
                                    detail=filename, ip_address=request.remote_addr))
            db.session.commit()
            flash('AWR报告上传并解析成功', 'success')
            return redirect(url_for('awr.view_report', report_id=report.id))

        except Exception as e:
            db.session.rollback()
            report = AWRReport(
                title=request.form.get('title') or filename,
                filename=filename,
                file_path=filepath,
                file_size=file_size,
                upload_user_id=current_user.id,
                status='error',
            )
            db.session.add(report)
            db.session.commit()
            flash(f'AWR报告解析出错: {str(e)}', 'error')
            return redirect(url_for('awr.list_reports'))

    return render_template('awr/upload.html')


def _store_metrics(report_id, parsed):
    """Store all parsed sections as AWRMetric records."""

    # load_profile section
    load_profile = parsed.get('load_profile', {})
    if isinstance(load_profile, list):
        for row in load_profile:
            metric = AWRMetric(
                report_id=report_id,
                metric_type='load_profile',
                metric_name=row.get('name', row.get('metric', '')),
                metric_value=row.get('per_second') or row.get('value'),
                metric_unit=row.get('unit', 'per sec'),
                extra_json=json.dumps(row, ensure_ascii=False),
            )
            db.session.add(metric)
    elif isinstance(load_profile, dict):
        for key, value in load_profile.items():
            metric_value = None
            if isinstance(value, (int, float)):
                metric_value = float(value)
            metric = AWRMetric(
                report_id=report_id,
                metric_type='load_profile',
                metric_name=key,
                metric_value=metric_value,
                metric_unit='per sec',
                extra_json=json.dumps({'name': key, 'value': value}, ensure_ascii=False),
            )
            db.session.add(metric)

    # top_events section
    top_events = parsed.get('top_events', [])
    for idx, event in enumerate(top_events):
        pct_db_time = event.get('pct_db_time') or event.get('pct', 0)
        avg_wait = event.get('avg_wait') or event.get('avg_wait_ms')
        metric = AWRMetric(
            report_id=report_id,
            metric_type='wait_event',
            metric_name=event.get('name', event.get('event', '')),
            metric_value=float(pct_db_time) if pct_db_time is not None else None,
            metric_unit='%DB Time',
            rank_order=idx + 1,
            extra_json=json.dumps({'avg_wait': avg_wait, **event}, ensure_ascii=False),
        )
        db.session.add(metric)

    # top_sql section
    top_sql = parsed.get('top_sql', [])
    for idx, sql_entry in enumerate(top_sql):
        metric = AWRMetric(
            report_id=report_id,
            metric_type='sql_stat',
            metric_name=sql_entry.get('sql_id', f'sql_rank_{idx + 1}'),
            metric_value=sql_entry.get('elapsed_time') or sql_entry.get('cpu_time') or sql_entry.get('buffer_gets'),
            metric_text=sql_entry.get('sql_text', ''),
            rank_order=idx + 1,
            extra_json=json.dumps(sql_entry, ensure_ascii=False),
        )
        db.session.add(metric)

    # io_stats section
    io_stats = parsed.get('io_stats', [])
    if isinstance(io_stats, list):
        for row in io_stats:
            metric = AWRMetric(
                report_id=report_id,
                metric_type='io_stat',
                metric_name=row.get('name', row.get('tablespace', row.get('function', ''))),
                metric_value=row.get('reads') or row.get('value'),
                extra_json=json.dumps(row, ensure_ascii=False),
            )
            db.session.add(metric)
    elif isinstance(io_stats, dict):
        for key, value in io_stats.items():
            metric = AWRMetric(
                report_id=report_id,
                metric_type='io_stat',
                metric_name=key,
                metric_value=float(value) if isinstance(value, (int, float)) else None,
                extra_json=json.dumps({'name': key, 'value': value}, ensure_ascii=False),
            )
            db.session.add(metric)

    # memory_stats section
    memory_stats = parsed.get('memory_stats', {})
    if isinstance(memory_stats, list):
        for row in memory_stats:
            metric = AWRMetric(
                report_id=report_id,
                metric_type='memory',
                metric_name=row.get('name', row.get('component', '')),
                metric_value=row.get('size') or row.get('value'),
                metric_unit=row.get('unit', 'MB'),
                extra_json=json.dumps(row, ensure_ascii=False),
            )
            db.session.add(metric)
    elif isinstance(memory_stats, dict):
        for key, value in memory_stats.items():
            metric = AWRMetric(
                report_id=report_id,
                metric_type='memory',
                metric_name=key,
                metric_value=float(value) if isinstance(value, (int, float)) else None,
                metric_unit='MB',
                extra_json=json.dumps({'name': key, 'value': value}, ensure_ascii=False),
            )
            db.session.add(metric)

    # instance_efficiency section
    instance_efficiency = parsed.get('instance_efficiency', {})
    if isinstance(instance_efficiency, list):
        for row in instance_efficiency:
            metric = AWRMetric(
                report_id=report_id,
                metric_type='efficiency',
                metric_name=row.get('name', row.get('metric', '')),
                metric_value=row.get('value') or row.get('pct'),
                metric_unit='%',
                extra_json=json.dumps(row, ensure_ascii=False),
            )
            db.session.add(metric)
    elif isinstance(instance_efficiency, dict):
        for key, value in instance_efficiency.items():
            metric = AWRMetric(
                report_id=report_id,
                metric_type='efficiency',
                metric_name=key,
                metric_value=float(value) if isinstance(value, (int, float)) else None,
                metric_unit='%',
                extra_json=json.dumps({'name': key, 'value': value}, ensure_ascii=False),
            )
            db.session.add(metric)

    # os_stats section
    os_stats = parsed.get('os_stats', [])
    if isinstance(os_stats, list):
        for row in os_stats:
            metric = AWRMetric(
                report_id=report_id,
                metric_type='os_stat',
                metric_name=row.get('name', row.get('stat_name', '')),
                metric_value=row.get('value'),
                extra_json=json.dumps(row, ensure_ascii=False),
            )
            db.session.add(metric)
    elif isinstance(os_stats, dict):
        for key, value in os_stats.items():
            metric = AWRMetric(
                report_id=report_id,
                metric_type='os_stat',
                metric_name=key,
                metric_value=float(value) if isinstance(value, (int, float)) else None,
                extra_json=json.dumps({'name': key, 'value': value}, ensure_ascii=False),
            )
            db.session.add(metric)

    # rac_stats section
    rac_stats = parsed.get('rac_stats', [])
    if isinstance(rac_stats, list):
        for row in rac_stats:
            metric = AWRMetric(
                report_id=report_id,
                metric_type='rac',
                metric_name=row.get('name', row.get('statistic', '')),
                metric_value=row.get('value'),
                extra_json=json.dumps(row, ensure_ascii=False),
            )
            db.session.add(metric)
    elif isinstance(rac_stats, dict):
        for key, value in rac_stats.items():
            metric = AWRMetric(
                report_id=report_id,
                metric_type='rac',
                metric_name=key,
                metric_value=float(value) if isinstance(value, (int, float)) else None,
                extra_json=json.dumps({'name': key, 'value': value}, ensure_ascii=False),
            )
            db.session.add(metric)

    # redo_stats section
    redo_stats = parsed.get('redo_stats', [])
    if isinstance(redo_stats, list):
        for row in redo_stats:
            metric = AWRMetric(
                report_id=report_id,
                metric_type='redo',
                metric_name=row.get('name', row.get('statistic', '')),
                metric_value=row.get('value'),
                extra_json=json.dumps(row, ensure_ascii=False),
            )
            db.session.add(metric)
    elif isinstance(redo_stats, dict):
        for key, value in redo_stats.items():
            metric = AWRMetric(
                report_id=report_id,
                metric_type='redo',
                metric_name=key,
                metric_value=float(value) if isinstance(value, (int, float)) else None,
                extra_json=json.dumps({'name': key, 'value': value}, ensure_ascii=False),
            )
            db.session.add(metric)

    # parse_stats section
    parse_stats = parsed.get('parse_stats', [])
    if isinstance(parse_stats, list):
        for row in parse_stats:
            metric = AWRMetric(
                report_id=report_id,
                metric_type='parse_stat',
                metric_name=row.get('name', row.get('statistic', '')),
                metric_value=row.get('value'),
                extra_json=json.dumps(row, ensure_ascii=False),
            )
            db.session.add(metric)
    elif isinstance(parse_stats, dict):
        for key, value in parse_stats.items():
            metric = AWRMetric(
                report_id=report_id,
                metric_type='parse_stat',
                metric_name=key,
                metric_value=float(value) if isinstance(value, (int, float)) else None,
                extra_json=json.dumps({'name': key, 'value': value}, ensure_ascii=False),
            )
            db.session.add(metric)

    # segment_stats section
    segment_stats = parsed.get('segment_stats', [])
    if isinstance(segment_stats, list):
        for row in segment_stats:
            metric = AWRMetric(
                report_id=report_id,
                metric_type='segment',
                metric_name=row.get('name', row.get('segment_name', row.get('tablespace', ''))),
                metric_value=row.get('value') or row.get('logical_reads'),
                extra_json=json.dumps(row, ensure_ascii=False),
            )
            db.session.add(metric)
    elif isinstance(segment_stats, dict):
        for key, value in segment_stats.items():
            metric = AWRMetric(
                report_id=report_id,
                metric_type='segment',
                metric_name=key,
                metric_value=float(value) if isinstance(value, (int, float)) else None,
                extra_json=json.dumps({'name': key, 'value': value}, ensure_ascii=False),
            )
            db.session.add(metric)


def _reconstruct_parsed_data(report):
    """Reconstruct parsed_data dict from stored AWRMetric records, or re-parse from raw_html."""
    metrics = AWRMetric.query.filter_by(report_id=report.id).all()
    if not metrics and report.raw_html:
        parser = AWRParser()
        return parser.parse(report.raw_html)

    parsed_data = {
        'db_info': {
            'db_name': report.db_name or '',
            'instance_name': report.instance_name or '',
            'db_version': report.db_version or '',
            'host_name': report.host_name or '',
            'platform': report.platform or '',
        },
        'snap_info': {
            'begin_id': report.snap_begin_id,
            'end_id': report.snap_end_id,
            'begin_time': report.snap_begin_time.isoformat() if report.snap_begin_time else None,
            'end_time': report.snap_end_time.isoformat() if report.snap_end_time else None,
            'elapsed_seconds': report.elapsed_seconds,
        },
        'load_profile': [],
        'top_events': [],
        'top_sql': [],
        'io_stats': [],
        'memory_stats': [],
        'instance_efficiency': {},
        'os_stats': [],
        'rac_stats': [],
        'redo_stats': [],
        'parse_stats': [],
        'segment_stats': [],
    }

    for m in metrics:
        extra = json.loads(m.extra_json) if m.extra_json else {}
        if m.metric_type == 'load_profile':
            parsed_data['load_profile'].append(extra if extra else {
                'name': m.metric_name, 'value': m.metric_value, 'unit': m.metric_unit
            })
        elif m.metric_type == 'wait_event':
            parsed_data['top_events'].append(extra if extra else {
                'name': m.metric_name, 'pct_db_time': m.metric_value
            })
        elif m.metric_type == 'sql_stat':
            entry = extra if extra else {'sql_id': m.metric_name}
            entry['sql_text'] = m.metric_text or entry.get('sql_text', '')
            parsed_data['top_sql'].append(entry)
        elif m.metric_type == 'io_stat':
            parsed_data['io_stats'].append(extra if extra else {
                'name': m.metric_name, 'value': m.metric_value
            })
        elif m.metric_type == 'memory':
            parsed_data['memory_stats'].append(extra if extra else {
                'name': m.metric_name, 'value': m.metric_value
            })
        elif m.metric_type == 'efficiency':
            parsed_data['instance_efficiency'][m.metric_name] = m.metric_value
        elif m.metric_type == 'os_stat':
            parsed_data['os_stats'].append(extra if extra else {
                'name': m.metric_name, 'value': m.metric_value
            })
        elif m.metric_type == 'rac':
            parsed_data['rac_stats'].append(extra if extra else {
                'name': m.metric_name, 'value': m.metric_value
            })
        elif m.metric_type == 'redo':
            parsed_data['redo_stats'].append(extra if extra else {
                'name': m.metric_name, 'value': m.metric_value
            })
        elif m.metric_type == 'parse_stat':
            parsed_data['parse_stats'].append(extra if extra else {
                'name': m.metric_name, 'value': m.metric_value
            })
        elif m.metric_type == 'segment':
            parsed_data['segment_stats'].append(extra if extra else {
                'name': m.metric_name, 'value': m.metric_value
            })

    # Sort ordered items
    parsed_data['top_events'].sort(key=lambda x: x.get('pct_db_time', x.get('pct', 0)) or 0, reverse=True)
    parsed_data['top_sql'].sort(key=lambda x: x.get('rank_order', x.get('elapsed_time', 0)) or 0)

    return parsed_data


@awr_bp.route('/<int:report_id>')
@login_required
def view_report(report_id):
    report = AWRReport.query.get_or_404(report_id)
    if current_user.role == 'viewer' and report.upload_user_id != current_user.id:
        flash('无权查看此报告', 'error')
        return redirect(url_for('awr.list_reports'))

    # Load metrics grouped by type
    metrics_by_type = {}
    metrics = AWRMetric.query.filter_by(report_id=report.id).order_by(AWRMetric.rank_order.asc()).all()
    for m in metrics:
        if m.metric_type not in metrics_by_type:
            metrics_by_type[m.metric_type] = []
        metrics_by_type[m.metric_type].append(m)

    # Load existing analyses
    analyses = report.analyses.order_by(AWRAnalysisResult.created_at.desc()).all()

    return render_template('awr/view.html', report=report, metrics_by_type=metrics_by_type, analyses=analyses)


@awr_bp.route('/<int:report_id>/analyze', methods=['POST'])
@login_required
def analyze_report(report_id):
    if not current_user.can_analyze:
        flash('无分析权限', 'error')
        return redirect(url_for('awr.view_report', report_id=report_id))

    report = AWRReport.query.get_or_404(report_id)

    # Reconstruct parsed data from stored metrics
    parsed_data = _reconstruct_parsed_data(report)

    # Step 1: Score metrics
    scorer = MetricScorer()
    problems = scorer.score_all(parsed_data, report)

    # Step 2: Correlate
    correlator = CorrelationAnalyzer()
    correlations = correlator.analyze(parsed_data, problems)

    # Step 3: Baseline compare
    comparer = BaselineComparer()
    deviations = comparer.compare(report, parsed_data, db.session)

    # Step 4: LLM enhancement (optional)
    use_llm = request.form.get('use_llm') == 'on'
    llm_result = None
    llm_patterns = []
    if use_llm:
        llm_provider = SystemSetting.get('llm_provider', 'none')
        llm_key = SystemSetting.get('llm_api_key', '')
        llm_url = SystemSetting.get('llm_api_url', '')
        llm_model = SystemSetting.get('llm_model', '')
        if llm_provider != 'none' and llm_key:
            llm = LLMIntegration(llm_provider, llm_key, llm_url, llm_model)
            llm_result = llm.enhance_analysis(parsed_data, problems, correlations)
            llm_patterns = llm_result.get('learned_patterns', []) if isinstance(llm_result, dict) else []

    # Step 5: Determine overall health level
    all_problems = problems + deviations
    health_level = 'healthy'
    for p in all_problems:
        p_level = p.get('health_level', p.get('severity', 'medium'))
        if p_level in ('serious', 'critical', 'high'):
            health_level = 'serious'
            break
        elif p_level in ('warning', 'medium'):
            health_level = 'warning'

    # Step 6: Build summary string
    db_info = parsed_data.get('db_info', {})
    snap_info = parsed_data.get('snap_info', {})
    summary_parts = [
        f"数据库: {db_info.get('db_name', 'N/A')}/{db_info.get('instance_name', 'N/A')}",
        f"版本: {db_info.get('db_version', 'N/A')}",
        f"快照: {snap_info.get('begin_id', 'N/A')} - {snap_info.get('end_id', 'N/A')}",
        f"持续时间: {snap_info.get('elapsed_seconds', 'N/A')}秒",
        f"健康等级: {health_level}",
        f"发现问题: {len(all_problems)}个",
    ]
    if llm_result:
        summary_parts.append("(含LLM增强分析)")
    summary = ' | '.join(summary_parts)

    # Step 7: Create AWRAnalysisResult
    analysis = AWRAnalysisResult(
        report_id=report.id,
        analysis_type='combined' if llm_result else 'rule',
        health_level=health_level,
        summary=summary,
        problems_json=json.dumps(all_problems, ensure_ascii=False, default=str),
        recommendations_json=json.dumps(correlations, ensure_ascii=False, default=str),
        correlation_findings_json=json.dumps(correlations, ensure_ascii=False, default=str),
        llm_provider=SystemSetting.get('llm_provider') if llm_result else None,
        llm_raw_response=json.dumps(llm_result, ensure_ascii=False, default=str) if llm_result else None,
        llm_structured_json=json.dumps(llm_result.get('structured', {}), ensure_ascii=False, default=str) if isinstance(llm_result, dict) else None,
        learned_patterns_json=json.dumps(llm_patterns, ensure_ascii=False, default=str) if llm_patterns else None,
        analyst_id=current_user.id,
    )
    db.session.add(analysis)
    db.session.flush()  # Get analysis.id for AWRProblem records

    # Step 8: Create AWRProblem records
    for p in problems:
        problem_record = AWRProblem(
            report_id=report.id,
            analysis_id=analysis.id,
            problem_type=p.get('problem_type', p.get('category', 'general')),
            title=p.get('title', p.get('name', 'Unknown Problem')),
            severity=p.get('severity', 'medium'),
            health_level=p.get('health_level', 'warning'),
            metric_name=p.get('metric_name', ''),
            metric_value=p.get('metric_value'),
            metric_unit=p.get('metric_unit', ''),
            threshold_warning=p.get('threshold_warning'),
            threshold_serious=p.get('threshold_serious'),
            evidence=p.get('evidence', ''),
            related_metrics_json=json.dumps(p.get('related_metrics', []), ensure_ascii=False, default=str) if p.get('related_metrics') else None,
            correlation_chain=json.dumps(p.get('correlation_chain', []), ensure_ascii=False, default=str) if p.get('correlation_chain') else None,
        )
        db.session.add(problem_record)

    # Step 9: Self-learning
    learning_engine = LearningEngine()
    learning_engine.process_analysis(report, problems, correlations, llm_patterns, db.session)

    # Step 10: Update baseline
    comparer.update_baseline(report, parsed_data, db.session)

    # Step 11: Finalize
    report.status = 'analyzed'
    db.session.add(AuditLog(user_id=current_user.id, action='analyze_awr',
                            detail=f'Report #{report.id}', ip_address=request.remote_addr))
    db.session.commit()
    flash('分析完成', 'success')
    return redirect(url_for('awr.view_analysis', report_id=report.id, analysis_id=analysis.id))


@awr_bp.route('/<int:report_id>/analysis/<int:analysis_id>')
@login_required
def view_analysis(report_id, analysis_id):
    report = AWRReport.query.get_or_404(report_id)
    analysis = AWRAnalysisResult.query.get_or_404(analysis_id)
    if current_user.role == 'viewer' and report.upload_user_id != current_user.id:
        flash('无权查看', 'error')
        return redirect(url_for('awr.list_reports'))

    # Parse JSON fields for template
    problems_list = json.loads(analysis.problems_json) if analysis.problems_json else []
    recommendations = json.loads(analysis.recommendations_json) if analysis.recommendations_json else []
    correlations = json.loads(analysis.correlation_findings_json) if analysis.correlation_findings_json else []
    llm_structured = json.loads(analysis.llm_structured_json) if analysis.llm_structured_json else {}
    learned_patterns = json.loads(analysis.learned_patterns_json) if analysis.learned_patterns_json else []

    return render_template('awr/analysis.html', report=report, analysis=analysis,
                           problems_list=problems_list, recommendations=recommendations,
                           correlations=correlations, llm_structured=llm_structured,
                           learned_patterns=learned_patterns)


@awr_bp.route('/<int:report_id>/delete', methods=['POST'])
@login_required
def delete_report(report_id):
    if not current_user.is_admin:
        flash('仅管理员可删除', 'error')
        return redirect(url_for('awr.list_reports'))

    report = AWRReport.query.get_or_404(report_id)
    if report.file_path and os.path.exists(report.file_path):
        os.remove(report.file_path)
    db.session.add(AuditLog(user_id=current_user.id, action='delete_awr',
                            detail=report.title, ip_address=request.remote_addr))
    db.session.delete(report)
    db.session.commit()
    flash('报告已删除', 'success')
    return redirect(url_for('awr.list_reports'))
