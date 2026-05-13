# app/i18n.py
# Lightweight i18n: dictionary-based translation with Flask session language switching.
# Usage in Python:  from app.i18n import t; t('login_failed')
# Usage in Jinja2:  {{ _('login_failed') }}  or  {{ _('user_created', username='admin') }}

from flask import session, request

DEFAULT_LANG = 'zh'
SUPPORTED_LANGS = ('zh', 'en')

# ---------------------------------------------------------------------------
# Translation catalogue
# Keys are grouped by module for readability; at runtime they are flat.
# Placeholders use Python str.format() syntax: {name}, {count}, {minutes}
# ---------------------------------------------------------------------------
MESSAGES = {
    'zh': {
        # ── auth ──
        'login_required': '请先登录',
        'login_failed': '用户名或密码错误',
        'rate_limited': '登录尝试过于频繁，请{minutes}分钟后再试',

        # ── admin ──
        'admin_required': '需要管理员权限',
        'username_exists': '用户名已存在',
        'user_created': '用户 {username} 已创建',
        'user_updated': '用户已更新',
        'cannot_delete_self': '不能删除当前登录用户',
        'user_deleted': '用户已删除',
        'settings_saved': '设置已保存',

        # ── awr upload / parse ──
        'no_file_selected': '请选择文件',
        'file_not_selected': '未选择文件',
        'invalid_file_format': '仅支持 HTML/HTM 格式的AWR报告（文本格式暂不支持）',
        'file_read_error': '文件读取失败: {error}',
        'awr_upload_success': 'AWR报告上传并解析成功',
        'awr_parse_error': 'AWR报告解析出错: {error}',

        # ── awr view / analyze ──
        'no_view_permission': '无权查看此报告',
        'no_analyze_permission': '无分析权限',
        'analysis_in_progress': '分析正在进行中，请稍后刷新查看结果',
        'analysis_submitted': '分析已提交，请稍后刷新查看结果',
        'no_view_access': '无权查看',
        'no_export_permission': '无权导出',
        'select_two_reports': '请选择两份报告进行对比',
        'admin_only_delete': '仅管理员可删除',
        'report_deleted': '报告已删除',
        'unknown_problem': 'Unknown Problem',

        # ── awr analysis summary ──
        'summary_database': '数据库: {db_name}/{instance_name}',
        'summary_version': '版本: {version}',
        'summary_snapshot': '快照: {begin_id} - {end_id}',
        'summary_duration': '持续时间: {seconds}秒',
        'summary_health_score': '健康评分: {score}/100 ({level})',
        'summary_problems_found': '发现问题: {count}个',
        'summary_sql_anti_patterns': 'SQL反模式: {count}个',
        'summary_param_suggestions': '参数建议: {count}个',
        'summary_advisory_suggestions': 'Advisory建议: {count}个',
        'summary_time_model_findings': '时间模型发现: {count}个',
        'summary_workload_type': '负载类型: {wtype}',
        'summary_llm_enhanced': '(含LLM增强分析)',

        # ── awr correlation / problems ──
        'sql_anti_pattern_title': 'SQL反模式: {pattern} (SQL_ID={sql_id})',
        'sql_snippet_evidence': '{description}\nSQL片段: {snippet}',
        'wait_class_title': 'Wait Class "{wclass}" 累计占 DB Time {pct:.1f}%',
        'wait_class_trigger': '{wclass} 类等待事件汇总',
        'wait_class_evidence': '{wclass} 类事件合计 {pct:.1f}% DB Time',
        'wait_class_root_cause': '{wclass} 类等待是主要性能瓶颈方向',
        'wait_class_suggestion': '重点关注 {wclass} 类下的各具体等待事件',

        # ── knowledge ──
        'no_permission': '无权限',
        'invalid_json': '条件JSON格式无效，请检查输入',
        'knowledge_added': '知识规则已添加',
        'knowledge_updated': '知识规则已更新',
        'knowledge_deleted': '知识规则已删除',

        # ── projects ──
        'projects_synced': '已同步 {count} 个项目',

        # ── navigation / base template ──
        'nav_dashboard': '控制台',
        'nav_awr_analysis': 'AWR分析',
        'nav_knowledge': '知识库',
        'nav_projects': '项目',
        'nav_admin': '管理后台',
        'nav_logout': '退出',
        'site_title': 'DBA工具平台',

        # ── login page ──
        'login_title': '登录 - DBA工具平台',
        'login_brand': 'DBA Platform',
        'login_tagline': 'Oracle AWR 分析 · 知识库 · 自动化运维',
        'label_username': '用户名',
        'label_password': '密码',
        'label_remember': '记住登录',
        'btn_login': '登录',

        # ── dashboard ──
        'dashboard_title': '控制台 - DBA平台',
        'dashboard_welcome': '欢迎回来，{username}',
        'btn_upload_awr': '上传AWR报告',
        'stat_awr_reports': 'AWR 报告',
        'stat_analyses': '分析报告',
        'stat_knowledge': '知识条目',
        'recent_awr': '最近 AWR 报告',
        'btn_view_all': '查看全部',
        'th_title': '标题',
        'th_database': '数据库',
        'th_status': '状态',
        'th_time': '时间',
        'status_analyzed': '已分析',
        'status_parsed': '已解析',
        'status_error': '错误',
        'empty_awr_reports': '暂无AWR报告',
        'recent_analyses': '最近分析',
        'label_knowledge_base': '知识库',
        'th_report': '报告',
        'th_health': '健康',
        'th_type': '类型',
        'label_rule': '规则',
        'empty_analyses': '暂无分析报告',

        # ── index / landing page ──
        'landing_slogan': 'DBA · DevOps · Automation',
        'landing_desc': '数据库运维自动化工具平台',
        'landing_detail': '专业的Oracle AWR分析引擎，自学习知识库，覆盖MySQL/PostgreSQL/MongoDB/Redis全栈数据库运维',
        'btn_login_system': '登录系统',
        'btn_view_projects': '查看项目',
        'label_open_source': '开源项目',
        'no_description': '暂无描述',
        'empty_projects_landing': '暂无公开项目，请管理员同步GitHub数据',

        # ── projects page ──
        'projects_title': '项目',
        'projects_github': 'GitHub 项目',
        'projects_desc': '数据库运维自动化工具集',
        'btn_sync_github': '同步 GitHub',
        'label_all': '全部',
        'label_private': 'Private',
        'empty_projects': '暂无项目数据，请管理员同步GitHub',

        # ── admin index ──
        'admin_title': '管理后台',
        'admin_subtitle': '系统概览与管理',
        'stat_users': '用户数',
        'stat_awr': 'AWR报告',
        'stat_analysis': '分析报告',
        'stat_kb': '知识条目',
        'stat_learned': '自学习条目',
        'stat_github': 'GitHub项目',
        'link_user_mgmt': '用户管理',
        'link_settings': '系统设置',
        'link_audit_log': '审计日志',
        'link_kb_stats': '知识库统计',
        'admin_recent_logs': '最近审计日志',
        'th_user': '用户',
        'th_action': '操作',
        'th_detail': '详情',
        'th_ip': 'IP',

        # ── admin logs ──
        'audit_log_title': '审计日志',
        'audit_log_subtitle': '系统操作记录',
        'btn_back_admin': '返回管理',
        'th_ip_address': 'IP地址',

        # ── admin settings ──
        'settings_title': '系统设置',
        'settings_subtitle': 'LLM集成配置与站点设置',
        'btn_back': '返回',
        'section_llm': '大模型集成',
        'label_llm_provider': 'LLM 提供商',
        'llm_none': '未启用',
        'llm_openai': 'OpenAI',
        'llm_custom': '自定义 (兼容OpenAI API)',
        'label_api_key': 'API Key',
        'placeholder_api_key': 'sk-... (留空保持现有密钥不变)',
        'label_api_url': 'API URL (自定义时填写)',
        'label_model_name': '模型名称',
        'llm_help_1': '说明：配置LLM后，在AWR分析时可勾选"LLM增强"，系统会将解析后的AWR数据发送给大模型，获取更专业的分析建议。',
        'llm_help_2': '支持OpenAI兼容API格式，包括国内各类大模型服务。',
        'section_site': '站点设置',
        'label_site_title': '站点标题',
        'default_site_title': 'DBA工具平台',
        'label_site_desc': '站点描述',
        'default_site_desc': 'Oracle AWR分析 · 知识库 · 自动化运维',
        'section_learning': '自学习机制说明',
        'learning_note_1': '1. 模式识别学习：每次分析AWR报告时，系统自动提取未识别的等待事件模式，作为新知识条目（置信度初始30%）。',
        'learning_note_2': '2. 置信度增长：每当知识条目在新报告中被匹配到，匹配计数+1，置信度自动提升（每次+2%，上限100%）。',
        'learning_note_3': '3. LLM增强：启用大模型后，可将AWR数据发送给AI获取专业分析，分析结果可手动录入知识库。',
        'learning_note_4': '4. 人工修正：分析师可手动添加、编辑、启用/禁用知识条目，修正自学习结果。',
        'btn_save_settings': '保存设置',

        # ── admin user form ──
        'edit_user': '编辑用户',
        'add_user': '添加用户',
        'label_email': '邮箱',
        'label_password_hint': '密码',
        'label_password_edit_hint': '(留空不修改)',
        'label_role': '角色',
        'label_account_active': '账户启用',
        'btn_save': '保存',

        # ── admin users ──
        'user_mgmt_title': '用户管理',
        'user_mgmt_subtitle': '管理系统用户与权限',
        'btn_add_user': '添加用户',
        'th_id': 'ID',
        'th_email': '邮箱',
        'th_role': '角色',
        'th_last_login': '最后登录',
        'th_created_at': '创建时间',
        'th_operations': '操作',
        'status_active': '活跃',
        'status_disabled': '禁用',
        'never_logged_in': '从未',
        'btn_edit': '编辑',
        'confirm_delete_user': '确认删除用户 {username}？',
        'btn_delete': '删除',
        'section_role_desc': '角色说明',
        'role_admin': '管理员',
        'role_admin_desc': '全部权限：用户管理、系统设置、AWR上传/分析/删除、知识库管理',
        'role_analyst': '分析师',
        'role_analyst_desc': 'AWR上传与分析、知识库编辑、查看所有报告',
        'role_viewer': '查看者',
        'role_viewer_desc': '仅查看自己上传的报告和分析结果',

        # ── AWR report list ──
        'awr_list_title': 'AWR报告列表',
        'awr_list_heading': 'AWR 报告',
        'awr_list_subtitle': 'Oracle AWR报告管理与分析',
        'btn_upload_report': '上传报告',
        'th_instance': '实例',
        'th_snap_range': '快照范围',
        'th_upload_time': '上传时间',
        'btn_view': '查看',
        'confirm_delete_report': '确认删除此报告？',
        'empty_awr_list': '暂无AWR报告',
        'btn_upload_first': '上传第一份报告',

        # ── AWR upload ──
        'awr_upload_title': '上传AWR报告',
        'awr_upload_heading': '上传 AWR 报告',
        'awr_upload_subtitle': '支持 Oracle AWR HTML 格式报告',
        'btn_back_list': '返回列表',
        'label_report_title': '报告标题',
        'placeholder_report_title': '例: PROD数据库-20260512快照',
        'label_awr_file': 'AWR报告文件',
        'upload_drop_hint': '点击或拖拽文件到此处',
        'upload_format_hint': '支持 .html / .htm 格式，最大 50MB',
        'btn_upload_parse': '上传并解析',
        'how_to_generate': '如何生成AWR报告',
        'generate_instruction': '在Oracle数据库中执行以下命令生成AWR HTML报告：',

        # ── AWR view ──
        'label_unknown': '未知',
        'label_llm_enhanced': 'LLM增强',
        'btn_run_analysis': '执行分析',
        'btn_export_csv': '导出CSV',
        'btn_compare': '对比分析',
        'label_version': '版本',
        'label_host': '主机',
        'label_elapsed': '采集时长',
        'section_top_waits': 'Top 等待事件',
        'th_event_name': '事件名称',
        'th_pct_db_time': '%DB Time',
        'th_unit': '单位',
        'th_avg_wait': '平均等待',
        'section_load_profile': '负载概况',
        'th_metric': '指标',
        'th_value': '值',
        'section_efficiency': '实例效率',
        'th_value_pct': '值(%)',
        'section_time_model': '时间模型',
        'th_stat_name': '统计项',
        'th_time_s': '时间(s)',
        'section_advisory': '建议信息',
        'th_advisory_name': '建议名称',
        'section_wait_histogram': '等待直方图',
        'th_event': '事件',
        'section_analysis_records': '分析记录',
        'label_auto': '自动',
        'btn_view_analysis': '查看分析',
        'label_efficiency_pct': '效率%',

        # ── AWR analysis ──
        'analysis_report_title': '分析报告 #{id}',
        'btn_export_json': '导出JSON',
        'btn_back_report': '返回报告',
        'label_composite_score': '综合评分',
        'label_health_assessment': '健康评估',
        'health_good': '数据库运行状态良好',
        'health_warning': '存在需要关注的性能问题',
        'health_serious': '存在严重性能瓶颈，需要立即处理',
        'section_workload_type': '负载类型识别',
        'label_confidence': '置信度',
        'label_threshold_adjustments': '已应用{count}项阈值调整',
        'label_classification_basis': '识别依据',
        'section_overview': '概览',
        'section_problems_found': '发现问题',
        'label_warning_threshold': '关注阈值:',
        'label_serious_threshold': '严重阈值:',
        'section_time_model_analysis': '时间模型分析',
        'th_component': '组件',
        'th_finding': '发现',
        'th_severity': '严重程度',
        'section_correlation': '关联分析',
        'section_advisory_recommendations': 'Advisory 建议',
        'th_advisory_type': 'Advisory 类型',
        'th_current_size': '当前大小',
        'th_recommended_size': '建议大小',
        'th_benefit': '收益说明',
        'section_param_optimization': '参数优化建议',
        'th_parameter': '参数',
        'th_suggestion': '建议',
        'th_description': '说明',
        'th_trigger': '触发条件',
        'section_version_diag': '版本诊断信息',
        'label_version_info': '版本信息',
        'section_histogram_analysis': '等待直方图分析',
        'th_pattern': '模式',
        'th_p95_bucket': 'P95 Bucket',
        'th_p99_bucket': 'P99 Bucket',
        'section_llm_analysis': 'LLM 增强分析',
        'label_ai_summary': 'AI 摘要',
        'label_ai_problems': 'AI 发现的问题',

        # ── AWR compare ──
        'compare_title': 'AWR报告对比',
        'compare_heading': 'AWR报告对比分析',
        'label_baseline_report': '基准报告 (变更前)',
        'label_compare_report': '对比报告 (变更后)',
        'placeholder_select_report': '选择报告...',
        'btn_start_compare': '开始对比分析',
        'compare_result_title': 'AWR对比结果',
        'compare_result_heading': 'AWR报告对比结果',
        'btn_reselect': '重新选择',
        'label_baseline_a': '基准报告 (A)',
        'label_compare_b': '对比报告 (B)',
        'label_snap_range': '快照范围',
        'section_load_change': '负载概况变化',
        'th_report_a': '报告A',
        'th_report_b': '报告B',
        'th_change_pct': '变化%',
        'section_wait_change': '等待事件变化',
        'th_change': '变化',
        'section_efficiency_change': '实例效率变化',
        'section_key_metrics': '关键指标摘要',
        'section_memory_change': '内存统计变化',
        'section_io_change': 'IO统计变化',
        'section_time_model_change': '时间模型变化',
        'empty_compare_data': '暂无可对比的指标数据。请确认两份报告均已解析完成。',

        # ── knowledge list ──
        'kb_title': '知识库',
        'kb_subtitle': 'AWR分析规则与经验积累，支持自学习',
        'btn_stats': '统计',
        'btn_add_knowledge': '添加知识',
        'th_category': '分类',
        'th_name': '名称',
        'th_severity_level': '严重级别',
        'th_source': '来源',
        'th_match_count': '匹配次数',
        'th_confidence': '置信度',
        'th_enabled': '启用',
        'source_learned': '自学习',
        'source_manual': '手动',
        'source_builtin': '内置',
        'label_enabled': '启用',
        'label_disabled': '禁用',
        'confirm_delete': '确认删除？',
        'empty_knowledge': '暂无知识条目',

        # ── knowledge edit ──
        'edit_knowledge': '编辑知识条目',
        'add_knowledge': '添加知识条目',
        'label_conditions_json': '条件 (JSON)',
        'label_root_cause': '根因分析',
        'label_solution': '解决方案',
        'label_enable_rule': '启用此规则',

        # ── knowledge stats ──
        'kb_stats_title': '知识库统计',
        'kb_stats_subtitle': '自学习效果与知识覆盖',
        'btn_back_kb': '返回知识库',
        'label_total_entries': '总条目数',
        'section_by_category': '按分类分布',
        'section_by_status': '按状态分布',
        'section_top_matched': '高频匹配 Top 10',
        'label_matches': '匹配',
        'empty_matches': '暂无匹配记录',
    },

    'en': {
        # ── auth ──
        'login_required': 'Please log in first',
        'login_failed': 'Invalid username or password',
        'rate_limited': 'Too many login attempts, please try again in {minutes} minutes',

        # ── admin ──
        'admin_required': 'Admin privileges required',
        'username_exists': 'Username already exists',
        'user_created': 'User {username} created',
        'user_updated': 'User updated',
        'cannot_delete_self': 'Cannot delete the currently logged-in user',
        'user_deleted': 'User deleted',
        'settings_saved': 'Settings saved',

        # ── awr upload / parse ──
        'no_file_selected': 'Please select a file',
        'file_not_selected': 'No file selected',
        'invalid_file_format': 'Only HTML/HTM AWR reports are supported (text format not yet supported)',
        'file_read_error': 'File read failed: {error}',
        'awr_upload_success': 'AWR report uploaded and parsed successfully',
        'awr_parse_error': 'AWR report parsing error: {error}',

        # ── awr view / analyze ──
        'no_view_permission': 'No permission to view this report',
        'no_analyze_permission': 'No analysis permission',
        'analysis_in_progress': 'Analysis in progress, please refresh later',
        'analysis_submitted': 'Analysis submitted, please refresh later for results',
        'no_view_access': 'No access to view',
        'no_export_permission': 'No export permission',
        'select_two_reports': 'Please select two reports to compare',
        'admin_only_delete': 'Only admins can delete',
        'report_deleted': 'Report deleted',
        'unknown_problem': 'Unknown Problem',

        # ── awr analysis summary ──
        'summary_database': 'Database: {db_name}/{instance_name}',
        'summary_version': 'Version: {version}',
        'summary_snapshot': 'Snapshot: {begin_id} - {end_id}',
        'summary_duration': 'Duration: {seconds}s',
        'summary_health_score': 'Health Score: {score}/100 ({level})',
        'summary_problems_found': 'Problems Found: {count}',
        'summary_sql_anti_patterns': 'SQL Anti-patterns: {count}',
        'summary_param_suggestions': 'Parameter Suggestions: {count}',
        'summary_advisory_suggestions': 'Advisory Suggestions: {count}',
        'summary_time_model_findings': 'Time Model Findings: {count}',
        'summary_workload_type': 'Workload Type: {wtype}',
        'summary_llm_enhanced': '(with LLM enhanced analysis)',

        # ── awr correlation / problems ──
        'sql_anti_pattern_title': 'SQL Anti-pattern: {pattern} (SQL_ID={sql_id})',
        'sql_snippet_evidence': '{description}\nSQL Snippet: {snippet}',
        'wait_class_title': 'Wait Class "{wclass}" accounts for {pct:.1f}% of DB Time',
        'wait_class_trigger': '{wclass} wait events summary',
        'wait_class_evidence': '{wclass} events total {pct:.1f}% of DB Time',
        'wait_class_root_cause': '{wclass} waits are the main performance bottleneck',
        'wait_class_suggestion': 'Focus on specific wait events under {wclass} class',

        # ── knowledge ──
        'no_permission': 'No permission',
        'invalid_json': 'Invalid JSON format in conditions, please check input',
        'knowledge_added': 'Knowledge rule added',
        'knowledge_updated': 'Knowledge rule updated',
        'knowledge_deleted': 'Knowledge rule deleted',

        # ── projects ──
        'projects_synced': 'Synced {count} projects',

        # ── navigation / base template ──
        'nav_dashboard': 'Dashboard',
        'nav_awr_analysis': 'AWR Analysis',
        'nav_knowledge': 'Knowledge Base',
        'nav_projects': 'Projects',
        'nav_admin': 'Admin',
        'nav_logout': 'Logout',
        'site_title': 'DBA Platform',

        # ── login page ──
        'login_title': 'Login - DBA Platform',
        'login_brand': 'DBA Platform',
        'login_tagline': 'Oracle AWR Analysis · Knowledge Base · Automated Ops',
        'label_username': 'Username',
        'label_password': 'Password',
        'label_remember': 'Remember me',
        'btn_login': 'Login',

        # ── dashboard ──
        'dashboard_title': 'Dashboard - DBA Platform',
        'dashboard_welcome': 'Welcome back, {username}',
        'btn_upload_awr': 'Upload AWR Report',
        'stat_awr_reports': 'AWR Reports',
        'stat_analyses': 'Analyses',
        'stat_knowledge': 'Knowledge Entries',
        'recent_awr': 'Recent AWR Reports',
        'btn_view_all': 'View All',
        'th_title': 'Title',
        'th_database': 'Database',
        'th_status': 'Status',
        'th_time': 'Time',
        'status_analyzed': 'Analyzed',
        'status_parsed': 'Parsed',
        'status_error': 'Error',
        'empty_awr_reports': 'No AWR reports yet',
        'recent_analyses': 'Recent Analyses',
        'label_knowledge_base': 'Knowledge Base',
        'th_report': 'Report',
        'th_health': 'Health',
        'th_type': 'Type',
        'label_rule': 'Rule',
        'empty_analyses': 'No analyses yet',

        # ── index / landing page ──
        'landing_slogan': 'DBA · DevOps · Automation',
        'landing_desc': 'Database Operations Automation Platform',
        'landing_detail': 'Professional Oracle AWR analysis engine, self-learning knowledge base, covering MySQL/PostgreSQL/MongoDB/Redis full-stack database operations',
        'btn_login_system': 'Login',
        'btn_view_projects': 'View Projects',
        'label_open_source': 'Open Source Projects',
        'no_description': 'No description',
        'empty_projects_landing': 'No public projects yet, admin needs to sync GitHub data',

        # ── projects page ──
        'projects_title': 'Projects',
        'projects_github': 'GitHub Projects',
        'projects_desc': 'Database Operations Automation Toolkit',
        'btn_sync_github': 'Sync GitHub',
        'label_all': 'All',
        'label_private': 'Private',
        'empty_projects': 'No project data, admin needs to sync GitHub',

        # ── admin index ──
        'admin_title': 'Admin',
        'admin_subtitle': 'System Overview & Management',
        'stat_users': 'Users',
        'stat_awr': 'AWR Reports',
        'stat_analysis': 'Analyses',
        'stat_kb': 'Knowledge Entries',
        'stat_learned': 'Learned Entries',
        'stat_github': 'GitHub Projects',
        'link_user_mgmt': 'User Management',
        'link_settings': 'System Settings',
        'link_audit_log': 'Audit Log',
        'link_kb_stats': 'Knowledge Stats',
        'admin_recent_logs': 'Recent Audit Logs',
        'th_user': 'User',
        'th_action': 'Action',
        'th_detail': 'Detail',
        'th_ip': 'IP',

        # ── admin logs ──
        'audit_log_title': 'Audit Log',
        'audit_log_subtitle': 'System Operation Records',
        'btn_back_admin': 'Back to Admin',
        'th_ip_address': 'IP Address',

        # ── admin settings ──
        'settings_title': 'System Settings',
        'settings_subtitle': 'LLM Integration & Site Settings',
        'btn_back': 'Back',
        'section_llm': 'LLM Integration',
        'label_llm_provider': 'LLM Provider',
        'llm_none': 'Disabled',
        'llm_openai': 'OpenAI',
        'llm_custom': 'Custom (OpenAI-compatible API)',
        'label_api_key': 'API Key',
        'placeholder_api_key': 'sk-... (leave empty to keep current key)',
        'label_api_url': 'API URL (for custom provider)',
        'label_model_name': 'Model Name',
        'llm_help_1': 'Note: After configuring LLM, you can enable "LLM Enhanced" during AWR analysis. The system will send parsed AWR data to the LLM for professional analysis suggestions.',
        'llm_help_2': 'Supports OpenAI-compatible API format, including various domestic LLM services.',
        'section_site': 'Site Settings',
        'label_site_title': 'Site Title',
        'default_site_title': 'DBA Platform',
        'label_site_desc': 'Site Description',
        'default_site_desc': 'Oracle AWR Analysis · Knowledge Base · Automated Ops',
        'section_learning': 'Self-Learning Mechanism',
        'learning_note_1': '1. Pattern Recognition: Each AWR analysis automatically extracts unrecognized wait event patterns as new knowledge entries (initial confidence 30%).',
        'learning_note_2': '2. Confidence Growth: When a knowledge entry matches in a new report, its match count +1 and confidence increases (+2% each time, max 100%).',
        'learning_note_3': '3. LLM Enhancement: With LLM enabled, AWR data can be sent to AI for professional analysis; results can be manually added to the knowledge base.',
        'learning_note_4': '4. Manual Correction: Analysts can manually add, edit, enable/disable knowledge entries to correct self-learning results.',
        'btn_save_settings': 'Save Settings',

        # ── admin user form ──
        'edit_user': 'Edit User',
        'add_user': 'Add User',
        'label_email': 'Email',
        'label_password_hint': 'Password',
        'label_password_edit_hint': '(leave empty to keep unchanged)',
        'label_role': 'Role',
        'label_account_active': 'Account Active',
        'btn_save': 'Save',

        # ── admin users ──
        'user_mgmt_title': 'User Management',
        'user_mgmt_subtitle': 'Manage System Users & Permissions',
        'btn_add_user': 'Add User',
        'th_id': 'ID',
        'th_email': 'Email',
        'th_role': 'Role',
        'th_last_login': 'Last Login',
        'th_created_at': 'Created',
        'th_operations': 'Actions',
        'status_active': 'Active',
        'status_disabled': 'Disabled',
        'never_logged_in': 'Never',
        'btn_edit': 'Edit',
        'confirm_delete_user': 'Confirm delete user {username}?',
        'btn_delete': 'Delete',
        'section_role_desc': 'Role Descriptions',
        'role_admin': 'Admin',
        'role_admin_desc': 'Full access: user management, system settings, AWR upload/analysis/delete, knowledge management',
        'role_analyst': 'Analyst',
        'role_analyst_desc': 'AWR upload & analysis, knowledge editing, view all reports',
        'role_viewer': 'Viewer',
        'role_viewer_desc': 'View only own uploaded reports and analysis results',

        # ── AWR report list ──
        'awr_list_title': 'AWR Reports',
        'awr_list_heading': 'AWR Reports',
        'awr_list_subtitle': 'Oracle AWR Report Management & Analysis',
        'btn_upload_report': 'Upload Report',
        'th_instance': 'Instance',
        'th_snap_range': 'Snapshot Range',
        'th_upload_time': 'Upload Time',
        'btn_view': 'View',
        'confirm_delete_report': 'Confirm delete this report?',
        'empty_awr_list': 'No AWR reports',
        'btn_upload_first': 'Upload your first report',

        # ── AWR upload ──
        'awr_upload_title': 'Upload AWR Report',
        'awr_upload_heading': 'Upload AWR Report',
        'awr_upload_subtitle': 'Supports Oracle AWR HTML format reports',
        'btn_back_list': 'Back to List',
        'label_report_title': 'Report Title',
        'placeholder_report_title': 'e.g. PROD DB - 20260512 Snapshot',
        'label_awr_file': 'AWR Report File',
        'upload_drop_hint': 'Click or drag file here',
        'upload_format_hint': 'Supports .html / .htm format, max 50MB',
        'btn_upload_parse': 'Upload & Parse',
        'how_to_generate': 'How to Generate AWR Report',
        'generate_instruction': 'Execute the following command in Oracle database to generate AWR HTML report:',

        # ── AWR view ──
        'label_unknown': 'Unknown',
        'label_llm_enhanced': 'LLM Enhanced',
        'btn_run_analysis': 'Run Analysis',
        'btn_export_csv': 'Export CSV',
        'btn_compare': 'Compare',
        'label_version': 'Version',
        'label_host': 'Host',
        'label_elapsed': 'Elapsed Time',
        'section_top_waits': 'Top Wait Events',
        'th_event_name': 'Event Name',
        'th_pct_db_time': '%DB Time',
        'th_unit': 'Unit',
        'th_avg_wait': 'Avg Wait',
        'section_load_profile': 'Load Profile',
        'th_metric': 'Metric',
        'th_value': 'Value',
        'section_efficiency': 'Instance Efficiency',
        'th_value_pct': 'Value(%)',
        'section_time_model': 'Time Model',
        'th_stat_name': 'Statistic',
        'th_time_s': 'Time(s)',
        'section_advisory': 'Advisory Information',
        'th_advisory_name': 'Advisory Name',
        'section_wait_histogram': 'Wait Histogram',
        'th_event': 'Event',
        'section_analysis_records': 'Analysis Records',
        'label_auto': 'Auto',
        'btn_view_analysis': 'View Analysis',
        'label_efficiency_pct': 'Efficiency %',

        # ── AWR analysis ──
        'analysis_report_title': 'Analysis Report #{id}',
        'btn_export_json': 'Export JSON',
        'btn_back_report': 'Back to Report',
        'label_composite_score': 'Composite Score',
        'label_health_assessment': 'Health Assessment',
        'health_good': 'Database is running in good health',
        'health_warning': 'Performance issues require attention',
        'health_serious': 'Serious performance bottleneck, immediate action required',
        'section_workload_type': 'Workload Type Classification',
        'label_confidence': 'Confidence',
        'label_threshold_adjustments': '{count} threshold adjustments applied',
        'label_classification_basis': 'Classification Basis',
        'section_overview': 'Overview',
        'section_problems_found': 'Problems Found',
        'label_warning_threshold': 'Warning threshold:',
        'label_serious_threshold': 'Serious threshold:',
        'section_time_model_analysis': 'Time Model Analysis',
        'th_component': 'Component',
        'th_finding': 'Finding',
        'th_severity': 'Severity',
        'section_correlation': 'Correlation Analysis',
        'section_advisory_recommendations': 'Advisory Recommendations',
        'th_advisory_type': 'Advisory Type',
        'th_current_size': 'Current Size',
        'th_recommended_size': 'Recommended Size',
        'th_benefit': 'Benefit',
        'section_param_optimization': 'Parameter Optimization',
        'th_parameter': 'Parameter',
        'th_suggestion': 'Suggestion',
        'th_description': 'Description',
        'th_trigger': 'Trigger Condition',
        'section_version_diag': 'Version Diagnostics',
        'label_version_info': 'Version Info',
        'section_histogram_analysis': 'Wait Histogram Analysis',
        'th_pattern': 'Pattern',
        'th_p95_bucket': 'P95 Bucket',
        'th_p99_bucket': 'P99 Bucket',
        'section_llm_analysis': 'LLM Enhanced Analysis',
        'label_ai_summary': 'AI Summary',
        'label_ai_problems': 'Problems Found by AI',

        # ── AWR compare ──
        'compare_title': 'AWR Report Comparison',
        'compare_heading': 'AWR Report Comparison Analysis',
        'label_baseline_report': 'Baseline Report (Before)',
        'label_compare_report': 'Compare Report (After)',
        'placeholder_select_report': 'Select report...',
        'btn_start_compare': 'Start Comparison',
        'compare_result_title': 'AWR Comparison Result',
        'compare_result_heading': 'AWR Report Comparison Result',
        'btn_reselect': 'Reselect',
        'label_baseline_a': 'Baseline Report (A)',
        'label_compare_b': 'Compare Report (B)',
        'label_snap_range': 'Snapshot Range',
        'section_load_change': 'Load Profile Changes',
        'th_report_a': 'Report A',
        'th_report_b': 'Report B',
        'th_change_pct': 'Change %',
        'section_wait_change': 'Wait Event Changes',
        'th_change': 'Change',
        'section_efficiency_change': 'Instance Efficiency Changes',
        'section_key_metrics': 'Key Metrics Summary',
        'section_memory_change': 'Memory Statistics Changes',
        'section_io_change': 'IO Statistics Changes',
        'section_time_model_change': 'Time Model Changes',
        'empty_compare_data': 'No comparable metric data. Please confirm both reports have been parsed.',

        # ── knowledge list ──
        'kb_title': 'Knowledge Base',
        'kb_subtitle': 'AWR analysis rules and experience, with self-learning',
        'btn_stats': 'Stats',
        'btn_add_knowledge': 'Add Knowledge',
        'th_category': 'Category',
        'th_name': 'Name',
        'th_severity_level': 'Severity',
        'th_source': 'Source',
        'th_match_count': 'Match Count',
        'th_confidence': 'Confidence',
        'th_enabled': 'Enabled',
        'source_learned': 'Learned',
        'source_manual': 'Manual',
        'source_builtin': 'Built-in',
        'label_enabled': 'Enabled',
        'label_disabled': 'Disabled',
        'confirm_delete': 'Confirm delete?',
        'empty_knowledge': 'No knowledge entries yet',

        # ── knowledge edit ──
        'edit_knowledge': 'Edit Knowledge Entry',
        'add_knowledge': 'Add Knowledge Entry',
        'label_conditions_json': 'Conditions (JSON)',
        'label_root_cause': 'Root Cause Analysis',
        'label_solution': 'Solution',
        'label_enable_rule': 'Enable this rule',

        # ── knowledge stats ──
        'kb_stats_title': 'Knowledge Base Statistics',
        'kb_stats_subtitle': 'Self-learning effectiveness and knowledge coverage',
        'btn_back_kb': 'Back to Knowledge Base',
        'label_total_entries': 'Total Entries',
        'section_by_category': 'By Category',
        'section_by_status': 'By Status',
        'section_top_matched': 'Top 10 Matched',
        'label_matches': 'matches',
        'empty_matches': 'No match records yet',
    },
}


