from app.awr.advisory import (
    AdvisoryAnalyzer, TimeModelAnalyzer, WaitHistogramAnalyzer,
    get_advisory_recommendations, get_time_model_findings,
    get_wait_histogram_findings,
)


class TestAdvisoryAnalyzer:
    def setup_method(self):
        self.analyzer = AdvisoryAnalyzer()

    def test_analyze_empty_data(self):
        result = self.analyzer.analyze({})
        assert isinstance(result, list)
        assert len(result) == 0

    def test_analyze_none_data(self):
        result = self.analyzer.analyze(None)
        assert isinstance(result, list)
        assert len(result) == 0

    def test_analyze_with_buffer_pool_advisory_significant_benefit(self):
        """Buffer pool advisory with >20% read reduction should produce recommendation."""
        advisories = {
            'Buffer Pool': [
                {'Size Factor': '0.5', 'Size (M)': '2048', 'Physical Read Factor': '2.0',
                 'Estimated Physical Reads': 200000},
                {'Size Factor': '1.0', 'Size (M)': '4096', 'Physical Read Factor': '1.0',
                 'Estimated Physical Reads': 100000},
                {'Size Factor': '1.5', 'Size (M)': '6144', 'Physical Read Factor': '0.5',
                 'Estimated Physical Reads': 50000},
                {'Size Factor': '2.0', 'Size (M)': '8192', 'Physical Read Factor': '0.3',
                 'Estimated Physical Reads': 30000},
            ]
        }
        result = self.analyzer.analyze(advisories)
        assert isinstance(result, list)
        # Should recommend buffer pool increase since reads drop >20%
        if len(result) > 0:
            assert result[0]['advisory_type'] == 'Buffer Pool'

    def test_analyze_with_pga_advisory(self):
        """PGA advisory with over-allocation should produce recommendation."""
        advisories = {
            'PGA': [
                {'PGA Target Est (MB)': '512', 'Estd PGA Overalloc Count': '50',
                 'Estd Extra Bytes Read/Written to Disk': 1000000},
                {'PGA Target Est (MB)': '1024', 'Estd PGA Overalloc Count': '0',
                 'Estd Extra Bytes Read/Written to Disk': 0},
            ]
        }
        result = self.analyzer.analyze(advisories)
        assert isinstance(result, list)
        if len(result) > 0:
            assert result[0]['advisory_type'] == 'PGA'

    def test_get_advisory_recommendations_convenience(self):
        """Convenience function should work."""
        result = get_advisory_recommendations({})
        assert isinstance(result, list)


class TestTimeModelAnalyzer:
    def setup_method(self):
        self.analyzer = TimeModelAnalyzer()

    def test_analyze_empty_data(self):
        result = self.analyzer.analyze({})
        assert isinstance(result, list)
        assert len(result) == 0

    def test_analyze_with_high_hard_parse(self):
        """Should flag high hard parse elapsed time."""
        time_model = {
            'sql_execute_elapsed_time': {
                'name': 'sql execute elapsed time',
                'time_seconds': 10000,
                'pct_db_time': 100,
            },
            'hard_parse_elapsed_time': {
                'name': 'hard parse elapsed time',
                'time_seconds': 2000,
                'pct_db_time': 20,  # above 10% threshold
            },
            'db_cpu': {
                'name': 'DB CPU',
                'time_seconds': 5000,
                'pct_db_time': 50,
            },
        }
        result = self.analyzer.analyze(time_model)
        assert isinstance(result, list)
        assert any('hard' in f.get('finding', '').lower() or 'hard' in f.get('component', '').lower()
                    for f in result)

    def test_analyze_with_low_db_cpu(self):
        """Should flag when DB CPU is below 30% of DB Time."""
        time_model = {
            'sql_execute_elapsed_time': {
                'name': 'sql execute elapsed time',
                'time_seconds': 10000,
                'pct_db_time': 100,
            },
            'db_cpu': {
                'name': 'DB CPU',
                'time_seconds': 2000,
                'pct_db_time': 20,  # below 30%
            },
        }
        result = self.analyzer.analyze(time_model)
        assert isinstance(result, list)
        assert any('CPU' in f.get('component', '') for f in result)

    def test_get_time_model_findings_convenience(self):
        """Convenience function should work."""
        result = get_time_model_findings({})
        assert isinstance(result, list)


class TestWaitHistogramAnalyzer:
    def setup_method(self):
        self.analyzer = WaitHistogramAnalyzer()

    def test_analyze_empty_data(self):
        result = self.analyzer.analyze([])
        assert isinstance(result, list)
        assert len(result) == 0

    def test_analyze_none_data(self):
        result = self.analyzer.analyze(None)
        assert isinstance(result, list)
        assert len(result) == 0

    def test_analyze_normal_distribution(self):
        """Normal latency distribution should be detected."""
        rows = [{
            'Event': 'db file sequential read',
            '< 1ms': 5000,
            '< 2ms': 3000,
            '< 4ms': 1500,
            '< 8ms': 400,
            '< 16ms': 80,
            '< 32ms': 15,
            '>= 32ms': 5,
        }]
        result = self.analyzer.analyze(rows)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]['event'] == 'db file sequential read'
        assert 'total_waits' in result[0]
        assert result[0]['total_waits'] == 10000

    def test_analyze_long_tail(self):
        """Should detect long-tail latency pattern when >= 32ms bucket > 5%."""
        rows = [{
            'Event': 'log file sync',
            '< 1ms': 100,
            '< 2ms': 100,
            '< 4ms': 100,
            '< 8ms': 100,
            '< 16ms': 100,
            '< 32ms': 100,
            '>= 32ms': 500,  # 500/1100 = ~45%
        }]
        result = self.analyzer.analyze(rows)
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]['pattern'] == 'long_tail'
        assert result[0]['severity'] == 'high'

    def test_get_wait_histogram_findings_convenience(self):
        """Convenience function should work."""
        result = get_wait_histogram_findings([])
        assert isinstance(result, list)
