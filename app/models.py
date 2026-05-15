import sqlite3
import json
from datetime import datetime
from pathlib import Path


class Database:
    def __init__(self, db_path="data/history.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self):
        """Get a thread-safe connection."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS analysis_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                filename TEXT NOT NULL,
                analyzer_type TEXT NOT NULL,

                db_time REAL,
                elapsed_time REAL,
                aas REAL,
                db_cpu_percent REAL,
                load_type TEXT,

                main_problem TEXT,
                diagnosis_summary TEXT,

                raw_result TEXT,
                llm_analysis TEXT,
                llm_result_json TEXT,
                markdown_content TEXT
            )
        """)

        # Migration: add llm_result_json column if missing
        cursor = conn.execute("PRAGMA table_info(analysis_history)")
        columns = {row[1] for row in cursor.fetchall()}
        if "llm_result_json" not in columns:
            conn.execute("ALTER TABLE analysis_history ADD COLUMN llm_result_json TEXT")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS database_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                db_identifier TEXT UNIQUE NOT NULL,
                db_name TEXT,
                db_version TEXT,
                business_type TEXT,
                environment TEXT,

                common_bottlenecks TEXT,
                optimized_items TEXT,
                notes TEXT,

                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()
        conn.close()

    def save_analysis(self, filename, analyzer_type, result, llm_result, markdown):
        """保存分析结果"""
        conn = sqlite3.connect(self.db_path)

        # 提取关键指标
        metrics = result.get("metrics", {})
        diagnosis = result.get("diagnosis", {})

        # 提取纯文本分析（向后兼容）
        llm_analysis_text = ""
        if llm_result:
            llm_analysis_text = llm_result.get("expert_analysis", "") or llm_result.get("analysis", "")

        # 完整 LLM 结果 JSON
        llm_json = json.dumps(llm_result, ensure_ascii=False) if llm_result else None

        conn.execute("""
            INSERT INTO analysis_history (
                filename, analyzer_type,
                db_time, elapsed_time, aas, db_cpu_percent, load_type,
                main_problem, diagnosis_summary,
                raw_result, llm_analysis, llm_result_json, markdown_content
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            filename,
            analyzer_type,
            metrics.get("db_time"),
            metrics.get("elapsed_time"),
            metrics.get("aas"),
            metrics.get("db_cpu_percent"),
            metrics.get("load_type"),
            diagnosis.get("main_problem"),
            diagnosis.get("summary"),
            json.dumps(result, ensure_ascii=False),
            llm_analysis_text,
            llm_json,
            markdown
        ))

        conn.commit()
        record_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()

        return record_id

    def get_all_history(self, limit=50):
        """获取所有历史记录"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        cursor = conn.execute("""
            SELECT id, created_at, filename, analyzer_type,
                   db_time, elapsed_time, aas, db_cpu_percent, load_type,
                   main_problem, diagnosis_summary
            FROM analysis_history
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))

        records = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return records

    def get_by_id(self, record_id):
        """获取单条记录详情"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        cursor = conn.execute("""
            SELECT * FROM analysis_history WHERE id = ?
        """, (record_id,))

        row = cursor.fetchone()
        conn.close()

        if row:
            record = dict(row)
            if record.get("raw_result"):
                record["raw_result"] = json.loads(record["raw_result"])
            # Parse structured LLM result (new format)
            if record.get("llm_result_json"):
                record["llm_result"] = json.loads(record["llm_result_json"])
            elif record.get("llm_analysis"):
                # Backward compat: old records with only text
                record["llm_result"] = {"expert_analysis": record["llm_analysis"]}
            return record
        return None

    def delete_by_id(self, record_id):
        """删除记录"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM analysis_history WHERE id = ?", (record_id,))
        conn.commit()
        conn.close()

    def get_similar_cases(self, main_problem, limit=5):
        """检索相似案例（简单关键词匹配）"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        cursor = conn.execute("""
            SELECT id, created_at, filename, main_problem, diagnosis_summary
            FROM analysis_history
            WHERE main_problem LIKE ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (f"%{main_problem}%", limit))

        records = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return records

    def compare_records(self, record1, record2):
        """对比两条记录，计算差异和趋势"""
        comparison = {
            "metrics_diff": {},
            "trend": {},
            "top_events_diff": [],
            "top_sql_diff": [],
            "summary": ""
        }

        # 对比关键指标
        metrics = ["db_time", "elapsed_time", "aas", "db_cpu_percent"]
        for metric in metrics:
            val1 = record1.get(metric)
            val2 = record2.get(metric)

            if val1 is not None and val2 is not None:
                diff = val2 - val1
                pct_change = (diff / val1 * 100) if val1 != 0 else 0

                comparison["metrics_diff"][metric] = {
                    "old": val1,
                    "new": val2,
                    "diff": diff,
                    "pct_change": pct_change,
                    "trend": "up" if diff > 0 else "down" if diff < 0 else "stable"
                }

        # 生成总体趋势
        if comparison["metrics_diff"].get("db_time"):
            db_time_trend = comparison["metrics_diff"]["db_time"]["trend"]
            db_time_pct = comparison["metrics_diff"]["db_time"]["pct_change"]

            if db_time_trend == "up":
                comparison["trend"]["overall"] = "worse"
                comparison["trend"]["message"] = f"性能下降 {abs(db_time_pct):.1f}%"
            elif db_time_trend == "down":
                comparison["trend"]["overall"] = "better"
                comparison["trend"]["message"] = f"性能提升 {abs(db_time_pct):.1f}%"
            else:
                comparison["trend"]["overall"] = "stable"
                comparison["trend"]["message"] = "性能基本稳定"

        # 对比 Top Events（从 raw_result 中提取）
        try:
            raw1 = record1.get("raw_result")
            raw2 = record2.get("raw_result")

            if raw1 and raw2:
                result1 = json.loads(raw1) if isinstance(raw1, str) else raw1
                result2 = json.loads(raw2) if isinstance(raw2, str) else raw2

                events1 = result1.get("evidence", {}).get("Top Events", [])
                events2 = result2.get("evidence", {}).get("Top Events", [])

                # 简单对比前5个事件
                comparison["top_events_diff"] = self._compare_events(events1[:5], events2[:5])

                # 对比 Top SQL
                sql1 = result1.get("evidence", {}).get("Top SQL", [])
                sql2 = result2.get("evidence", {}).get("Top SQL", [])
                comparison["top_sql_diff"] = self._compare_sql(sql1[:5], sql2[:5])
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Failed to compare events/sql: {e}")

        return comparison

    def _compare_events(self, events1, events2):
        """对比两组等待事件"""
        event_map1 = {e["name"]: e for e in events1}
        event_map2 = {e["name"]: e for e in events2}

        all_events = set(event_map1.keys()) | set(event_map2.keys())
        diff = []

        for event_name in all_events:
            e1 = event_map1.get(event_name)
            e2 = event_map2.get(event_name)

            if e1 and e2:
                # 都存在，对比变化
                diff.append({
                    "name": event_name,
                    "status": "changed",
                    "old_value": e1.get("value", ""),
                    "new_value": e2.get("value", "")
                })
            elif e1:
                # 只在旧记录中存在
                diff.append({
                    "name": event_name,
                    "status": "removed",
                    "old_value": e1.get("value", ""),
                    "new_value": "-"
                })
            else:
                # 只在新记录中存在
                diff.append({
                    "name": event_name,
                    "status": "new",
                    "old_value": "-",
                    "new_value": e2.get("value", "")
                })

        return diff

    def _compare_sql(self, sql1, sql2):
        """对比两组 Top SQL"""
        sql_map1 = {s["name"]: s for s in sql1}
        sql_map2 = {s["name"]: s for s in sql2}

        all_sql = set(sql_map1.keys()) | set(sql_map2.keys())
        diff = []

        for sql_id in all_sql:
            s1 = sql_map1.get(sql_id)
            s2 = sql_map2.get(sql_id)

            if s1 and s2:
                diff.append({
                    "sql_id": sql_id,
                    "status": "changed",
                    "old_value": s1.get("value", ""),
                    "new_value": s2.get("value", "")
                })
            elif s1:
                diff.append({
                    "sql_id": sql_id,
                    "status": "removed",
                    "old_value": s1.get("value", ""),
                    "new_value": "-"
                })
            else:
                diff.append({
                    "sql_id": sql_id,
                    "status": "new",
                    "old_value": "-",
                    "new_value": s2.get("value", "")
                })

        return diff


    def get_profile(self, db_identifier):
        """获取数据库画像"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        cursor = conn.execute("""
            SELECT * FROM database_profiles WHERE db_identifier = ?
        """, (db_identifier,))

        row = cursor.fetchone()
        conn.close()

        if row:
            profile = dict(row)
            if profile.get("common_bottlenecks"):
                profile["common_bottlenecks"] = json.loads(profile["common_bottlenecks"])
            if profile.get("optimized_items"):
                profile["optimized_items"] = json.loads(profile["optimized_items"])
            return profile
        return None

    def save_profile(self, db_identifier, db_name=None, db_version=None,
                     business_type=None, environment=None, common_bottlenecks=None,
                     optimized_items=None, notes=None):
        """保存或更新数据库画像"""
        conn = sqlite3.connect(self.db_path)

        # 检查是否已存在
        existing = conn.execute(
            "SELECT id FROM database_profiles WHERE db_identifier = ?",
            (db_identifier,)
        ).fetchone()

        if existing:
            # 更新
            conn.execute("""
                UPDATE database_profiles
                SET db_name = COALESCE(?, db_name),
                    db_version = COALESCE(?, db_version),
                    business_type = COALESCE(?, business_type),
                    environment = COALESCE(?, environment),
                    common_bottlenecks = COALESCE(?, common_bottlenecks),
                    optimized_items = COALESCE(?, optimized_items),
                    notes = COALESCE(?, notes),
                    updated_at = CURRENT_TIMESTAMP
                WHERE db_identifier = ?
            """, (
                db_name, db_version, business_type, environment,
                json.dumps(common_bottlenecks, ensure_ascii=False) if common_bottlenecks else None,
                json.dumps(optimized_items, ensure_ascii=False) if optimized_items else None,
                notes, db_identifier
            ))
        else:
            # 插入
            conn.execute("""
                INSERT INTO database_profiles (
                    db_identifier, db_name, db_version, business_type, environment,
                    common_bottlenecks, optimized_items, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                db_identifier, db_name, db_version, business_type, environment,
                json.dumps(common_bottlenecks, ensure_ascii=False) if common_bottlenecks else None,
                json.dumps(optimized_items, ensure_ascii=False) if optimized_items else None,
                notes
            ))

        conn.commit()
        conn.close()

    def get_all_profiles(self):
        """获取所有数据库画像"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        cursor = conn.execute("""
            SELECT id, db_identifier, db_name, db_version, business_type,
                   environment, updated_at
            FROM database_profiles
            ORDER BY updated_at DESC
        """)

        records = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return records

    def update_profile_from_analysis(self, db_identifier, main_problem):
        """根据分析结果自动更新数据库画像"""
        profile = self.get_profile(db_identifier)

        if not profile:
            # 创建新画像
            self.save_profile(
                db_identifier=db_identifier,
                common_bottlenecks=[main_problem]
            )
        else:
            # 更新常见瓶颈
            bottlenecks = profile.get("common_bottlenecks", [])
            if main_problem and main_problem not in bottlenecks:
                bottlenecks.append(main_problem)
                # 只保留最近10个
                bottlenecks = bottlenecks[-10:]
                self.save_profile(
                    db_identifier=db_identifier,
                    common_bottlenecks=bottlenecks
                )

    def get_trend_data(self, days=30, analyzer_type=None):
        """获取性能趋势数据"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        query = """
            SELECT
                id,
                created_at,
                filename,
                db_time,
                aas,
                db_cpu_percent,
                load_type,
                main_problem
            FROM analysis_history
            WHERE datetime(created_at) >= datetime('now', '-' || ? || ' days')
        """
        params = [days]

        if analyzer_type:
            query += " AND analyzer_type = ?"
            params.append(analyzer_type)

        query += " ORDER BY created_at ASC"

        cursor = conn.execute(query, params)
        records = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return records

    def get_statistics(self):
        """获取统计信息"""
        conn = sqlite3.connect(self.db_path)

        stats = {}

        # 总记录数
        stats["total_records"] = conn.execute(
            "SELECT COUNT(*) FROM analysis_history"
        ).fetchone()[0]

        # 最近7天记录数
        stats["recent_records"] = conn.execute(
            "SELECT COUNT(*) FROM analysis_history WHERE datetime(created_at) >= datetime('now', '-7 days')"
        ).fetchone()[0]

        # 平均 DB Time
        result = conn.execute(
            "SELECT AVG(db_time) FROM analysis_history WHERE db_time IS NOT NULL"
        ).fetchone()
        stats["avg_db_time"] = result[0] if result[0] else 0

        # 平均 AAS
        result = conn.execute(
            "SELECT AVG(aas) FROM analysis_history WHERE aas IS NOT NULL"
        ).fetchone()
        stats["avg_aas"] = result[0] if result[0] else 0

        # 最常见问题 Top 5
        cursor = conn.execute("""
            SELECT main_problem, COUNT(*) as count
            FROM analysis_history
            WHERE main_problem IS NOT NULL AND main_problem != ''
            GROUP BY main_problem
            ORDER BY count DESC
            LIMIT 5
        """)
        stats["top_problems"] = [{"problem": row[0], "count": row[1]} for row in cursor.fetchall()]

        # 数据库画像数量
        stats["total_profiles"] = conn.execute(
            "SELECT COUNT(*) FROM database_profiles"
        ).fetchone()[0]

        conn.close()
        return stats

    def detect_anomalies(self, records, metric="db_time", threshold=1.5):
        """检测性能突变点"""
        if len(records) < 3:
            return []

        anomalies = []
        values = [r.get(metric) for r in records if r.get(metric) is not None]

        if len(values) < 3:
            return []

        # 计算移动平均和标准差
        for i in range(2, len(records)):
            current = records[i].get(metric)
            if current is None:
                continue

            # 前面的值
            prev_values = [records[j].get(metric) for j in range(max(0, i-5), i) if records[j].get(metric) is not None]
            if len(prev_values) < 2:
                continue

            avg = sum(prev_values) / len(prev_values)
            std = (sum((x - avg) ** 2 for x in prev_values) / len(prev_values)) ** 0.5

            # 检测异常
            if std > 0 and abs(current - avg) > threshold * std:
                anomalies.append({
                    "index": i,
                    "record_id": records[i]["id"],
                    "timestamp": records[i]["created_at"],
                    "metric": metric,
                    "value": current,
                    "expected": avg,
                    "deviation": abs(current - avg) / std,
                    "type": "spike" if current > avg else "drop"
                })

        return anomalies


# 全局数据库实例
db = Database()