def get_lang():
    """Get current language from session, cookie, Accept-Language header, or default."""
    # 1. Explicit session override
    lang = session.get('lang')
    if lang in SUPPORTED_LANGS:
        return lang
    # 2. Query parameter (also persists to session)
    lang = request.args.get('lang')
    if lang in SUPPORTED_LANGS:
        session['lang'] = lang
        return lang
    # 3. Accept-Language header
    accept = request.accept_languages.best_match(SUPPORTED_LANGS)
    if accept:
        return accept
    return DEFAULT_LANG


def t(key, **kwargs):
    """Translate a message key to the current language.

    Supports Python format placeholders:
        t('user_created', username='admin')  ->  '用户 admin 已创建'
    """
    lang = get_lang()
    messages = MESSAGES.get(lang, MESSAGES[DEFAULT_LANG])
    text = messages.get(key)
    if text is None:
        # Fallback to default language, then to the raw key
        text = MESSAGES[DEFAULT_LANG].get(key, key)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError):
            pass  # Return unformatted if placeholders don't match
    return text


def init_i18n(app):
    """Register the translation function as a Jinja2 global and template context processor."""
    # Make _() available in all templates
    app.jinja_env.globals['_'] = t
    app.jinja_env.globals['get_lang'] = get_lang
    app.jinja_env.globals['SUPPORTED_LANGS'] = SUPPORTED_LANGS

    # Language switch route
    @app.route('/set-lang/<lang>')
    def set_lang(lang):
        if lang in SUPPORTED_LANGS:
            session['lang'] = lang
        # Redirect back to the referring page
        return __import__('flask').redirect(
            request.referrer or __import__('flask').url_for('main.dashboard')
        )
