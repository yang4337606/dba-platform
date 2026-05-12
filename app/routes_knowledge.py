import json
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from .models import db, KnowledgeBase, AuditLog

kb_bp = Blueprint('knowledge', __name__, url_prefix='/knowledge')


@kb_bp.route('/')
@login_required
def list_entries():
    page = request.args.get('page', 1, type=int)
    category = request.args.get('category', '')
    source = request.args.get('source', '')
    query = KnowledgeBase.query
    if category:
        query = query.filter_by(category=category)
    if source:
        query = query.filter_by(source=source)
    entries = query.order_by(KnowledgeBase.match_count.desc()).paginate(page=page, per_page=20)

    categories = db.session.query(KnowledgeBase.category).distinct().all()
    sources = db.session.query(KnowledgeBase.source).distinct().all()
    return render_template('knowledge/list.html', entries=entries,
                           categories=[c[0] for c in categories],
                           sources=[s[0] for s in sources],
                           current_category=category, current_source=source)


@kb_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add_entry():
    if not current_user.can_analyze:
        flash('无权限', 'error')
        return redirect(url_for('knowledge.list_entries'))

    if request.method == 'POST':
        entry = KnowledgeBase(
            category=request.form.get('category', 'general'),
            title=request.form.get('title', ''),
            pattern=request.form.get('pattern', ''),
            description=request.form.get('description', ''),
            solution=request.form.get('solution', ''),
            severity=request.form.get('severity', 'medium'),
            source='manual',
            confidence=0.7,
        )
        db.session.add(entry)
        db.session.add(AuditLog(user_id=current_user.id, action='add_knowledge',
                                detail=entry.title, ip_address=request.remote_addr))
        db.session.commit()
        flash('知识条目已添加', 'success')
        return redirect(url_for('knowledge.list_entries'))

    return render_template('knowledge/edit.html', entry=None)


@kb_bp.route('/<int:entry_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_entry(entry_id):
    if not current_user.can_analyze:
        flash('无权限', 'error')
        return redirect(url_for('knowledge.list_entries'))

    entry = KnowledgeBase.query.get_or_404(entry_id)
    if request.method == 'POST':
        entry.category = request.form.get('category', entry.category)
        entry.title = request.form.get('title', entry.title)
        entry.pattern = request.form.get('pattern', entry.pattern)
        entry.description = request.form.get('description', entry.description)
        entry.solution = request.form.get('solution', entry.solution)
        entry.severity = request.form.get('severity', entry.severity)
        entry.is_active = request.form.get('is_active') == 'on'
        db.session.add(AuditLog(user_id=current_user.id, action='edit_knowledge',
                                detail=entry.title, ip_address=request.remote_addr))
        db.session.commit()
        flash('知识条目已更新', 'success')
        return redirect(url_for('knowledge.list_entries'))

    return render_template('knowledge/edit.html', entry=entry)


@kb_bp.route('/<int:entry_id>/delete', methods=['POST'])
@login_required
def delete_entry(entry_id):
    if not current_user.is_admin:
        flash('仅管理员可删除', 'error')
        return redirect(url_for('knowledge.list_entries'))

    entry = KnowledgeBase.query.get_or_404(entry_id)
    db.session.delete(entry)
    db.session.commit()
    flash('知识条目已删除', 'success')
    return redirect(url_for('knowledge.list_entries'))


@kb_bp.route('/stats')
@login_required
def stats():
    total = KnowledgeBase.query.count()
    by_category = db.session.query(
        KnowledgeBase.category, db.func.count(KnowledgeBase.id)
    ).group_by(KnowledgeBase.category).all()
    by_source = db.session.query(
        KnowledgeBase.source, db.func.count(KnowledgeBase.id)
    ).group_by(KnowledgeBase.source).all()
    top_matched = KnowledgeBase.query.order_by(KnowledgeBase.match_count.desc()).limit(10).all()

    return render_template('knowledge/stats.html', total=total,
                           by_category=by_category, by_source=by_source,
                           top_matched=top_matched)
