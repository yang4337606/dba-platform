import os
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from .models import db, AWRReport, AWRMetric, AWRProblem, AWRAnalysisResult, KnowledgeRule, AuditLog, SystemSetting
from .awr import (AWRParser, MetricScorer, CorrelationAnalyzer, BaselineComparer,
                   LLMIntegration, LearningEngine, SQLAntiPatternDetector, classify_wait_event,
                   get_parameter_recommendations, get_version_specific_notes,
                   compute_composite_health_score,
                   AdvisoryAnalyzer, TimeModelAnalyzer, WaitHistogramAnalyzer,
                   WorkloadClassifier)
from .i18n import t

logger = logging.getLogger(__name__)
awr_bp = Blueprint('awr', __name__, url_prefix='/awr')

# Thread pool for async analysis (max 2 concurrent analyses)
_analysis_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='awr_analysis')


def _allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ('html', 'htm')


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
            flash(t('no_file_selected'), 'error')
            return redirect(request.url)

        file = request.files['file']
        if file.filename == '':
            flash(t('file_not_selected'), 'error')
            return redirect(request.url)

        if not _allowed_file(file.filename):
            flash(t('invalid_file_format'), 'error')
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
            flash(t('file_read_error', error=str(e)), 'error')
            return redirect(request.url)

        # Parse the AWR report
        parser = AWRParser()
        try:
            parsed = parser.parse(html_content)
            db_info = parsed.get('db_info', {})
            snap_info = parsed.get('snap_info', {})

            # Create AWRReport record – auto-generate title from parsed data
            auto_title = ''
            if db_info.get('db_name'):
                auto_title = db_info['db_name']
                if db_info.get('instance_name'):
                    auto_title += f" / {db_info['instance_name']}"
                if snap_info.get('begin_id') and snap_info.get('end_id'):
                    auto_title += f" (#{snap_info['begin_id']}-#{snap_info['end_id']})"
            report = AWRReport(
                title=request.form.get('title', '').strip() or auto_title or filename,
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
                snap_begin_time=snap_info.get('snap_begin') or snap_info.get('begin_time'),
                snap_end_time=snap_info.get('snap_end') or snap_info.get('end_time'),
                elapsed_seconds=snap_info.get('elapsed_seconds'),
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
            flash(t('awr_upload_success'), 'success')
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
            flash(t('awr_parse_error', error=str(e)), 'error')
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

    # top_sql section -- parser returns dict {section_name: [rows]} or list
    top_sql = parsed.get('top_sql', {})
    sql_entries_flat = []
    if isinstance(top_sql, dict):
        for section_name, sql_list in top_sql.items():
            if isinstance(sql_list, list):
                for entry in sql_list:
                    if isinstance(entry, dict):
                        entry['_section'] = section_name
                        sql_entries_flat.append(entry)
    elif isinstance(top_sql, list):
        sql_entries_flat = top_sql
    for idx, sql_entry in enumerate(sql_entries_flat):
        metric = AWRMetric(
            report_id=report_id,
            metric_type='sql_stat',
            metric_name=sql_entry.get('sql_id', sql_entry.get('SQL Id', f'sql_rank_{idx + 1}')),
            metric_value=sql_entry.get('elapsed_time') or sql_entry.get('cpu_time') or sql_entry.get('buffer_gets'),
            metric_text=sql_entry.get('sql_text', sql_entry.get('SQL Text', '')),
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

    # --- New sections added in Batch 3 ---

    # advisories section
    _store_list_or_dict(report_id, 'advisory', parsed.get('advisories', []))

    # enqueue_activity section
    _store_list_or_dict(report_id, 'enqueue', parsed.get('enqueue_activity', []))

    # latch_detail section
    _store_list_or_dict(report_id, 'latch', parsed.get('latch_detail', []))

    # wait_histogram section
    _store_list_or_dict(report_id, 'wait_histogram', parsed.get('wait_histogram', []))

    # undo_stats section
    _store_list_or_dict(report_id, 'undo', parsed.get('undo_stats', []))

    # wait_class_summary section
    wait_class_summary = parsed.get('wait_class_summary', [])
    if isinstance(wait_class_summary, list):
        for row in wait_class_summary:
            metric = AWRMetric(
                report_id=report_id,
                metric_type='wait_class',
                metric_name=row.get('wait_class', row.get('name', '')),
                metric_value=row.get('pct_db_time', row.get('value')),
                metric_unit='%DB Time',
                extra_json=json.dumps(row, ensure_ascii=False),
            )
            db.session.add(metric)

    # temp_stats section
    _store_list_or_dict(report_id, 'temp', parsed.get('temp_stats', []))

    # time_model section
    time_model = parsed.get('time_model', {})
    if isinstance(time_model, dict):
        for key, tm in time_model.items():
            if isinstance(tm, dict):
                metric = AWRMetric(
                    report_id=report_id,
                    metric_type='time_model',
                    metric_name=tm.get('name', key),
                    metric_value=tm.get('time_seconds'),
                    metric_unit='seconds',
                    extra_json=json.dumps(tm, ensure_ascii=False),
                )
                db.session.add(metric)
    elif isinstance(time_model, list):
        for row in time_model:
            metric = AWRMetric(
                report_id=report_id,
                metric_type='time_model',
                metric_name=row.get('name', row.get('stat_name', '')),
                metric_value=row.get('time_seconds', row.get('value')),
                metric_unit='seconds',
                extra_json=json.dumps(row, ensure_ascii=False),
            )
            db.session.add(metric)

    # --- New sections (Batch 4 - missing AWR chapters) ---
    _store_list_or_dict(report_id, 'io_profile', parsed.get('io_profile', []))
    _store_list_or_dict(report_id, 'file_io', parsed.get('file_io_stats', []))
    _store_list_or_dict(report_id, 'dict_cache', parsed.get('dictionary_cache_stats', []))
    _store_list_or_dict(report_id, 'lib_cache', parsed.get('library_cache_activity', []))
    _store_list_or_dict(report_id, 'init_param', parsed.get('init_parameters', []))
    _store_list_or_dict(report_id, 'bg_wait_event', parsed.get('background_wait_events', []))
    _store_list_or_dict(report_id, 'service_stat', parsed.get('service_statistics', []))
    _store_list_or_dict(report_id, 'instance_recovery', parsed.get('instance_recovery_stats', []))

    # --- New sections (Batch 5 - v3 parser chapters) ---
    _store_list_or_dict(report_id, 'ash_activity', parsed.get('ash_activity', {}))
    _store_list_or_dict(report_id, 'addm_finding', parsed.get('addm_findings', []))
    _store_list_or_dict(report_id, 'sql_plan_change', parsed.get('sql_plan_changes', []))
    _store_list_or_dict(report_id, 'host_cpu', parsed.get('host_instance_cpu', {}))
    _store_list_or_dict(report_id, 'cache_size', parsed.get('cache_sizes', {}))
    _store_list_or_dict(report_id, 'seg_row_lock_itl', parsed.get('segment_row_lock_itl', []))


def _store_list_or_dict(report_id, metric_type, data):
    """Generic helper to store list-or-dict parsed sections as AWRMetric rows."""
    if isinstance(data, list):
        for row in data:
            name = row.get('name', row.get('stat_name', row.get('latch_name',
                   row.get('event', row.get('Event', row.get('advisory', ''))))))
            val = row.get('value', row.get('gets', row.get('waits')))
            metric = AWRMetric(
                report_id=report_id,
                metric_type=metric_type,
                metric_name=name or metric_type,
                metric_value=float(val) if isinstance(val, (int, float)) else None,
                extra_json=json.dumps(row, ensure_ascii=False),
            )
            db.session.add(metric)
    elif isinstance(data, dict):
        for key, value in data.items():
            metric = AWRMetric(
                report_id=report_id,
                metric_type=metric_type,
                metric_name=key,
                metric_value=float(value) if isinstance(value, (int, float)) else None,
                extra_json=json.dumps({'name': key, 'value': value}, ensure_ascii=False),
            )
            db.session.add(metric)


def _reconstruct_parsed_data(report):
    """Reconstruct parsed_data dict from stored AWRMetric records, or re-parse from file_path."""
    metrics = AWRMetric.query.filter_by(report_id=report.id).all()
    if not metrics and report.file_path and os.path.exists(report.file_path):
        with open(report.file_path, 'r', encoding='utf-8', errors='ignore') as f:
            parser = AWRParser()
            return parser.parse(f.read())

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
        'load_profile': {'raw': [], 'computed': {}},
        'top_events': [],
        'top_sql': {},
        'io_stats': [],
        'memory_stats': [],
        'instance_efficiency': {},
        'os_stats': [],
        'rac_stats': [],
        'redo_stats': {},
        'parse_stats': {},
        'segment_stats': [],
        'advisories': {},
        'enqueue_activity': [],
        'latch_detail': [],
        'wait_histogram': [],
        'undo_stats': {},
        'wait_class_summary': [],
        'temp_stats': {},
        'time_model': {},
        'io_profile': [],
        'file_io_stats': [],
        'dictionary_cache_stats': [],
        'library_cache_activity': [],
        'init_parameters': [],
        'background_wait_events': [],
        'service_statistics': [],
        'instance_recovery_stats': [],
    }

    for m in metrics:
        extra = json.loads(m.extra_json) if m.extra_json else {}
        if m.metric_type == 'load_profile':
            # Rebuild load_profile as dict with 'raw' and 'computed' keys
            if isinstance(extra, dict) and 'name' in extra and 'value' in extra:
                parsed_data['load_profile'][extra['name']] = extra['value']
            else:
                parsed_data['load_profile'][m.metric_name] = extra if extra else {
                    'name': m.metric_name, 'value': m.metric_value, 'unit': m.metric_unit
                }
        elif m.metric_type == 'wait_event':
            parsed_data['top_events'].append(extra if extra else {
                'name': m.metric_name, 'pct_db_time': m.metric_value
            })
        elif m.metric_type == 'sql_stat':
            entry = extra if extra else {'sql_id': m.metric_name}
            entry['sql_text'] = m.metric_text or entry.get('sql_text', '')
            section = entry.pop('_section', 'SQL ordered by Elapsed Time')
            parsed_data['top_sql'].setdefault(section, []).append(entry)
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
            parsed_data['redo_stats'][m.metric_name] = m.metric_value
        elif m.metric_type == 'parse_stat':
            parsed_data['parse_stats'][m.metric_name] = m.metric_value
        elif m.metric_type == 'segment':
            parsed_data['segment_stats'].append(extra if extra else {
                'name': m.metric_name, 'value': m.metric_value
            })
        elif m.metric_type == 'advisory':
            # Unwrap: extra is {'name': key, 'value': [row_dicts...]}, need to restore the list
            if isinstance(extra, dict) and isinstance(extra.get('value'), list):
                parsed_data['advisories'][m.metric_name] = extra['value']
            else:
                parsed_data['advisories'].setdefault(m.metric_name, []).append(
                    extra if extra else {'name': m.metric_name, 'value': m.metric_value}
                )
        elif m.metric_type == 'enqueue':
            parsed_data['enqueue_activity'].append(extra if extra else {
                'name': m.metric_name, 'value': m.metric_value
            })
        elif m.metric_type == 'latch':
            parsed_data['latch_detail'].append(extra if extra else {
                'name': m.metric_name, 'value': m.metric_value
            })
        elif m.metric_type == 'wait_histogram':
            parsed_data['wait_histogram'].append(extra if extra else {
                'name': m.metric_name, 'value': m.metric_value
            })
        elif m.metric_type == 'undo':
            parsed_data['undo_stats'][m.metric_name] = m.metric_value
        elif m.metric_type == 'wait_class':
            parsed_data['wait_class_summary'].append(extra if extra else {
                'wait_class': m.metric_name, 'pct_db_time': m.metric_value
            })
        elif m.metric_type == 'temp':
            parsed_data['temp_stats'][m.metric_name] = m.metric_value
        elif m.metric_type == 'time_model':
            parsed_data['time_model'][m.metric_name] = extra if extra else {
                'name': m.metric_name, 'time_seconds': m.metric_value
            }
        elif m.metric_type == 'io_profile':
            parsed_data['io_profile'].append(extra if extra else {'name': m.metric_name, 'value': m.metric_value})
        elif m.metric_type == 'file_io':
            parsed_data['file_io_stats'].append(extra if extra else {'name': m.metric_name, 'value': m.metric_value})
        elif m.metric_type == 'dict_cache':
            parsed_data['dictionary_cache_stats'].append(extra if extra else {'name': m.metric_name, 'value': m.metric_value})
        elif m.metric_type == 'lib_cache':
            parsed_data['library_cache_activity'].append(extra if extra else {'name': m.metric_name, 'value': m.metric_value})
        elif m.metric_type == 'init_param':
            parsed_data['init_parameters'].append(extra if extra else {'name': m.metric_name, 'value': m.metric_value})
        elif m.metric_type == 'bg_wait_event':
            parsed_data['background_wait_events'].append(extra if extra else {'name': m.metric_name, 'value': m.metric_value})
        elif m.metric_type == 'service_stat':
            parsed_data['service_statistics'].append(extra if extra else {'name': m.metric_name, 'value': m.metric_value})
        elif m.metric_type == 'instance_recovery':
            parsed_data['instance_recovery_stats'].append(extra if extra else {'name': m.metric_name, 'value': m.metric_value})

    # Sort ordered items
    parsed_data['top_events'].sort(key=lambda x: x.get('pct_db_time', x.get('pct', 0)) or 0, reverse=True)
    # Sort each SQL section list individually
    for _section_key, _sql_list in parsed_data['top_sql'].items():
        _sql_list.sort(key=lambda x: x.get('rank_order', x.get('elapsed_time', 0)) or 0)

    return parsed_data


@awr_bp.route('/<int:report_id>')
@login_required
def view_report(report_id):
    report = AWRReport.query.get_or_404(report_id)
    if current_user.role == 'viewer' and report.upload_user_id != current_user.id:
        flash(t('no_view_permission'), 'error')
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
        flash(t('no_analyze_permission'), 'error')
        return redirect(url_for('awr.view_report', report_id=report_id))

    report = AWRReport.query.get_or_404(report_id)

    # Prevent duplicate analysis submissions
    if report.status == 'analyzing':
        flash(t('analysis_in_progress'), 'info')
        return redirect(url_for('awr.view_report', report_id=report_id))

    use_llm = request.form.get('use_llm') == 'on'
    user_id = current_user.id
    ip_address = request.remote_addr

    # Mark report as analyzing
    report.status = 'analyzing'
    db.session.commit()

    # Submit analysis to thread pool for async execution
    app = current_app._get_current_object()
    _analysis_executor.submit(_run_analysis, app, report_id, user_id, use_llm, ip_address)

    flash(t('analysis_submitted'), 'info')
    return redirect(url_for('awr.view_report', report_id=report_id))


def _run_analysis(app, report_id, user_id, use_llm, ip_address):
    """Run the full analysis pipeline in a background thread."""
    with app.app_context():
        try:
            report = AWRReport.query.get(report_id)
            if not report:
                logger.error(f"Analysis failed: report {report_id} not found")
                return

            # Reconstruct parsed data from stored metrics
            parsed_data = _reconstruct_parsed_data(report)

            # Step 0.5: Workload Classification (adjusts scoring thresholds)
            workload_classifier = WorkloadClassifier()
            workload_info = workload_classifier.classify(parsed_data)
            threshold_overrides = workload_info.get('threshold_adjustments', {})

            # Step 1: Score metrics (with workload-aware thresholds)
            scorer = MetricScorer()
            problems = scorer.score_all(parsed_data, report, threshold_overrides=threshold_overrides)

            # Step 2: Correlate
            correlator = CorrelationAnalyzer()
            correlations = correlator.analyze(parsed_data, problems)

            # Step 3: Baseline compare
            comparer = BaselineComparer()
            deviations = comparer.compare(report, parsed_data, db.session)

            # Step 3.5: SQL Anti-Pattern Detection
            anti_pattern_detector = SQLAntiPatternDetector()
            sql_anti_patterns = anti_pattern_detector.detect_from_parsed(parsed_data)
            for ap in sql_anti_patterns:
                problems.append({
                    'problem_type': 'sql_anti_pattern',
                    'title': t('sql_anti_pattern_title', pattern=ap['anti_pattern'], sql_id=ap['sql_id']),
                    'severity': ap['severity'],
                    'health_level': 'warning' if ap['severity'] in ('low', 'medium') else 'serious',
                    'metric_name': f"anti_pattern_{ap['anti_pattern'].lower()}",
                    'metric_value': None,
                    'metric_unit': '',
                    'evidence': t('sql_snippet_evidence', description=ap['description'], snippet=ap['sql_snippet'][:100]),
                    'threshold_warning': None,
                    'threshold_serious': None,
                })

            # Step 3.6: Wait Class Aggregation
            wait_class_totals = {}
            for evt in parsed_data.get('top_events', []):
                wclass = evt.get('wait_class') or classify_wait_event(evt.get('event', evt.get('name', '')))
                pct = float(evt.get('pct_db_time', 0) or 0)
                wait_class_totals[wclass] = wait_class_totals.get(wclass, 0) + pct
            for wclass, total_pct in wait_class_totals.items():
                if wclass in ('Idle', 'Other'):
                    continue
                if total_pct > 40:
                    correlations.append({
                        'title': t('wait_class_title', wclass=wclass, pct=total_pct),
                        'trigger_problem': t('wait_class_trigger', wclass=wclass),
                        'related_evidence': [t('wait_class_evidence', wclass=wclass, pct=total_pct)],
                        'root_cause': t('wait_class_root_cause', wclass=wclass),
                        'suggestion': t('wait_class_suggestion', wclass=wclass),
                    })

            # Step 3.7: Parameter recommendations and version notes
            param_recommendations = get_parameter_recommendations(problems, parsed_data)
            version_notes = get_version_specific_notes(
                parsed_data.get('db_info', {}).get('db_version', ''))

            # Step 3.8: Advisory Analysis
            advisory_analyzer = AdvisoryAnalyzer()
            advisory_recommendations = advisory_analyzer.analyze(parsed_data.get('advisories', {}))

            # Step 3.9: Time Model Analysis
            time_model_analyzer = TimeModelAnalyzer()
            lp = parsed_data.get('load_profile', {})
            lp_computed = lp.get('computed', {}) if isinstance(lp, dict) else {}
            db_time_per_sec = float(lp_computed.get('db_time', 0) or 0)
            elapsed_secs = float(parsed_data.get('snap_info', {}).get('elapsed_seconds', 0) or 0)
            db_time_total = db_time_per_sec * elapsed_secs
            # Fallback: if load_profile didn't yield db_time, try time_model directly
            if db_time_total <= 0:
                tm = parsed_data.get('time_model', {})
                db_time_entry = tm.get('db_time') or tm.get('DB_time') or tm.get('DB Time') or {}
                if isinstance(db_time_entry, dict):
                    db_time_total = float(db_time_entry.get('time_seconds', 0) or 0)
            time_model_findings = time_model_analyzer.analyze(parsed_data.get('time_model', {}), db_time_total)

            # Step 3.10: Wait Histogram Analysis
            histogram_analyzer = WaitHistogramAnalyzer()
            histogram_findings = histogram_analyzer.analyze(parsed_data.get('wait_histogram', []))

            # Step 4: LLM enhancement (optional)
            llm_result = None
            llm_patterns = []
            if use_llm:
                llm_provider = SystemSetting.get('llm_provider', 'none')
                llm_key = SystemSetting.get('llm_api_key', '')
                llm_url = SystemSetting.get('llm_api_url', '')
                llm_model = SystemSetting.get('llm_model', '')
                if llm_provider != 'none' and llm_key:
                    llm = LLMIntegration(llm_provider, llm_key, llm_url, llm_model)
                    llm_result = llm.enhance_analysis(
                        parsed_data, problems, correlations,
                        anti_patterns=sql_anti_patterns,
                        wait_class_summary=wait_class_totals,
                        param_recommendations=param_recommendations,
                    )
                    llm_patterns = llm_result.get('learned_patterns', []) if isinstance(llm_result, dict) else []

            # Step 5: Determine overall health level and composite score
            all_problems = problems + deviations
            health_level = 'healthy'
            for p in all_problems:
                p_level = p.get('health_level', p.get('severity', 'medium'))
                if p_level in ('serious', 'critical', 'high'):
                    health_level = 'serious'
                    break
                elif p_level in ('warning', 'medium'):
                    health_level = 'warning'

            composite_score = compute_composite_health_score(problems, correlations, deviations)

            # Step 6: Build summary string
            db_info = parsed_data.get('db_info', {})
            snap_info = parsed_data.get('snap_info', {})
            summary_parts = [
                t('summary_database', db_name=db_info.get('db_name', 'N/A'), instance_name=db_info.get('instance_name', 'N/A')),
                t('summary_version', version=db_info.get('db_version', 'N/A')),
                t('summary_snapshot', begin_id=snap_info.get('begin_id', 'N/A'), end_id=snap_info.get('end_id', 'N/A')),
                t('summary_duration', seconds=snap_info.get('elapsed_seconds', 'N/A')),
                t('summary_health_score', score=composite_score, level=health_level),
                t('summary_problems_found', count=len(all_problems)),
            ]
            if sql_anti_patterns:
                summary_parts.append(t('summary_sql_anti_patterns', count=len(sql_anti_patterns)))
            if param_recommendations:
                summary_parts.append(t('summary_param_suggestions', count=len(param_recommendations)))
            if advisory_recommendations:
                summary_parts.append(t('summary_advisory_suggestions', count=len(advisory_recommendations)))
            if time_model_findings:
                summary_parts.append(t('summary_time_model_findings', count=len(time_model_findings)))
            summary_parts.append(t('summary_workload_type', wtype=workload_info['workload_type']))
            if llm_result:
                summary_parts.append(t('summary_llm_enhanced'))
            summary = ' | '.join(summary_parts)

            # Step 7: Create AWRAnalysisResult
            full_recommendations = {
                'correlations': correlations,
                'parameter_recommendations': param_recommendations,
                'version_notes': version_notes,
                'composite_score': composite_score,
                'advisory_recommendations': advisory_recommendations,
                'time_model_findings': time_model_findings,
                'histogram_findings': histogram_findings,
                'workload_info': workload_info,
            }
            analysis = AWRAnalysisResult(
                report_id=report.id,
                analysis_type='combined' if llm_result else 'rule',
                health_level=health_level,
                summary=summary,
                problems_json=json.dumps(all_problems, ensure_ascii=False, default=str),
                recommendations_json=json.dumps(full_recommendations, ensure_ascii=False, default=str),
                correlation_findings_json=json.dumps(correlations, ensure_ascii=False, default=str),
                llm_provider=SystemSetting.get('llm_provider') if llm_result else None,
                llm_raw_response=json.dumps(llm_result, ensure_ascii=False, default=str) if llm_result else None,
                llm_structured_json=json.dumps(llm_result.get('structured', {}), ensure_ascii=False, default=str) if isinstance(llm_result, dict) else None,
                learned_patterns_json=json.dumps(llm_patterns, ensure_ascii=False, default=str) if llm_patterns else None,
                analyst_id=user_id,
            )
            db.session.add(analysis)
            db.session.flush()

            # Step 8: Create AWRProblem records
            for p in problems:
                problem_record = AWRProblem(
                    report_id=report.id,
                    analysis_id=analysis.id,
                    problem_type=p.get('problem_type', p.get('category', 'general')),
                    title=p.get('title', p.get('name', t('unknown_problem'))),
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
            db.session.add(AuditLog(user_id=user_id, action='analyze_awr',
                                    detail=f'Report #{report.id}', ip_address=ip_address))
            db.session.commit()
            logger.info(f"Analysis completed for report #{report_id}")

        except Exception as e:
            logger.error(f"Analysis failed for report #{report_id}: {e}", exc_info=True)
            try:
                db.session.rollback()
                report = AWRReport.query.get(report_id)
                if report:
                    report.status = 'error'
                    db.session.commit()
            except Exception:
                logger.error(f"Failed to update report status for #{report_id}", exc_info=True)


@awr_bp.route('/<int:report_id>/analysis/<int:analysis_id>')
@login_required
def view_analysis(report_id, analysis_id):
    report = AWRReport.query.get_or_404(report_id)
    analysis = AWRAnalysisResult.query.get_or_404(analysis_id)
    if current_user.role == 'viewer' and report.upload_user_id != current_user.id:
        flash(t('no_view_access'), 'error')
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


@awr_bp.route('/<int:report_id>/analysis/<int:analysis_id>/export')
@login_required
def export_analysis(report_id, analysis_id):
    """Export analysis results as downloadable JSON."""
    report = AWRReport.query.get_or_404(report_id)
    analysis = AWRAnalysisResult.query.get_or_404(analysis_id)
    if current_user.role == 'viewer' and report.upload_user_id != current_user.id:
        flash(t('no_export_permission'), 'error')
        return redirect(url_for('awr.list_reports'))

    export_data = {
        'report': {
            'id': report.id,
            'title': report.title,
            'db_name': report.db_name,
            'instance_name': report.instance_name,
            'db_version': report.db_version,
            'host_name': report.host_name,
            'snap_begin_id': report.snap_begin_id,
            'snap_end_id': report.snap_end_id,
            'elapsed_seconds': report.elapsed_seconds,
        },
        'analysis': {
            'id': analysis.id,
            'type': analysis.analysis_type,
            'health_level': analysis.health_level,
            'summary': analysis.summary,
            'created_at': analysis.created_at.isoformat() if analysis.created_at else None,
        },
        'problems': json.loads(analysis.problems_json) if analysis.problems_json else [],
        'recommendations': json.loads(analysis.recommendations_json) if analysis.recommendations_json else {},
        'correlations': json.loads(analysis.correlation_findings_json) if analysis.correlation_findings_json else [],
    }

    from flask import Response
    response = Response(
        json.dumps(export_data, ensure_ascii=False, indent=2, default=str),
        mimetype='application/json',
        headers={'Content-Disposition': f'attachment; filename=awr_analysis_{report_id}_{analysis_id}.json'}
    )
    return response


@awr_bp.route('/<int:report_id>/export_metrics')
@login_required
def export_metrics(report_id):
    """Export report metrics as CSV."""
    report = AWRReport.query.get_or_404(report_id)
    if current_user.role == 'viewer' and report.upload_user_id != current_user.id:
        flash(t('no_export_permission'), 'error')
        return redirect(url_for('awr.list_reports'))

    import csv
    import io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['metric_type', 'metric_name', 'metric_value', 'metric_unit', 'rank_order'])

    metrics = AWRMetric.query.filter_by(report_id=report.id).order_by(
        AWRMetric.metric_type, AWRMetric.rank_order.asc()).all()
    for m in metrics:
        writer.writerow([m.metric_type, m.metric_name, m.metric_value, m.metric_unit, m.rank_order])

    from flask import Response
    response = Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=awr_metrics_{report_id}.csv'}
    )
    return response


