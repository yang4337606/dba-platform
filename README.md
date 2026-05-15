# 数据库智能诊断平台

本项目已从复杂 DBA 管理平台重构为插件式数据库智能诊断平台。

第一阶段完整支持 Oracle AWR HTML 报告分析。用户上传报告后，系统输出类似 ChatGPT 回复的诊断内容：

1. 诊断结论
2. 异常发现
3. 原因分析
4. 证据
5. 处理建议

## 架构

- `app/core/`：统一诊断模型、Analyzer 接口、注册表、规则引擎、渲染器
- `app/analyzers/oracle_awr/`：Oracle AWR parser、metrics、rules、diagnosis
- `app/analyzers/oracle_ash/`：Oracle ASH 预留插件
- `app/analyzers/mysql_optimize/`：MySQL 优化预留插件
- `app/analyzers/postgresql_optimize/`：PostgreSQL 优化预留插件
- `legacy/`：旧登录、后台、知识库、复杂 AWR 引擎、旧模板和旧测试

## 启动

```bash
pip install -r requirements.txt
python run.py
```

访问 `http://127.0.0.1:3000` 上传 Oracle AWR HTML 报告。

## 测试

```bash
pytest tests/ -v
```
