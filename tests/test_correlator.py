from app.awr.correlator import CorrelationAnalyzer


class TestCorrelationAnalyzer:
    def setup_method(self):
        self.analyzer = CorrelationAnalyzer()

    def test_analyze_empty_data_empty_problems(self):
        """Empty data and problems should produce no correlations."""
        result = self.analyzer.analyze({}, [])
        assert isinstance(result, list)
        assert len(result) == 0

    def test_analyze_none_problems(self):
        """None problems should produce no correlations."""
        result = self.analyzer.analyze({'top_events': []}, None)
        assert isinstance(result, list)
        assert len(result) == 0

    def test_analyze_empty_problems(self):
        """Non-empty data but empty problems should return empty list."""
        result = self.analyzer.analyze({'top_events': [{'event': 'DB CPU'}]}, [])
        assert isinstance(result, list)
        assert len(result) == 0

    def test_analyze_with_io_problem(self):
        """Should detect I/O correlations when relevant problems exist."""
        parsed_data = {
            'top_sql': {
                'SQL ordered by Gets': [
                    {'sql_id': 'abc123', 'Buffer Gets per Exec': 500000}
                ],
                'SQL ordered by Reads': [
                    {'sql_id': 'abc123', 'Physical Reads per Exec': 100000}
                ],
            },
            'top_events': [],
        }
        problems = [
            {'metric_name': 'db_file_sequential_read_avg_wait',
             'title': 'db file sequential read wait high',
             'metric_value': 25.0}
        ]
        result = self.analyzer.analyze(parsed_data, problems)
        assert isinstance(result, list)
        assert len(result) > 0
        assert any('I/O' in f.get('title', '') for f in result)

    def test_analyze_with_cpu_problem(self):
        """Should detect CPU correlations when CPU problems exist."""
        parsed_data = {
            'top_sql': {
                'SQL ordered by CPU Time': [
                    {'sql_id': 'xyz789', 'CPU Time (s)': 500}
                ],
            },
            'top_events': [],
        }
        problems = [
            {'metric_name': 'db_time_ratio',
             'title': 'DB Time ratio high',
             'metric_value': 5.0}
        ]
        result = self.analyzer.analyze(parsed_data, problems)
        assert isinstance(result, list)
        assert len(result) > 0
        assert any('CPU' in f.get('title', '') for f in result)

    def test_analyze_with_log_file_sync_problem(self):
        """Should detect redo/commit correlation for log file sync issues."""
        parsed_data = {
            'load_profile': {
                'computed': {
                    'redo_size': 60000000,
                    'transactions': 150,
                }
            },
            'top_events': [],
        }
        problems = [
            {'metric_name': 'log_file_sync_avg_wait',
             'title': 'log file sync wait high',
             'metric_value': 20.0}
        ]
        result = self.analyzer.analyze(parsed_data, problems)
        assert isinstance(result, list)
        assert len(result) > 0

    def test_correlation_rules_defined(self):
        """Correlation rules should be defined as a class attribute."""
        assert hasattr(CorrelationAnalyzer, 'CORRELATION_RULES')
        assert len(CorrelationAnalyzer.CORRELATION_RULES) > 0
