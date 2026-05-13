from app.awr.classifier import WorkloadClassifier, classify_workload


class TestWorkloadClassifier:
    def setup_method(self):
        self.classifier = WorkloadClassifier()

    def test_classify_oltp_workload(self):
        """OLTP-like metrics should classify as OLTP."""
        parsed_data = {
            'load_profile': {
                'computed': {
                    'logical_reads': 200000,
                    'physical_reads': 500,
                    'transactions': 2000,
                    'redo_size': 20000000,
                    'parses': 500,
                    'executes': 10000,
                }
            },
            'top_events': [
                {'event': 'DB CPU', 'pct_db_time': 50.0},
                {'event': 'db file sequential read', 'pct_db_time': 25.0},
            ],
            'temp_stats': {},
        }
        result = self.classifier.classify(parsed_data)
        assert isinstance(result, dict)
        assert result['workload_type'] == 'OLTP'
        assert result['oltp_score'] > result['olap_score']

    def test_classify_olap_workload(self):
        """OLAP-like metrics should classify as OLAP."""
        parsed_data = {
            'load_profile': {
                'computed': {
                    'logical_reads': 5000,
                    'physical_reads': 4000,
                    'transactions': 2,
                    'redo_size': 100000,
                    'parses': 100,
                    'executes': 100,
                }
            },
            'top_events': [
                {'event': 'DB CPU', 'pct_db_time': 30.0},
                {'event': 'db file scattered read', 'pct_db_time': 25.0},
                {'event': 'direct path read', 'pct_db_time': 20.0},
            ],
            'temp_stats': {'disk_sort_pct': 15},
        }
        result = self.classifier.classify(parsed_data)
        assert isinstance(result, dict)
        assert result['workload_type'] == 'OLAP'
        assert result['olap_score'] > result['oltp_score']

    def test_classify_empty_data(self):
        """Empty data should not crash and should return a valid classification."""
        result = self.classifier.classify({})
        assert isinstance(result, dict)
        assert 'workload_type' in result
        assert result['workload_type'] in ('OLTP', 'OLAP', 'MIXED', 'HTAP')
        assert result['confidence'] <= 1.0

    def test_classify_returns_required_keys(self):
        """Result should contain all expected keys."""
        result = self.classifier.classify({})
        for key in ('workload_type', 'confidence', 'signals',
                     'oltp_score', 'olap_score', 'threshold_adjustments'):
            assert key in result, f"Missing key: {key}"

    def test_classify_workload_wrapper(self):
        """classify_workload() convenience function should work."""
        result = classify_workload({})
        assert isinstance(result, dict)
        assert 'workload_type' in result

    def test_threshold_adjustments_for_oltp(self):
        """OLTP classification should produce OLTP-specific threshold adjustments."""
        adjustments = self.classifier._get_threshold_adjustments('OLTP')
        assert isinstance(adjustments, dict)
        assert 'log_file_sync_avg_wait' in adjustments

    def test_threshold_adjustments_for_olap(self):
        """OLAP classification should produce OLAP-specific threshold adjustments."""
        adjustments = self.classifier._get_threshold_adjustments('OLAP')
        assert isinstance(adjustments, dict)
        assert 'physical_reads_per_sec' in adjustments

    def test_threshold_adjustments_for_unknown(self):
        """Unknown workload type should return empty adjustments."""
        adjustments = self.classifier._get_threshold_adjustments('UNKNOWN')
        assert isinstance(adjustments, dict)
        assert len(adjustments) == 0
