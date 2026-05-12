from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='viewer')  # admin, analyst, viewer
    is_active_user = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)

    awr_reports = db.relationship('AWRReport', backref='uploader', lazy='dynamic')
    analyses = db.relationship('AWRAnalysis', backref='author', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def can_analyze(self):
        return self.role in ('admin', 'analyst')

    def __repr__(self):
        return f'<User {self.username}>'


class AWRReport(db.Model):
    __tablename__ = 'awr_reports'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer)
    db_name = db.Column(db.String(100))
    instance_name = db.Column(db.String(100))
    snap_begin = db.Column(db.String(50))
    snap_end = db.Column(db.String(50))
    snap_duration = db.Column(db.String(50))
    db_version = db.Column(db.String(50))
    host_name = db.Column(db.String(100))
    platform = db.Column(db.String(100))
    # Extracted raw metrics JSON
    raw_metrics = db.Column(db.Text)
    # Parsed sections JSON
    parsed_sections = db.Column(db.Text)
    upload_user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    status = db.Column(db.String(20), default='uploaded')  # uploaded, parsed, analyzed, error
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    analyses = db.relationship('AWRAnalysis', backref='report', lazy='dynamic', cascade='all, delete-orphan')
    knowledge_entries = db.relationship('KnowledgeBase', backref='source_report', lazy='dynamic')

    def __repr__(self):
        return f'<AWRReport {self.title}>'


class AWRAnalysis(db.Model):
    __tablename__ = 'awr_analyses'
    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey('awr_reports.id'), nullable=False)
    analysis_type = db.Column(db.String(50), default='auto')  # auto, manual, llm
    # Analysis content sections (JSON)
    summary = db.Column(db.Text)
    performance_score = db.Column(db.Float)
    wait_events_analysis = db.Column(db.Text)
    sql_analysis = db.Column(db.Text)
    io_analysis = db.Column(db.Text)
    memory_analysis = db.Column(db.Text)
    recommendations = db.Column(db.Text)
    full_report = db.Column(db.Text)
    # LLM-enhanced analysis
    llm_provider = db.Column(db.String(50))
    llm_analysis = db.Column(db.Text)
    analyst_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<AWRAnalysis report={self.report_id} type={self.analysis_type}>'


class KnowledgeBase(db.Model):
    __tablename__ = 'knowledge_base'
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50), nullable=False)  # wait_event, sql_pattern, io_pattern, memory, general
    title = db.Column(db.String(200), nullable=False)
    pattern = db.Column(db.Text)  # The pattern/condition that triggers this knowledge
    description = db.Column(db.Text, nullable=False)
    solution = db.Column(db.Text)
    severity = db.Column(db.String(20), default='medium')  # low, medium, high, critical
    match_count = db.Column(db.Integer, default=0)  # How many times this was matched - for learning
    confidence = db.Column(db.Float, default=0.5)  # Confidence score, improves with matches
    source = db.Column(db.String(50), default='builtin')  # builtin, learned, llm, manual
    source_report_id = db.Column(db.Integer, db.ForeignKey('awr_reports.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<KnowledgeBase {self.category}: {self.title}>'


class GitHubProject(db.Model):
    __tablename__ = 'github_projects'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    language = db.Column(db.String(50))
    url = db.Column(db.String(500))
    stars = db.Column(db.Integer, default=0)
    is_private = db.Column(db.Boolean, default=False)
    category = db.Column(db.String(50))  # database, middleware, system, ai, other
    display_order = db.Column(db.Integer, default=0)
    is_featured = db.Column(db.Boolean, default=False)
    synced_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<GitHubProject {self.name}>'


class SystemSetting(db.Model):
    __tablename__ = 'system_settings'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @staticmethod
    def get(key, default=None):
        setting = SystemSetting.query.filter_by(key=key).first()
        return setting.value if setting else default

    @staticmethod
    def set(key, value):
        setting = SystemSetting.query.filter_by(key=key).first()
        if setting:
            setting.value = value
        else:
            setting = SystemSetting(key=key, value=value)
            db.session.add(setting)
        db.session.commit()


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    action = db.Column(db.String(100), nullable=False)
    detail = db.Column(db.Text)
    ip_address = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='audit_logs')