@awr_bp.route('/compare', methods=['GET', 'POST'])
@login_required
def compare_reports():
    if request.method == 'POST':
        report_id_a = request.form.get('report_a', type=int)
        report_id_b = request.form.get('report_b', type=int)
        if not report_id_a or not report_id_b:
            flash(t('select_two_reports'), 'error')
            return redirect(url_for('awr.compare_reports'))
        return redirect(url_for('awr.compare_result', id_a=report_id_a, id_b=report_id_b))

    # GET: show report selection
    reports = AWRReport.query.filter(AWRReport.status.in_(['parsed', 'analyzed'])).order_by(AWRReport.created_at.desc()).limit(50).all()
    return render_template('awr/compare_select.html', reports=reports)


@awr_bp.route('/compare/<int:id_a>/<int:id_b>')
@login_required
def compare_result(id_a, id_b):
    report_a = AWRReport.query.get_or_404(id_a)
    report_b = AWRReport.query.get_or_404(id_b)

    parsed_a = _reconstruct_parsed_data(report_a)
    parsed_b = _reconstruct_parsed_data(report_b)

    # Build comparison data
    diff = _build_comparison(parsed_a, parsed_b, report_a, report_b)

    return render_template('awr/compare_result.html',
                          report_a=report_a, report_b=report_b, diff=diff)


