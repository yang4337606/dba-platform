import os
import json
from flask import Flask
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
    """Create default admin user and seed knowledge rules."""
    from .awr_engine import BUILTIN_RULES

    # Default admin
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', email='admin@local', role='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()

    # Seed builtin knowledge rules
    if KnowledgeRule.query.filter_by(source='builtin').count() == 0:
        for rule in BUILTIN_RULES:
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
        db.session.commit()

    # Seed default system settings
    if not SystemSetting.get('llm_provider'):
        SystemSetting.set('llm_provider', 'none')
