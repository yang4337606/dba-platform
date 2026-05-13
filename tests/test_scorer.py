from app.awr.scorer import MetricScorer


class TestMetricScorer:
    def setup_method(self):
        self.scorer = MetricScorer()

    def test_score_metric_healthy_higher_worse(self):
        """Value below warning threshold (higher_worse) should be healthy."""
        result = self.scorer.score_metric('aas_per_cpu', 0.3)
        assert result['level'] == 'healthy'

    def test_score_metric_warning_higher_worse(self):
        """Value between warning and serious (higher_worse) should be warning."""
        result = self.scorer.score_metric('aas_per_cpu', 0.8)
        assert result['level'] == 'warning'

    def test_score_metric_serious_higher_worse(self):
        """Value above serious threshold (higher_worse) should be serious."""
        result = self.scorer.score_metric('aas_per_cpu', 1.5)
        assert result['level'] == 'serious'

    def test_score_metric_healthy_lower_worse(self):
        """Value above warning threshold (lower_worse) should be healthy."""
        result = self.scorer.score_metric('buffer_cache_hit_ratio', 99.0)
        assert result['level'] == 'healthy'

    def test_score_metric_warning_lower_worse(self):
        """Value between serious and warning (lower_worse) should be warning."""
        result = self.scorer.score_metric('buffer_cache_hit_ratio', 92.0)
        assert result['level'] == 'warning'

    def test_score_metric_serious_lower_worse(self):
        """Value below serious threshold (lower_worse) should be serious."""
        result = self.scorer.score_metric('buffer_cache_hit_ratio', 85.0)
        assert result['level'] == 'serious'

    def test_score_metric_unknown_metric(self):
        """Unknown metric name should return healthy with no evidence."""
        result = self.scorer.score_metric('nonexistent_metric', 50.0)
        assert result['level'] == 'healthy'
        assert result['evidence'] == ''

    def test_score_metric_returns_thresholds(self):
        """Result should include warning and serious thresholds."""
        result = self.scorer.score_metric('aas_per_cpu', 0.8)
        assert result['warning_threshold'] == 0.7
        assert result['serious_threshold'] == 1.0

    def test_score_all_with_empty_data(self):
        """Empty parsed data should return empty problems list."""
        problems = self.scorer.score_all({})
        assert isinstance(problems, list)
        assert len(problems) == 0

    def test_score_all_with_none_data(self):
        """None parsed data should return empty problems list."""
        problems = self.scorer.score_all(None)
        assert isinstance(problems, list)
        assert len(problems) == 0

    def test_default_thresholds_exist(self):
        """Default thresholds should be defined and non-empty."""
        assert hasattr(MetricScorer, 'DEFAULT_THRESHOLDS')
        assert len(MetricScorer.DEFAULT_THRESHOLDS) > 0

    def test_custom_thresholds_override(self):
        """Custom thresholds should override defaults."""
        custom = {'aas_per_cpu': (0.5, 0.8, 'ratio', 'higher_worse')}
        scorer = MetricScorer(custom_thresholds=custom)
        assert scorer.thresholds['aas_per_cpu'] == (0.5, 0.8, 'ratio', 'higher_worse')

    def test_score_all_detects_load_profile_problem(self):
        """score_all should detect problems in load_profile computed metrics."""
        parsed_data = {
            'load_profile': {
                'computed': {
                    'db_time': 10.0,
                    'db_cpu': 2.0,  # db_time_ratio = 5.0, serious threshold = 3.0
                }
            }
        }
        problems = self.scorer.score_all(parsed_data)
        assert isinstance(problems, list)
        metric_names = [p['metric_name'] for p in problems]
        assert 'db_time_ratio' in metric_names

    def test_score_all_detects_instance_efficiency_problem(self):
        """score_all should detect low buffer cache hit from instance_efficiency."""
        parsed_data = {
            'instance_efficiency': {
                'Buffer Hit %': 80.0,  # below serious threshold of 90
            }
        }
        problems = self.scorer.score_all(parsed_data)
        assert isinstance(problems, list)
        metric_names = [p['metric_name'] for p in problems]
        assert 'buffer_cache_hit_ratio' in metric_names

    def test_score_metric_evidence_non_empty_on_warning(self):
        """Evidence string should be non-empty when level is not healthy."""
        result = self.scorer.score_metric('aas_per_cpu', 0.8)
        assert result['level'] == 'warning'
        assert len(result['evidence']) > 0

    def test_score_metric_evidence_empty_on_healthy(self):
        """Evidence string should be empty when level is healthy."""
        result = self.scorer.score_metric('aas_per_cpu', 0.3)
        assert result['level'] == 'healthy'
        assert result['evidence'] == ''
