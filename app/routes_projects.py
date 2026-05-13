from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from .models import db, GitHubProject, AuditLog
from .i18n import t

projects_bp = Blueprint('projects', __name__, url_prefix='/projects')

# Hardcoded GitHub data from your account
GITHUB_REPOS = [
    {'name': 'ai-experiment-platform', 'description': 'AI 自动化实验平台 - 基于AI的全流程自动化测试平台', 'language': 'Python', 'url': 'https://github.com/yang4337606/ai-experiment-platform', 'stars': 0, 'is_private': False, 'category': 'ai'},
    {'name': 'pg-inspect-tool', 'description': '企业级PostgreSQL数据库巡检工具 - 许可证保护/自定义品牌/Word+PDF报告', 'language': 'Python', 'url': 'https://github.com/yang4337606/pg-inspect-tool', 'stars': 0, 'is_private': True, 'category': 'database'},
    {'name': 'mysql-optimizer', 'description': 'MySQL 优化诊断脚本 - 采集系统/数据库信息并生成离线 HTML 优化报告', 'language': 'Shell', 'url': 'https://github.com/yang4337606/mysql-optimizer', 'stars': 0, 'is_private': True, 'category': 'database'},
    {'name': 'mysql-inspect-tool', 'description': '企业级MySQL数据库巡检工具 - 许可证保护/自定义品牌/Word+PDF报告', 'language': 'Python', 'url': 'https://github.com/yang4337606/mysql-inspect-tool', 'stars': 0, 'is_private': True, 'category': 'database'},
    {'name': 'Elasticsearch_auto_scripts', 'description': 'Elasticsearch 自动化运维脚本集', 'language': 'Shell', 'url': 'https://github.com/yang4337606/Elasticsearch_auto_scripts', 'stars': 0, 'is_private': True, 'category': 'database'},
    {'name': 'PostgreSQL_AUTO_Scripts', 'description': 'PostgreSQL 自动化运维脚本集', 'language': 'Shell', 'url': 'https://github.com/yang4337606/PostgreSQL_AUTO_Scripts', 'stars': 0, 'is_private': True, 'category': 'database'},
    {'name': 'MySQLShellInstall', 'description': 'MySQL Shell 一键安装部署', 'language': 'Shell', 'url': 'https://github.com/yang4337606/MySQLShellInstall', 'stars': 0, 'is_private': True, 'category': 'database'},
    {'name': 'redis_auto_scripts', 'description': 'Redis 自动化运维脚本集', 'language': 'HTML', 'url': 'https://github.com/yang4337606/redis_auto_scripts', 'stars': 0, 'is_private': True, 'category': 'database'},
    {'name': 'MongoDBShellInstall', 'description': 'MongoDB 一键自动化安装脚本，支持单机/副本集双模式', 'language': 'HTML', 'url': 'https://github.com/yang4337606/MongoDBShellInstall', 'stars': 0, 'is_private': False, 'category': 'database'},
    {'name': 'Kafka_auto_Scripts', 'description': 'Kafka 自动化运维脚本集', 'language': 'Shell', 'url': 'https://github.com/yang4337606/Kafka_auto_Scripts', 'stars': 0, 'is_private': True, 'category': 'middleware'},
    {'name': 'HAProxy_Keepalived_Install', 'description': 'HAProxy + Keepalived 一键安装，支持单机/高可用双模式', 'language': 'Shell', 'url': 'https://github.com/yang4337606/HAProxy_Keepalived_Install', 'stars': 0, 'is_private': True, 'category': 'middleware'},
    {'name': 'Nacos_Consul_Install', 'description': 'Nacos / Consul 一键安装，服务注册与配置中心', 'language': 'Shell', 'url': 'https://github.com/yang4337606/Nacos_Consul_Install', 'stars': 0, 'is_private': True, 'category': 'middleware'},
    {'name': 'ZooKeeper_Auto_Install', 'description': 'ZooKeeper 一键自动化安装，支持单机/集群双模式', 'language': 'Shell', 'url': 'https://github.com/yang4337606/ZooKeeper_Auto_Install', 'stars': 0, 'is_private': True, 'category': 'middleware'},
    {'name': 'RabbitMQ_Auto_Install', 'description': 'RabbitMQ 一键自动化安装，支持单机/集群模式', 'language': 'Shell', 'url': 'https://github.com/yang4337606/RabbitMQ_Auto_Install', 'stars': 0, 'is_private': True, 'category': 'middleware'},
    {'name': 'JDK_Auto_Install', 'description': 'JDK 一键安装，支持多版本管理与切换', 'language': 'Shell', 'url': 'https://github.com/yang4337606/JDK_Auto_Install', 'stars': 0, 'is_private': True, 'category': 'system'},
    {'name': 'Linux_Init_Hardening', 'description': 'Linux 系统初始化与安全加固脚本，9大模块', 'language': 'Shell', 'url': 'https://github.com/yang4337606/Linux_Init_Hardening', 'stars': 0, 'is_private': True, 'category': 'system'},
    {'name': 'tomcat-optimize', 'description': 'Apache Tomcat 全版本优化脚本与建议报告', 'language': 'HTML', 'url': 'https://github.com/yang4337606/tomcat-optimize', 'stars': 0, 'is_private': False, 'category': 'middleware'},
]


@projects_bp.route('/')
def list_projects():
    projects = GitHubProject.query.order_by(GitHubProject.category, GitHubProject.display_order).all()
    categories = db.session.query(GitHubProject.category).distinct().all()
    return render_template('projects.html', projects=projects,
                           categories=[c[0] for c in categories if c[0]])


@projects_bp.route('/sync', methods=['POST'])
@login_required
def sync():
    if not current_user.is_admin:
        flash(t('admin_required'), 'error')
        return redirect(url_for('projects.list_projects'))

    for repo in GITHUB_REPOS:
        existing = GitHubProject.query.filter_by(name=repo['name']).first()
        if existing:
            existing.description = repo['description']
            existing.language = repo['language']
            existing.url = repo['url']
            existing.stars = repo['stars']
            existing.is_private = repo['is_private']
            existing.category = repo['category']
            existing.synced_at = datetime.utcnow()
        else:
            project = GitHubProject(
                name=repo['name'],
                description=repo['description'],
                language=repo['language'],
                url=repo['url'],
                stars=repo['stars'],
                is_private=repo['is_private'],
                category=repo['category'],
                synced_at=datetime.utcnow(),
            )
            db.session.add(project)

    db.session.add(AuditLog(user_id=current_user.id, action='sync_github',
                            ip_address=request.remote_addr))
    db.session.commit()
    flash(t('projects_synced', count=len(GITHUB_REPOS)), 'success')
    return redirect(url_for('projects.list_projects'))
