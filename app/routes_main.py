from flask import Blueprint, render_template
from flask_login import login_required, current_user
from .models import AWRReport, AWRAnalysisResult, KnowledgeRule, GitHubProject

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    projects = GitHubProject.query.filter_by(is_private=False).order_by(GitHubProject.display_order).all()
    return render_template('index.html', projects=projects)


@main_bp.route('/dashboard')
@login_required
def dashboard():
    report_count = AWRReport.query.count()
    analysis_count = AWRAnalysisResult.query.count()
    kb_count = KnowledgeRule.query.filter_by(is_active=True).count()
    recent_reports = AWRReport.query.order_by(AWRReport.created_at.desc()).limit(5).all()
    recent_analyses = AWRAnalysisResult.query.order_by(AWRAnalysisResult.created_at.desc()).limit(5).all()

    if current_user.role == 'viewer':
        report_count = AWRReport.query.filter_by(upload_user_id=current_user.id).count()
        recent_reports = AWRReport.query.filter_by(upload_user_id=current_user.id)\
            .order_by(AWRReport.created_at.desc()).limit(5).all()

    return render_template('dashboard.html',
                           report_count=report_count,
                           analysis_count=analysis_count,
                           kb_count=kb_count,
                           recent_reports=recent_reports,
                           recent_analyses=recent_analyses)
