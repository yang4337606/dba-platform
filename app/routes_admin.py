from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from functools import wraps
from .models import db, User, AWRReport, AWRAnalysisResult, KnowledgeRule, AuditLog, SystemSetting, GitHubProject

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def admin_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            flash('需要管理员权限', 'error')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated


@admin_bp.route('/')
@admin_required
def index():
    stats = {
        'users': User.query.count(),
        'reports': AWRReport.query.count(),
        'analyses': AWRAnalysisResult.query.count(),
        'knowledge': KnowledgeRule.query.count(),
        'projects': GitHubProject.query.count(),
        'learned_kb': KnowledgeRule.query.filter_by(source='learned').count(),
    }
    recent_logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(20).all()
    return render_template('admin/index.html', stats=stats, recent_logs=recent_logs)


# ---- User Management ----
@admin_bp.route('/users')
@admin_required
def users():
    all_users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=all_users)


@admin_bp.route('/users/add', methods=['GET', 'POST'])
@admin_required
def add_user():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        role = request.form.get('role', 'viewer')

        if User.query.filter_by(username=username).first():
            flash('用户名已存在', 'error')
            return redirect(request.url)

        user = User(username=username, email=email, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.add(AuditLog(user_id=current_user.id, action='add_user',
                                detail=username, ip_address=request.remote_addr))
        db.session.commit()
        flash(f'用户 {username} 已创建', 'success')
        return redirect(url_for('admin.users'))

    return render_template('admin/user_form.html', user=None)


@admin_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    if request.method == 'POST':
        user.email = request.form.get('email', user.email)
        user.role = request.form.get('role', user.role)
        user.is_active_user = request.form.get('is_active') == 'on'
        new_pwd = request.form.get('password', '')
        if new_pwd:
            user.set_password(new_pwd)
        db.session.add(AuditLog(user_id=current_user.id, action='edit_user',
                                detail=user.username, ip_address=request.remote_addr))
        db.session.commit()
        flash('用户已更新', 'success')
        return redirect(url_for('admin.users'))

    return render_template('admin/user_form.html', user=user)


@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('不能删除当前登录用户', 'error')
        return redirect(url_for('admin.users'))
    db.session.delete(user)
    db.session.commit()
    flash('用户已删除', 'success')
    return redirect(url_for('admin.users'))


# ---- System Settings (LLM config etc.) ----
@admin_bp.route('/settings', methods=['GET', 'POST'])
@admin_required
def settings():
    if request.method == 'POST':
        keys = ['llm_provider', 'llm_api_key', 'llm_api_url', 'llm_model',
                'site_title', 'site_description']
        for key in keys:
            val = request.form.get(key, '')
            SystemSetting.set(key, val)
        flash('设置已保存', 'success')
        return redirect(url_for('admin.settings'))

    current_settings = {}
    for s in SystemSetting.query.all():
        current_settings[s.key] = s.value
    return render_template('admin/settings.html', settings=current_settings)


# ---- Audit Log ----
@admin_bp.route('/logs')
@admin_required
def logs():
    page = request.args.get('page', 1, type=int)
    log_entries = AuditLog.query.order_by(AuditLog.created_at.desc()).paginate(page=page, per_page=30)
    return render_template('admin/logs.html', logs=log_entries)
