import json
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from .models import db, KnowledgeRule, AuditLog
from .i18n import t

kb_bp = Blueprint('knowledge', __name__, url_prefix='/knowledge')


@kb_bp.route('/')
@login_required
def list_entries():
    page = request.args.get('page', 1, type=int)
    category = request.args.get('category', '')
    source = request.args.get('source', '')
    status = request.args.get('status', '')

    query = KnowledgeRule.query
    if category:
        query = query.filter_by(category=category)
    if source:
        query = query.filter_by(source=source)
    if status:
        query = query.filter_by(status=status)

    entries = query.order_by(KnowledgeRule.hit_count.desc()).paginate(page=page, per_page=20)

    categories = db.session.query(KnowledgeRule.category).distinct().all()
    sources = db.session.query(KnowledgeRule.source).distinct().all()
    statuses = db.session.query(KnowledgeRule.status).distinct().all()

    return render_template('knowledge/list.html', entries=entries,
                           categories=[c[0] for c in categories],
                           sources=[s[0] for s in sources],
                           statuses=[s[0] for s in statuses],
                           current_category=category,
                           current_source=source,
                           current_status=status)


@kb_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add_entry():
    if not current_user.can_analyze:
        flash(t('no_permission'), 'error')
        return redirect(url_for('knowledge.list_entries'))

    if request.method == 'POST':
        # Validate conditions_json is valid JSON
        conditions_raw = request.form.get('conditions_json', '[]')
        try:
            json.loads(conditions_raw)
        except (json.JSONDecodeError, TypeError):
            flash(t('invalid_json'), 'error')
            return render_template('knowledge/edit.html', entry=None)

        entry = KnowledgeRule(
            name=request.form.get('name', ''),
            category=request.form.get('category', 'general'),
            conditions_json=conditions_raw,
            root_cause=request.form.get('root_cause', ''),
            solution=request.form.get('solution', ''),
            severity=request.form.get('severity', 'medium'),
            source='manual',
            confidence=0.7,
            status='active',
            is_active=True,
        )
        db.session.add(entry)
        db.session.add(AuditLog(user_id=current_user.id, action='add_knowledge',
                                detail=entry.name, ip_address=request.remote_addr))
        db.session.commit()
        flash(t('knowledge_added'), 'success')
        return redirect(url_for('knowledge.list_entries'))

    return render_template('knowledge/edit.html', entry=None)


@kb_bp.route('/<int:entry_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_entry(entry_id):
    if not current_user.can_analyze:
        flash(t('no_permission'), 'error')
        return redirect(url_for('knowledge.list_entries'))

    entry = KnowledgeRule.query.get_or_404(entry_id)
    if request.method == 'POST':
        # Validate conditions_json is valid JSON
        conditions_raw = request.form.get('conditions_json', entry.conditions_json)
        try:
            json.loads(conditions_raw)
        except (json.JSONDecodeError, TypeError):
            flash(t('invalid_json'), 'error')
            return render_template('knowledge/edit.html', entry=entry)

        entry.name = request.form.get('name', entry.name)
        entry.category = request.form.get('category', entry.category)
        entry.conditions_json = conditions_raw
        entry.root_cause = request.form.get('root_cause', entry.root_cause)
        entry.solution = request.form.get('solution', entry.solution)
        entry.severity = request.form.get('severity', entry.severity)
        entry.is_active = request.form.get('is_active') == 'on'
        entry.status = request.form.get('status', entry.status)

        db.session.add(AuditLog(user_id=current_user.id, action='edit_knowledge',
                                detail=entry.name, ip_address=request.remote_addr))
        db.session.commit()
        flash(t('knowledge_updated'), 'success')
        return redirect(url_for('knowledge.list_entries'))

    return render_template('knowledge/edit.html', entry=entry)


@kb_bp.route('/<int:entry_id>/delete', methods=['POST'])
@login_required
def delete_entry(entry_id):
    if not current_user.is_admin:
        flash(t('admin_only_delete'), 'error')
        return redirect(url_for('knowledge.list_entries'))

    entry = KnowledgeRule.query.get_or_404(entry_id)
    db.session.delete(entry)
    db.session.commit()
    flash(t('knowledge_deleted'), 'success')
    return redirect(url_for('knowledge.list_entries'))


@kb_bp.route('/stats')
@login_required
def stats():
    total = KnowledgeRule.query.count()
    by_category = db.session.query(
        KnowledgeRule.category, db.func.count(KnowledgeRule.id)
    ).group_by(KnowledgeRule.category).all()
    by_source = db.session.query(
        KnowledgeRule.source, db.func.count(KnowledgeRule.id)
    ).group_by(KnowledgeRule.source).all()
    by_status = db.session.query(
        KnowledgeRule.status, db.func.count(KnowledgeRule.id)
    ).group_by(KnowledgeRule.status).all()
    top_matched = KnowledgeRule.query.order_by(KnowledgeRule.hit_count.desc()).limit(10).all()

    return render_template('knowledge/stats.html', total=total,
                           by_category=by_category, by_source=by_source,
                           by_status=by_status, top_matched=top_matched)
