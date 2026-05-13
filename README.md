# DBA Platform - Oracle AWR Report Analysis

Oracle AWR (Automatic Workload Repository) 报告智能分析平台，支持 AWR HTML 报告上传、自动解析、多维度评分、基线对比、关联分析和优化建议生成。

## Features

- **AWR 报告解析** - 自动解析 Oracle AWR HTML 报告，提取 28+ 关键数据段（Load Profile、Top Events、Top SQL、IO Stats、Memory、Wait Events 等）
- **多维度评分** - 40+ 指标阈值评分，自动识别性能问题并按严重程度分级
- **负载分类** - 自动识别 OLTP / OLAP / MIXED / HTAP 工作负载类型
- **基线对比** - 历史基线自动维护，检测异常偏差
- **关联分析** - 11 种检查方法 + 15 种复合模式，发现指标间的关联问题
- **SQL 反模式检测** - 17 种正则模式识别常见 SQL 性能问题
- **自学习知识引擎** - 规则匹配、命中跟踪、置信度自动更新
- **LLM 集成** - 可选对接 OpenAI / DeepSeek / 自定义 API 生成优化建议
- **多报告对比** - 支持两份 AWR 报告的差异对比分析
- **导出功能** - 分析结果导出为 Markdown 格式
- **用户管理** - 管理员 / 分析师 / 查看者三级权限
- **审计日志** - 完整的操作审计记录
- **中英文支持** - 内置 i18n 国际化

## Tech Stack

| 组件 | 技术 |
|------|------|
| 后端框架 | Flask + Blueprint |
| 数据库 | SQLAlchemy + SQLite |
| 认证 | Flask-Login（密码 bcrypt 哈希） |
| HTML 解析 | BeautifulSoup (lxml / html.parser) |
| 异步分析 | ThreadPoolExecutor (max 2 workers) |
| 前端 | Jinja2 模板 + Bootstrap |
| 测试 | pytest (116 tests) |

## Project Structure

```
dba-platform/
├── run.py                  # 入口文件，启动 Flask 应用 (port 3000)
├── app/
│   ├── __init__.py         # App factory，初始化 DB、登录、蓝图注册
│   ├── config.py           # 配置：SECRET_KEY、数据库、上传、LLM
│   ├── models.py           # 9 个 ORM 模型
│   ├── i18n.py             # 中英文国际化
│   ├── routes_auth.py      # 登录/登出 + 速率限制
│   ├── routes_main.py      # 首页和仪表盘
│   ├── routes_awr.py       # AWR 核心路由（上传/分析/对比/导出）
│   ├── routes_knowledge.py # 知识规则管理
│   ├── routes_admin.py     # 管理后台
│   ├── routes_projects.py  # GitHub 项目展示
│   └── awr/                # AWR 分析引擎
│       ├── parser.py       # HTML 报告解析器
│       ├── scorer.py       # 指标评分引擎 (40+ 阈值)
│       ├── correlator.py   # 关联分析器
│       ├── baseline.py     # 基线对比引擎
│       ├── learning.py     # 自学习引擎
│       ├── llm.py          # LLM 集成
│       ├── advisory.py     # Advisory/TimeModel/Histogram 分析
│       ├── classifier.py   # 负载分类器
│       ├── sql_patterns.py # SQL 反模式检测
│       ├── utils.py        # 工具函数
│       └── constants.py    # 内置规则和常量
├── templates/              # Jinja2 模板
├── static/                 # 静态资源
└── tests/                  # pytest 测试
```

## Analysis Pipeline

```
AWR HTML Upload
    → Parser (BeautifulSoup 解析 28+ 数据段)
    → Scorer (40+ 指标阈值评分)
    → Correlator (关联分析 + 复合模式)
    → Baseline (历史基线对比)
    → Advisory / TimeModel / Histogram 分析
    → SQL Anti-pattern 检测
    → Workload 分类
    → LLM 建议生成 (可选)
    → Learning 引擎更新
```

## Quick Start

### 安装依赖

```bash
pip install -r requirements.txt
```

### 运行

```bash
python run.py
```

应用启动后访问 `http://localhost:3000`。

### 默认账号

首次启动自动创建管理员账号：
- 用户名：`admin`
- 密码：`admin123`

> 请在首次登录后立即修改密码。

### LLM 配置（可选）

在管理后台 → 系统设置中配置：
- `llm_api_url` - API 地址（兼容 OpenAI 接口）
- `llm_api_key` - API Key
- `llm_model` - 模型名称（默认 `deepseek-chat`）

## Running Tests

```bash
pytest tests/ -v
```

## License

MIT
