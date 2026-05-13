import time
from collections import defaultdict
from datetime import datetime
from urllib.parse import urlparse
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from .models import db, User, AuditLog
from .i18n import t

# Simple in-memory rate limiter for login attempts
_login_attempts = defaultdict(list)  # ip -> [timestamps]
_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW_SECONDS = 300  # 5 minutes


def _is_rate_limited(ip):
    """Check if an IP has exceeded login attempt limits."""
    now = time.time()
    # Clean old entries
    _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < _LOGIN_WINDOW_SECONDS]
    return len(_login_attempts[ip]) >= _LOGIN_MAX_ATTEMPTS


def _record_attempt(ip):
    """Record a failed login attempt."""
    _login_attempts[ip].append(time.time())


def _is_safe_redirect_url(target):
    """Validate that the redirect target is a relative URL (no open redirect)."""
    if not target:
        return False
    parsed = urlparse(target)
    return parsed.scheme == '' and parsed.netloc == ''

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        # Rate limit check
        client_ip = request.remote_addr
        if _is_rate_limited(client_ip):
            flash(t('rate_limited', minutes=5), 'error')
            return render_template('auth/login.html')

        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password) and user.is_active_user:
            login_user(user, remember=request.form.get('remember'))
            user.last_login = datetime.utcnow()
            db.session.add(AuditLog(user_id=user.id, action='login', ip_address=request.remote_addr))
            db.session.commit()
            next_page = request.args.get('next')
            if not _is_safe_redirect_url(next_page):
                next_page = None
            return redirect(next_page or url_for('main.dashboard'))
        else:
            _record_attempt(client_ip)
            flash(t('login_failed'), 'error')

    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    db.session.add(AuditLog(user_id=current_user.id, action='logout', ip_address=request.remote_addr))
    db.session.commit()
    logout_user()
    return redirect(url_for('auth.login'))
