from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


# ==============================================================================
# User Model
# ==============================================================================

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

    awr_reports = db.relationship('AWRReport', backref='uploader', lazy='dynamic',
                                  foreign_keys='AWRReport.upload_user_id')
    analyses = db.relationship('AWRAnalysisResult', backref='analyst', lazy='dynamic',
                               foreign_keys='AWRAnalysisResult.analyst_id')

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


# ==============================================================================
# AWR Report - Upload record for AWR HTML files
# ==============================================================================

class AWRReport(db.Model):
    __tablename__ = 'awr_reports'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer)

    # Database instance info extracted from the AWR report
    db_name = db.Column(db.String(100), index=True)
    instance_name = db.Column(db.String(100), index=True)
    db_version = db.Column(db.String(50))
    host_name = db.Column(db.String(100))
    platform = db.Column(db.String(100))

    # Snapshot information
    snap_begin_id = db.Column(db.Integer)
    snap_end_id = db.Column(db.Integer)
    snap_begin_time = db.Column(db.DateTime)
    snap_end_time = db.Column(db.DateTime)
    elapsed_seconds = db.Column(db.Float)

    # Hardware info
    cpu_count = db.Column(db.Integer, nullable=True)

    # Store the original HTML content
    raw_html = db.Column(db.Text)

    # Ownership and status
    upload_user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    status = db.Column(db.String(20), default='uploaded', index=True)  # uploaded, parsed, analyzed, error

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships with cascade delete
    metrics = db.relationship('AWRMetric', backref='report', lazy='dynamic',
                              cascade='all, delete-orphan')
    problems = db.relationship('AWRProblem', backref='report', lazy='dynamic',
                               cascade='all, delete-orphan')
    analyses = db.relationship('AWRAnalysisResult', backref='report', lazy='dynamic',
                               cascade='all, delete-orphan')
    baselines = db.relationship('AWRBaseline', backref='report', lazy='dynamic')

    def __repr__(self):
        return f'<AWRReport {self.title}>'


# ==============================================================================
# AWR Metric - Unified metrics table for all metric types
# ==============================================================================

class AWRMetric(db.Model):
    __tablename__ = 'awr_metrics'
    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey('awr_reports.id'), nullable=False, index=True)

    # Metric classification
    metric_type = db.Column(db.String(50), nullable=False, index=True)
    # Types: load_profile, wait_event, sql_stat, io_stat, memory, efficiency,
    #         redo, os_stat, rac, segment, advisory, parse_stat

    metric_name = db.Column(db.String(200), nullable=False)
    metric_value = db.Column(db.Float, nullable=True)
    metric_unit = db.Column(db.String(50), nullable=True)  # e.g. '%DB Time', 'ms', 'per sec', 'per txn'

    # For non-numeric data like SQL text, SQL_ID
    metric_text = db.Column(db.Text, nullable=True)

    # Additional structured data as JSON string
    extra_json = db.Column(db.Text, nullable=True)

    # For ordered items like Top SQL
    rank_order = db.Column(db.Integer, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Composite index for common queries
    __table_args__ = (
        db.Index('ix_awr_metrics_report_type', 'report_id', 'metric_type'),
    )

    def __repr__(self):
        return f'<AWRMetric {self.metric_type}:{self.metric_name}={self.metric_value}>'


# ==============================================================================
# AWR Problem - Identified problems per analysis
# ==============================================================================

class AWRProblem(db.Model):
    __tablename__ = 'awr_problems'
    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey('awr_reports.id'), nullable=False, index=True)
    analysis_id = db.Column(db.Integer, db.ForeignKey('awr_analysis_results.id'), nullable=True)

    # Problem classification
    problem_type = db.Column(db.String(50), nullable=False)
    # Types: wait_event, sql, io, memory, redo, rac, parse, general

    title = db.Column(db.String(300), nullable=False)
    severity = db.Column(db.String(20), nullable=False, default='medium')  # low, medium, high, critical
    health_level = db.Column(db.String(20), nullable=False, default='warning')  # healthy, warning, serious

    # Related metric info
    metric_name = db.Column(db.String(200))
    metric_value = db.Column(db.Float, nullable=True)
    metric_unit = db.Column(db.String(50), nullable=True)

    # Thresholds used for evaluation
    threshold_warning = db.Column(db.Float, nullable=True)
    threshold_serious = db.Column(db.Float, nullable=True)

    # Human-readable evidence string
    evidence = db.Column(db.Text)

    # JSON array of related metric references
    related_metrics_json = db.Column(db.Text, nullable=True)

    # JSON describing the root cause chain
    correlation_chain = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationship to analysis
    analysis = db.relationship('AWRAnalysisResult', backref=db.backref('problems', lazy='dynamic'))

    def __repr__(self):
        return f'<AWRProblem [{self.severity}] {self.title}>'


# ==============================================================================
# AWR Analysis Result - Analysis output (rule-based, LLM, or combined)
# ==============================================================================

