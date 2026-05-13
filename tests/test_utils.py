from app.awr.utils import (
    classify_wait_event,
    get_version_specific_notes,
    compute_composite_health_score,
    get_parameter_recommendations,
)


class TestClassifyWaitEvent:
    def test_empty_string(self):
        assert classify_wait_event('') == 'Other'

    def test_none(self):
        assert classify_wait_event(None) == 'Other'

    def test_enq_prefix(self):
        result = classify_wait_event('enq: TX - row lock contention')
        assert result == 'Application'

    def test_gc_prefix(self):
        result = classify_wait_event('gc current block busy')
        assert result == 'Cluster'

    def test_latch_prefix(self):
        result = classify_wait_event('latch: shared pool')
        assert result == 'Concurrency'

    def test_cursor_prefix(self):
        result = classify_wait_event('cursor: pin S wait on X')
        assert result == 'Concurrency'

    def test_unknown_event(self):
        result = classify_wait_event('some completely unknown event xyz')
        assert isinstance(result, str)


class TestGetVersionSpecificNotes:
    def test_empty_version(self):
        result = get_version_specific_notes('')
        assert result == []

    def test_none_version(self):
        result = get_version_specific_notes(None)
        assert result == []

    def test_returns_list(self):
        result = get_version_specific_notes('19.0.0.0.0')
        assert isinstance(result, list)


class TestComputeCompositeHealthScore:
    def test_no_issues(self):
        """No problems should give score of 100."""
        score = compute_composite_health_score([], [], [])
        assert score == 100

    def test_none_inputs(self):
        """None inputs should give score of 100."""
        score = compute_composite_health_score(None, None, None)
        assert score == 100

    def test_problems_reduce_score(self):
        """Problems should reduce the health score."""
        problems = [
            {'severity': 'high'},
            {'severity': 'medium'},
        ]
        score = compute_composite_health_score(problems, [], [])
        assert score < 100

    def test_critical_problems_reduce_more(self):
        """Critical problems should reduce score more than low ones."""
        critical = [{'severity': 'critical'}]
        low = [{'severity': 'low'}]
        score_critical = compute_composite_health_score(critical, [], [])
        score_low = compute_composite_health_score(low, [], [])
        assert score_critical < score_low

    def test_correlations_reduce_score(self):
        """Correlations should reduce score by 3 each."""
        correlations = [{'title': 'corr1'}, {'title': 'corr2'}]
        score = compute_composite_health_score([], correlations, [])
        assert score == 94  # 100 - 2*3

    def test_score_clamped_to_zero(self):
        """Score should never go below 0."""
        many_problems = [{'severity': 'critical'} for _ in range(20)]
        score = compute_composite_health_score(many_problems, [], [])
        assert score == 0

    def test_score_clamped_to_100(self):
        """Score should never exceed 100."""
        score = compute_composite_health_score([], [], [])
        assert score <= 100

    def test_health_level_key_used_as_fallback(self):
        """Should use health_level when severity is absent."""
        problems = [{'health_level': 'serious'}]
        score = compute_composite_health_score(problems, [], [])
        assert score == 92  # 100 - 8


class TestGetParameterRecommendations:
    def test_empty_inputs(self):
        result = get_parameter_recommendations([], {})
        assert isinstance(result, list)
        assert len(result) == 0

    def test_returns_list(self):
        problems = [{'title': 'buffer cache hit low', 'evidence': 'Buffer Cache', 'metric_name': 'buffer_cache_hit_ratio'}]
        result = get_parameter_recommendations(problems, {})
        assert isinstance(result, list)