def _build_comparison(parsed_a, parsed_b, report_a, report_b):
    """Build structured comparison between two AWR reports."""
    diff = {
        'load_profile': [],
        'wait_events': [],
        'efficiency': [],
        'key_metrics': [],
        'memory': [],
        'io_stats': [],
        'time_model': [],
    }

    # Compare load profile computed values
    lp_a = parsed_a.get('load_profile', {})
    lp_b = parsed_b.get('load_profile', {})
    computed_a = lp_a.get('computed', {}) if isinstance(lp_a, dict) else {}
    computed_b = lp_b.get('computed', {}) if isinstance(lp_b, dict) else {}

    for key in set(list(computed_a.keys()) + list(computed_b.keys())):
        val_a = float(computed_a.get(key, 0) or 0)
        val_b = float(computed_b.get(key, 0) or 0)
        change_pct = ((val_b - val_a) / val_a * 100) if val_a != 0 else 0
        diff['load_profile'].append({
            'metric': key,
            'value_a': val_a,
            'value_b': val_b,
            'change_pct': round(change_pct, 1),
            'direction': 'up' if val_b > val_a else ('down' if val_b < val_a else 'same'),
        })

    # Compare top wait events
    events_a = {(e.get('event', e.get('name', ''))): e for e in parsed_a.get('top_events', [])}
    events_b = {(e.get('event', e.get('name', ''))): e for e in parsed_b.get('top_events', [])}
    all_events = set(list(events_a.keys()) + list(events_b.keys()))
    for evt_name in all_events:
        if not evt_name:
            continue
        ea = events_a.get(evt_name, {})
        eb = events_b.get(evt_name, {})
        pct_a = float(ea.get('pct_db_time', 0) or 0)
        pct_b = float(eb.get('pct_db_time', 0) or 0)
        diff['wait_events'].append({
            'event': evt_name,
            'pct_a': pct_a,
            'pct_b': pct_b,
            'change': round(pct_b - pct_a, 1),
            'direction': 'up' if pct_b > pct_a else ('down' if pct_b < pct_a else 'same'),
        })
    diff['wait_events'].sort(key=lambda x: abs(x['change']), reverse=True)

    # Compare instance efficiency
    eff_a = parsed_a.get('instance_efficiency', {})
    eff_b = parsed_b.get('instance_efficiency', {})
    if isinstance(eff_a, list):
        eff_a = {item.get('name', item.get('metric', '')): item.get('value', item.get('pct', 0)) for item in eff_a}
    if isinstance(eff_b, list):
        eff_b = {item.get('name', item.get('metric', '')): item.get('value', item.get('pct', 0)) for item in eff_b}
    for key in set(list(eff_a.keys()) + list(eff_b.keys())):
        val_a = float(eff_a.get(key, 0) or 0)
        val_b = float(eff_b.get(key, 0) or 0)
        diff['efficiency'].append({
            'metric': key,
            'value_a': val_a,
            'value_b': val_b,
            'change': round(val_b - val_a, 1),
        })

    # Build key_metrics summary from the most significant changes
    KEY_METRICS_NAMES = {
        'db_time', 'db_cpu', 'physical_reads', 'logical_reads',
        'redo_size', 'transactions', 'executes', 'hard_parses',
    }
    for item in diff['load_profile']:
        metric_key = item.get('metric', '')
        if metric_key in KEY_METRICS_NAMES or abs(item.get('change_pct', 0)) > 20:
            diff['key_metrics'].append(item)
    # Sort by absolute change descending
    diff['key_metrics'].sort(key=lambda x: abs(x.get('change_pct', 0)), reverse=True)

    # Compare memory stats
    diff['memory'] = []
    mem_a = parsed_a.get('memory_stats', {})
    mem_b = parsed_b.get('memory_stats', {})
    # Flatten to comparable format
    def _flatten_memory(mem):
        result = {}
        if isinstance(mem, dict):
            for section, rows in mem.items():
                if isinstance(rows, list):
                    for row in rows:
                        name = row.get('name', row.get('component', row.get('Pool Name', '')))
                        size = row.get('size', row.get('value', row.get('Size (M)', 0)))
                        if name:
                            result[f"{section}:{name}"] = float(size) if isinstance(size, (int, float)) else 0
        elif isinstance(mem, list):
            for row in mem:
                name = row.get('name', row.get('component', ''))
                val = row.get('size', row.get('value', 0))
                if name:
                    result[name] = float(val) if isinstance(val, (int, float)) else 0
        return result
    flat_a = _flatten_memory(mem_a)
    flat_b = _flatten_memory(mem_b)
    for key in set(list(flat_a.keys()) + list(flat_b.keys())):
        val_a = flat_a.get(key, 0)
        val_b = flat_b.get(key, 0)
        change_pct = ((val_b - val_a) / val_a * 100) if val_a != 0 else 0
        diff['memory'].append({
            'metric': key, 'value_a': val_a, 'value_b': val_b,
            'change_pct': round(change_pct, 1),
        })

    # Compare IO stats
    diff['io_stats'] = []
    def _flatten_io(io_data):
        result = {}
        if isinstance(io_data, list):
            for row in io_data:
                name = row.get('name', row.get('tablespace', row.get('function', '')))
                reads = row.get('reads', row.get('value', 0))
                if name:
                    result[name] = float(reads) if isinstance(reads, (int, float)) else 0
        return result
    io_a = _flatten_io(parsed_a.get('io_stats', []))
    io_b = _flatten_io(parsed_b.get('io_stats', []))
    for key in set(list(io_a.keys()) + list(io_b.keys())):
        val_a = io_a.get(key, 0)
        val_b = io_b.get(key, 0)
        change_pct = ((val_b - val_a) / val_a * 100) if val_a != 0 else 0
        diff['io_stats'].append({
            'metric': key, 'value_a': val_a, 'value_b': val_b,
            'change_pct': round(change_pct, 1),
        })

    # Compare time model
    diff['time_model'] = []
    def _flatten_time_model(tm):
        result = {}
        if isinstance(tm, dict):
            for key, val in tm.items():
                if isinstance(val, dict):
                    result[val.get('name', key)] = float(val.get('time_seconds', 0) or 0)
                else:
                    result[key] = float(val) if isinstance(val, (int, float)) else 0
        return result
    tm_a = _flatten_time_model(parsed_a.get('time_model', {}))
    tm_b = _flatten_time_model(parsed_b.get('time_model', {}))
    for key in set(list(tm_a.keys()) + list(tm_b.keys())):
        val_a = tm_a.get(key, 0)
        val_b = tm_b.get(key, 0)
        change_pct = ((val_b - val_a) / val_a * 100) if val_a != 0 else 0
        diff['time_model'].append({
            'metric': key, 'value_a': round(val_a, 2), 'value_b': round(val_b, 2),
            'change_pct': round(change_pct, 1),
        })

    return diff


@awr_bp.route('/<int:report_id>/delete', methods=['POST'])
@login_required
def delete_report(report_id):
    if not current_user.is_admin:
        flash(t('admin_only_delete'), 'error')
        return redirect(url_for('awr.list_reports'))

    report = AWRReport.query.get_or_404(report_id)
    if report.file_path and os.path.exists(report.file_path):
        os.remove(report.file_path)
    db.session.add(AuditLog(user_id=current_user.id, action='delete_awr',
                            detail=report.title, ip_address=request.remote_addr))
    db.session.delete(report)
    db.session.commit()
    flash(t('report_deleted'), 'success')
    return redirect(url_for('awr.list_reports'))
