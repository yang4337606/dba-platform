"""
Oracle AWR Report Analysis Engine
Modules: Parser -> Scorer -> Correlator -> Baseline -> LLM -> Learning
"""
from .constants import (
    BUILTIN_RULES, BUILTIN_RULES_VERSION, PARAMETER_RECOMMENDATIONS,
    VERSION_SPECIFIC_KNOWLEDGE, WAIT_EVENT_CLASS, WAIT_CLASS_EVENTS,
)
from .utils import (
    _safe_float, classify_wait_event, get_parameter_recommendations,
    get_version_specific_notes, compute_composite_health_score,
)
from .parser import AWRParser
from .scorer import MetricScorer
from .correlator import CorrelationAnalyzer
from .advisory import (
    AdvisoryAnalyzer, TimeModelAnalyzer, WaitHistogramAnalyzer,
    get_advisory_recommendations, get_time_model_findings,
    get_wait_histogram_findings,
)
from .classifier import WorkloadClassifier, classify_workload
from .baseline import BaselineComparer
from .learning import LearningEngine
from .llm import LLMIntegration
from .sql_patterns import SQLAntiPatternDetector
