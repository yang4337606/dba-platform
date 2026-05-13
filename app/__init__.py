import os
import json
import hashlib
import hmac
from flask import Flask, request, session, abort
from flask_login import LoginManager
from .config import Config
from .models import db, User, KnowledgeRule, SystemSetting

login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = '请先登录'


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Ensure dirs exist
    os.makedirs(os.path.join(app.root_path, 'instance'), exist_ok=True)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)

    # Simple CSRF protection
    @app.before_request
    def csrf_protect():
        if request.method in ('POST', 'PUT', 'DELETE', 'PATCH'):
            token = request.form.get('_csrf_token') or request.headers.get('X-CSRF-Token')
            if not token or not hmac.compare_digest(token, _generate_csrf_token()):
                abort(403)

    def _generate_csrf_token():
        if '_csrf_token' not in session:
            session['_csrf_token'] = hashlib.sha256(os.urandom(32)).hexdigest()
        return session['_csrf_token']

    @app.context_processor
    def inject_csrf_token():
        return dict(csrf_token=_generate_csrf_token)

    # Register blueprints
    from .routes_auth import auth_bp
    from .routes_main import main_bp
    from .routes_awr import awr_bp
    from .routes_knowledge import kb_bp
    from .routes_admin import admin_bp
    from .routes_projects import projects_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(awr_bp)
    app.register_blueprint(kb_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(projects_bp)

    # Custom Jinja2 filters
    @app.template_filter('fromjson')
    def fromjson_filter(value):
        if value:
            return json.loads(value)
        return {}

    with app.app_context():
        db.create_all()
        _seed_defaults(app)

    return app


def _seed_defaults(app):
    """Create default admin user and seed/sync knowledge rules."""
    from .awr_engine import BUILTIN_RULES, BUILTIN_RULES_VERSION

    # Default admin
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', email='admin@local', role='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()

    # Seed / incremental-sync builtin knowledge rules
    current_version = SystemSetting.get('builtin_rules_version', '0')
    if int(current_version) < BUILTIN_RULES_VERSION:
        # Build lookup of existing builtin rules by name
        existing = {r.name: r for r in KnowledgeRule.query.filter_by(source='builtin').all()}
        code_names = set()
        for rule in BUILTIN_RULES:
            code_names.add(rule['name'])
            if rule['name'] in existing:
                # Update existing rule in-place (keep hit_count & confidence)
                entry = existing[rule['name']]
                entry.category = rule['category']
                entry.conditions_json = json.dumps(rule['conditions'], ensure_ascii=False)
                entry.root_cause = rule['root_cause']
                entry.solution = rule['solution']
                entry.severity = rule['severity']
                entry.is_active = True
                entry.status = 'active'
            else:
                # New rule
                entry = KnowledgeRule(
                    name=rule['name'],
                    category=rule['category'],
                    conditions_json=json.dumps(rule['conditions'], ensure_ascii=False),
                    root_cause=rule['root_cause'],
                    solution=rule['solution'],
                    severity=rule['severity'],
                    confidence=0.9,
                    status='active',
                    source='builtin',
                    is_active=True,
                )
                db.session.add(entry)
        # Soft-delete builtin rules removed from code
        for name, entry in existing.items():
            if name not in code_names:
                entry.status = 'stale'
                entry.is_active = False
        SystemSetting.set('builtin_rules_version', str(BUILTIN_RULES_VERSION))
        db.session.commit()

    # Seed default system settings
    if not SystemSetting.get('llm_provider'):
        SystemSetting.set('llm_provider', 'none')