class AWRAnalysisResult(db.Model):
    __tablename__ = 'awr_analysis_results'
    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey('awr_reports.id'), nullable=False, index=True)

    # Analysis metadata
    analysis_type = db.Column(db.String(50), nullable=False, default='rule')  # rule, llm, combined
    health_level = db.Column(db.String(20), nullable=False, default='healthy')  # healthy, warning, serious

    # Analysis output
    summary = db.Column(db.Text)
    problems_json = db.Column(db.Text)  # Structured problems JSON
    recommendations_json = db.Column(db.Text)  # Structured recommendations
    correlation_findings_json = db.Column(db.Text)  # Cross-metric findings

    # LLM-specific fields
    llm_provider = db.Column(db.String(50), nullable=True)
    llm_raw_response = db.Column(db.Text, nullable=True)
    llm_structured_json = db.Column(db.Text, nullable=True)  # Parsed LLM JSON output
    learned_patterns_json = db.Column(db.Text, nullable=True)  # Patterns LLM suggested

    # Who ran this analysis
    analyst_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<AWRAnalysisResult report={self.report_id} type={self.analysis_type}>'


# ==============================================================================
# Knowledge Rule - Self-learning rules for pattern matching
# ==============================================================================

class KnowledgeRule(db.Model):
    __tablename__ = 'knowledge_rules'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)

    # Rule classification
    category = db.Column(db.String(50), nullable=False, index=True)
    # Categories: wait_event, sql, io, memory, redo, rac, parse, general

    # JSON array of structured conditions
    # Example: [{"metric": "pct_db_time", "op": ">", "value": 30, "event": "db file sequential read"}]
    conditions_json = db.Column(db.Text, nullable=False)

    root_cause = db.Column(db.Text)
    solution = db.Column(db.Text)
    severity = db.Column(db.String(20), nullable=False, default='medium')  # low, medium, high, critical

    # Learning metrics
    confidence = db.Column(db.Float, default=0.5)
    status = db.Column(db.String(20), nullable=False, default='candidate', index=True)
    # Status: candidate, observed, active, stale, rejected
    source = db.Column(db.String(20), nullable=False, default='builtin')  # builtin, learned, llm, manual

    # Hit tracking
    hit_count = db.Column(db.Integer, default=0)
    miss_streak = db.Column(db.Integer, default=0)  # Consecutive analyses without a hit
    last_hit_at = db.Column(db.DateTime, nullable=True)

    # Active flag: computed from status, active if status in ('observed', 'active')
    is_active = db.Column(db.Boolean, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    hit_logs = db.relationship('KnowledgeHitLog', backref='rule', lazy='dynamic',
                               cascade='all, delete-orphan')

    def __repr__(self):
        return f'<KnowledgeRule [{self.category}] {self.name}>'


# ==============================================================================
# Knowledge Hit Log - Records of when rules matched reports
# ==============================================================================

class KnowledgeHitLog(db.Model):
    __tablename__ = 'knowledge_hit_logs'
    id = db.Column(db.Integer, primary_key=True)
    rule_id = db.Column(db.Integer, db.ForeignKey('knowledge_rules.id'), nullable=False, index=True)
    report_id = db.Column(db.Integer, db.ForeignKey('awr_reports.id'), nullable=False, index=True)

    # Which metrics triggered this rule (JSON)
    hit_metrics_json = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationship to report
    report = db.relationship('AWRReport', backref=db.backref('knowledge_hits', lazy='dynamic'))

    def __repr__(self):
        return f'<KnowledgeHitLog rule={self.rule_id} report={self.report_id}>'


# ==============================================================================
# AWR Baseline - Historical baseline metrics for comparison
# ==============================================================================

class AWRBaseline(db.Model):
    __tablename__ = 'awr_baselines'
    id = db.Column(db.Integer, primary_key=True)

    # Identifies which database/instance this baseline is for
    db_name = db.Column(db.String(100), nullable=False)
    instance_name = db.Column(db.String(100), nullable=False)

    # Metric identification
    metric_name = db.Column(db.String(200), nullable=False)
    metric_type = db.Column(db.String(50), nullable=False)

    # Statistical values
    avg_value = db.Column(db.Float, nullable=False)
    min_value = db.Column(db.Float, nullable=False)
    max_value = db.Column(db.Float, nullable=False)
    p95_value = db.Column(db.Float, nullable=True)
    sample_count = db.Column(db.Integer, default=0)

    # Optional FK to the report that last updated this baseline
    report_id = db.Column(db.Integer, db.ForeignKey('awr_reports.id'), nullable=True)

    last_updated = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Composite indexes for frequent lookups
    __table_args__ = (
        db.Index('ix_awr_baselines_db_instance', 'db_name', 'instance_name'),
        db.Index('ix_awr_baselines_lookup', 'db_name', 'instance_name', 'metric_name', 'metric_type'),
    )

    def __repr__(self):
        return f'<AWRBaseline {self.db_name}/{self.instance_name} {self.metric_name}>'


# ==============================================================================
# System Setting - Key/value store for configuration and thresholds
# ==============================================================================

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


# ==============================================================================
# GitHub Project - Tracked GitHub repositories
# ==============================================================================

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


# ==============================================================================
# Audit Log - Track user actions
# ==============================================================================

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    action = db.Column(db.String(100), nullable=False)
    detail = db.Column(db.Text)
    ip_address = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref='audit_logs')
