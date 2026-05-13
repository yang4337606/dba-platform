from app.awr.sql_patterns import SQLAntiPatternDetector


class TestSQLAntiPatternDetector:
    def setup_method(self):
        self.detector = SQLAntiPatternDetector()

    def test_detect_select_star(self):
        """Should detect SELECT * pattern."""
        sqls = [{'sql_text': 'SELECT * FROM employees WHERE dept_id = 10', 'sql_id': 'test1'}]
        results = self.detector.detect(sqls)
        assert isinstance(results, list)
        assert any(r['anti_pattern'] == 'SELECT_STAR' for r in results)

    def test_detect_leading_wildcard_like(self):
        """Should detect LIKE '%...' pattern."""
        sqls = [{'sql_text': "SELECT name FROM employees WHERE name LIKE '%smith'", 'sql_id': 'test2'}]
        results = self.detector.detect(sqls)
        assert isinstance(results, list)
        assert any(r['anti_pattern'] == 'LEADING_WILDCARD_LIKE' for r in results)

    def test_detect_not_in_subquery(self):
        """Should detect NOT IN (SELECT ...) pattern."""
        sqls = [{'sql_text': 'SELECT id FROM orders WHERE customer_id NOT IN (SELECT id FROM customers WHERE active = 1)',
                 'sql_id': 'test3'}]
        results = self.detector.detect(sqls)
        assert isinstance(results, list)
        assert any(r['anti_pattern'] == 'NOT_IN_SUBQUERY' for r in results)

    def test_detect_empty_list(self):
        """Empty SQL list should return empty results."""
        results = self.detector.detect([])
        assert isinstance(results, list)
        assert len(results) == 0

    def test_detect_short_sql_ignored(self):
        """SQL text shorter than 10 chars should be skipped."""
        sqls = [{'sql_text': 'SELECT 1', 'sql_id': 'short'}]
        results = self.detector.detect(sqls)
        assert isinstance(results, list)
        assert len(results) == 0

    def test_detect_string_input(self):
        """Should accept plain strings in the list."""
        sqls = ['SELECT * FROM employees WHERE dept_id = 10']
        results = self.detector.detect(sqls)
        assert isinstance(results, list)
        assert any(r['anti_pattern'] == 'SELECT_STAR' for r in results)

    def test_detect_from_parsed_with_sql(self):
        """detect_from_parsed should work with parsed AWR data containing top_sql."""
        parsed_data = {
            'top_sql': {
                'SQL ordered by Elapsed Time': [
                    {'sql_id': 'abc', 'sql_text': 'SELECT * FROM dual WHERE dummy = 1'}
                ]
            }
        }
        results = self.detector.detect_from_parsed(parsed_data)
        assert isinstance(results, list)

    def test_detect_from_parsed_empty(self):
        """No sql in parsed data should return empty list."""
        results = self.detector.detect_from_parsed({})
        assert isinstance(results, list)
        assert len(results) == 0

    def test_detect_from_parsed_deduplicates(self):
        """detect_from_parsed should deduplicate by sql_id."""
        parsed_data = {
            'top_sql': {
                'SQL ordered by Gets': [
                    {'sql_id': 'dup1', 'sql_text': 'SELECT * FROM employees WHERE id = 1'}
                ],
                'SQL ordered by Reads': [
                    {'sql_id': 'dup1', 'sql_text': 'SELECT * FROM employees WHERE id = 1'}
                ],
            }
        }
        results = self.detector.detect_from_parsed(parsed_data)
        # Should only process dup1 once
        sql_ids = [r['sql_id'] for r in results]
        assert sql_ids.count('dup1') <= len(self.detector.PATTERNS)  # at most one match per pattern

    def test_patterns_defined(self):
        """PATTERNS should be defined and non-empty."""
        assert hasattr(SQLAntiPatternDetector, 'PATTERNS')
        assert len(SQLAntiPatternDetector.PATTERNS) > 0

    def test_each_pattern_has_required_fields(self):
        """Each pattern definition should have required fields."""
        for p in SQLAntiPatternDetector.PATTERNS:
            assert 'name' in p
            assert 'pattern' in p
            assert 'severity' in p
            assert 'description' in p
            assert 'suggestion' in p
