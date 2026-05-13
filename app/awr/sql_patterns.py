"""SQL anti-pattern detector."""
import re
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SQL ANTI-PATTERN DETECTOR
# ---------------------------------------------------------------------------

class SQLAntiPatternDetector:
    """Detect common SQL anti-patterns from SQL text extracted from AWR."""

    # Each pattern: (name, regex/callable, severity, description, suggestion)
    PATTERNS = [
        {
            'name': 'SELECT_STAR',
            'pattern': r'\bSELECT\s+\*\s+FROM\b',
            'severity': 'medium',
            'description': 'SELECT * 查询所有列，增加不必要的I/O和网络传输',
            'suggestion': '明确指定需要的列名，减少数据传输和Buffer Gets',
        },
        {
            'name': 'NO_WHERE_CLAUSE',
            'pattern': r'\bSELECT\b.+?\bFROM\b\s+\w+\s*(?:$|;|\)|ORDER|GROUP|HAVING|UNION)',
            'severity': 'high',
            'description': '查询缺少WHERE条件，可能导致全表扫描',
            'suggestion': '添加合适的WHERE条件限制返回行数',
        },
        {
            'name': 'LEADING_WILDCARD_LIKE',
            'pattern': r"\bLIKE\s+'%[^']+",
            'severity': 'high',
            'description': "LIKE '%xxx' 前导通配符导致索引失效，必须全表扫描",
            'suggestion': '改用全文索引(Oracle Text)或反转字符串索引，避免前导%',
        },
        {
            'name': 'FUNCTION_ON_INDEX_COLUMN',
            'pattern': r'\b(?:TO_CHAR|TO_DATE|TO_NUMBER|TRUNC|UPPER|LOWER|NVL|SUBSTR|TRIM|DECODE)\s*\([^)]*\)\s*=',
            'severity': 'high',
            'description': '函数包裹索引列导致索引失效(隐式全扫描)',
            'suggestion': '创建函数索引，或改写条件避免对列施加函数',
        },
        {
            'name': 'NOT_IN_SUBQUERY',
            'pattern': r'\bNOT\s+IN\s*\(\s*SELECT\b',
            'severity': 'medium',
            'description': 'NOT IN子查询在有NULL值时语义可能错误，且性能差',
            'suggestion': '改用NOT EXISTS或LEFT JOIN ... IS NULL',
        },
        {
            'name': 'CARTESIAN_JOIN',
            'pattern': r'\bFROM\b\s+\w+\s*,\s*\w+(?:\s*,\s*\w+)*\s+WHERE\b(?:(?!(?:\w+\.\w+\s*=\s*\w+\.\w+)).)*$',
            'severity': 'high',
            'description': '可能存在笛卡尔积(Cartesian Join)，缺少表关联条件',
            'suggestion': '检查FROM子句中多表是否都有正确的JOIN条件',
        },
        {
            'name': 'UNION_INSTEAD_OF_UNION_ALL',
            'pattern': r'\bUNION\b(?!\s+ALL\b)',
            'severity': 'low',
            'description': 'UNION 会执行去重排序(SORT UNIQUE)，如果不需要去重应使用 UNION ALL',
            'suggestion': '确认是否需要去重，不需要则改为 UNION ALL 避免排序开销',
        },
        {
            'name': 'ORDER_BY_WITHOUT_LIMIT',
            'pattern': r'\bORDER\s+BY\b(?!.*\b(?:ROWNUM|FETCH\s+FIRST|ROW_NUMBER|OFFSET)\b)',
            'severity': 'low',
            'description': 'ORDER BY 无分页限制，可能对大结果集排序消耗大量PGA/TEMP',
            'suggestion': '添加ROWNUM限制或使用分页(12c+ FETCH FIRST N ROWS)',
        },
        {
            'name': 'IMPLICIT_TYPE_CONVERSION',
            'pattern': r"(?:WHERE|AND|OR)\s+\w+\s*=\s*'?\d{4,}'?",
            'severity': 'medium',
            'description': '可能存在隐式类型转换(字符串列与数值比较)导致索引失效',
            'suggestion': '确保比较两侧数据类型一致，避免Oracle隐式调用TO_NUMBER/TO_CHAR',
        },
        {
            'name': 'NESTED_SUBQUERY_DEEP',
            'pattern': r'(?:\bSELECT\b.*){4,}',
            'severity': 'medium',
            'description': '嵌套子查询层级过深(4+层)，优化器可能无法有效优化',
            'suggestion': '使用WITH(CTE)改写子查询，或拆分为多步操作',
        },
        {
            'name': 'DISTINCT_ON_LARGE_SET',
            'pattern': r'\bSELECT\s+DISTINCT\b',
            'severity': 'low',
            'description': 'DISTINCT 需要排序去重，大结果集消耗PGA/TEMP',
            'suggestion': '检查是否因JOIN不当导致重复行，修正JOIN后移除DISTINCT',
        },
        {
            'name': 'HINT_FULL_TABLE_SCAN',
            'pattern': r'/\*\+.*\bFULL\s*\(\s*\w+\s*\).*\*/',
            'severity': 'medium',
            'description': 'SQL Hint强制全表扫描，可能是历史遗留或不适当的优化',
            'suggestion': '评估全扫描提示是否仍然合理，更新统计信息后考虑移除',
        },
        {
            'name': 'CURSOR_LOOP',
            'pattern': r'\b(CURSOR\s+\w+\s+IS\s+SELECT|FOR\s+\w+\s+IN\s*\(\s*SELECT)',
            'severity': 'high',
            'description': '游标循环(Cursor Loop/Row-by-Row)处理，导致上下文切换和大量SQL执行',
            'suggestion': '改用集合操作(BULK COLLECT + FORALL)或单条SQL完成批量处理',
        },
        {
            'name': 'SCALAR_SUBQUERY_IN_SELECT',
            'pattern': r'\bSELECT\b[^,]*\(\s*SELECT\b[^)]*\)\s*(?:,|\bFROM\b)',
            'severity': 'medium',
            'description': '标量子查询在SELECT列表中，每行都会执行子查询。当外层结果集大时性能极差',
            'suggestion': '改用LEFT JOIN关联查询，或使用WITH子句(CTE)预先计算',
        },
        {
            'name': 'OR_ON_DIFFERENT_COLUMNS',
            'pattern': r'\bWHERE\b.*\b(\w+)\.\w+\s*=.*\bOR\b.*\b(?!\1\.)\w+\.\w+\s*=',
            'severity': 'medium',
            'description': 'WHERE条件中OR连接不同表的列，可能导致全表扫描(优化器无法同时使用多个索引)',
            'suggestion': '改用UNION ALL将OR条件拆分为多个独立查询，或使用CONCATENATION hint',
        },
        {
            'name': 'MISSING_INDEX_FK',
            'pattern': r'\bDELETE\b.*\bFROM\b|\bUPDATE\b.*\bSET\b',
            'severity': 'low',
            'description': '对有外键引用的表执行DML时，如果外键列缺少索引会导致子表全表锁',
            'suggestion': '确保所有外键列上都有索引，避免DELETE/UPDATE父表时锁定整个子表',
        },
        {
            'name': 'SYSDATE_IN_SQL',
            'pattern': r'\bSYSDATE\b.*\b(?:BETWEEN|>|<|>=|<=)\b|\b(?:BETWEEN|>|<|>=|<=)\b.*\bSYSDATE\b',
            'severity': 'low',
            'description': 'SQL中使用SYSDATE作为绑定条件，每次执行值不同可能导致执行计划不稳定',
            'suggestion': '考虑将SYSDATE计算结果作为绑定变量传入，避免影响执行计划缓存',
        },
        {
            'name': 'EXISTS_VS_IN_LARGE_SET',
            'pattern': r'\bIN\s*\(\s*SELECT\b.*\bFROM\b\s+\w+.*(?:WHERE|GROUP|HAVING)',
            'severity': 'low',
            'description': 'IN子查询用于大结果集时，EXISTS通常更高效(尤其当外层表较小时)',
            'suggestion': '对于大子查询结果集，评估改用EXISTS或JOIN是否能提升性能',
        },
    ]

    def detect(self, sql_text_list: list) -> list:
        """Detect anti-patterns in a list of SQL text strings.
        Each item should be a dict with at least 'sql_text' and optionally 'sql_id'.
        Returns list of finding dicts."""
        findings = []
        if not sql_text_list:
            return findings

        for sql_entry in sql_text_list:
            if isinstance(sql_entry, str):
                sql_text = sql_entry
                sql_id = 'unknown'
            elif isinstance(sql_entry, dict):
                sql_text = sql_entry.get('sql_text', sql_entry.get('SQL Text', ''))
                sql_id = sql_entry.get('sql_id', sql_entry.get('SQL Id', 'unknown'))
            else:
                continue

            if not sql_text or len(sql_text.strip()) < 10:
                continue

            sql_upper = sql_text.upper()
            for pattern_def in self.PATTERNS:
                try:
                    if re.search(pattern_def['pattern'], sql_upper, re.IGNORECASE | re.DOTALL):
                        findings.append({
                            'sql_id': sql_id,
                            'anti_pattern': pattern_def['name'],
                            'severity': pattern_def['severity'],
                            'description': pattern_def['description'],
                            'suggestion': pattern_def['suggestion'],
                            'sql_snippet': sql_text[:200],
                        })
                except re.error:
                    pass

        return findings

    def detect_from_parsed(self, parsed_data: dict) -> list:
        """Convenience method: extract SQL text from parsed AWR data and detect."""
        sql_entries = []
        top_sql = parsed_data.get('top_sql', {})
        if isinstance(top_sql, dict):
            for section_name, sql_list in top_sql.items():
                if isinstance(sql_list, list):
                    for entry in sql_list:
                        if isinstance(entry, dict) and entry.get('sql_text', entry.get('SQL Text', '')):
                            sql_entries.append(entry)
        elif isinstance(top_sql, list):
            for entry in top_sql:
                if isinstance(entry, dict) and entry.get('sql_text', entry.get('SQL Text', '')):
                    sql_entries.append(entry)

        # Deduplicate by sql_id
        seen = set()
        unique_entries = []
        for e in sql_entries:
            sid = e.get('sql_id', e.get('SQL Id', ''))
            if sid and sid not in seen:
                seen.add(sid)
                unique_entries.append(e)
            elif not sid:
                unique_entries.append(e)

        return self.detect(unique_entries)


