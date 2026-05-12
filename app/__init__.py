import os
from flask import Flask
from flask_login import LoginManager
from .config import Config
from .models import db, User

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

    with app.app_context():
        db.create_all()
        _seed_defaults(app)

    return app


def _seed_defaults(app):
    """Create default admin user and seed knowledge base."""
    from .models import KnowledgeBase, SystemSetting
    from .awr_engine import AWRAnalyzer

    # Default admin
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', email='admin@local', role='admin')
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()

    # Seed builtin knowledge
    if KnowledgeBase.query.filter_by(source='builtin').count() == 0:
        for rule in AWRAnalyzer.BUILTIN_RULES:
            entry = KnowledgeBase(
                category=rule['category'],
                title=rule['title'],
                pattern=rule.get('pattern', ''),
                description=rule['description'],
                solution=rule.get('solution', ''),
                severity=rule.get('severity', 'medium'),
                source='builtin',
                confidence=0.8,
            )
            db.session.add(entry)
        db.session.commit()
