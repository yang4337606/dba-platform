from app.awr.baseline import BaselineComparer


class TestBaselineComparer:
    def setup_method(self):
        self.comparer = BaselineComparer()

    def test_calculate_deviation_normal(self):
        """Should calculate deviation percentage correctly."""
        result = self.comparer._calculate_deviation(150.0, 100.0, 120.0)
        assert result['deviation_pct'] == 50.0
        assert result['is_anomaly'] is True

    def test_calculate_deviation_no_anomaly(self):
        """Small deviation should not be flagged as anomaly."""
        result = self.comparer._calculate_deviation(110.0, 100.0, 120.0)
        assert result['deviation_pct'] == 10.0
        assert result['is_anomaly'] is False

    def test_calculate_deviation_exceeds_max(self):
        """Value exceeding 1.2x max should be anomaly even if avg deviation is small."""
        result = self.comparer._calculate_deviation(150.0, 140.0, 120.0)
        # deviation_pct = (150-140)/140*100 = 7.1%, but 150 > 120*1.2=144
        assert result['is_anomaly'] is True

    def test_calculate_deviation_zero_avg(self):
        """Zero avg should return no anomaly."""
        result = self.comparer._calculate_deviation(10.0, 0.0, 0.0)
        assert result['deviation_pct'] == 0
        assert result['is_anomaly'] is False

    def test_calculate_deviation_none_avg(self):
        """None avg should return no anomaly."""
        result = self.comparer._calculate_deviation(10.0, None, None)
        assert result['deviation_pct'] == 0
        assert result['is_anomaly'] is False

    def test_extract_key_metrics_empty(self):
        """Empty parsed data should return empty metrics dict."""
        metrics = self.comparer._extract_key_metrics({})
        assert isinstance(metrics, dict)

    def test_extract_key_metrics_with_load_profile(self):
        """Should extract db_time_ratio from load_profile."""
        parsed_data = {
            'load_profile': {
                'computed': {
                    'db_time': 10.0,
                    'db_cpu': 2.0,
                }
            }
        }
        metrics = self.comparer._extract_key_metrics(parsed_data)
        assert isinstance(metrics, dict)
        assert 'db_time_ratio' in metrics
        assert metrics['db_time_ratio'] == 5.0

    def test_extract_key_metrics_with_instance_efficiency(self):
        """Should extract efficiency metrics from instance_efficiency dict."""
        parsed_data = {
            'instance_efficiency': {
                'Buffer Hit %': 95.5,
                'Library Hit %': 99.2,
            }
        }
        metrics = self.comparer._extract_key_metrics(parsed_data)
        assert isinstance(metrics, dict)
        assert 'buffer_cache_hit_ratio' in metrics

    def test_compare_returns_empty_without_report(self):
        """compare() with None report should return empty list."""
        result = self.comparer.compare(None, {}, None)
        assert isinstance(result, list)
        assert len(result) == 0

    def test_compare_returns_empty_without_parsed_data(self):
        """compare() with empty parsed_data should return empty list."""
        result = self.comparer.compare(object(), None, None)
        assert isinstance(result, list)
        assert len(result) == 0
