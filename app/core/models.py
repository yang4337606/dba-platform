from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


@dataclass
class Finding:
    name: str
    severity: str
    value: Optional[str] = None
    description: Optional[str] = None
    reason: Optional[str] = None


@dataclass
class EvidenceItem:
    name: str
    value: Any
    description: Optional[str] = None


@dataclass
class Recommendation:
    priority: str
    action: str
    reason: Optional[str] = None


@dataclass
class ProblemDomain:
    name: str
    value: float
    severity: str
    role: str
    score: float
    evidence: List[EvidenceItem] = field(default_factory=list)
    reason: str = ""
    recommendation: str = ""


@dataclass
class CauseFlow:
    title: str
    severity: str
    root: str
    amplifiers: List[str] = field(default_factory=list)
    symptoms: List[str] = field(default_factory=list)
    evidence: List[EvidenceItem] = field(default_factory=list)
    explanation: str = ""


@dataclass
class AnalysisContext:
    elapsed_minutes: float
    db_time_minutes: float
    aas: float
    workload_type: str = "Mixed"
    waiting_vs_cpu_model: str = "mixed"

    time_breakdown: List[EvidenceItem] = field(default_factory=list)
    top_events: List[Dict[str, Any]] = field(default_factory=list)
    top_sql_elapsed: List[Dict[str, Any]] = field(default_factory=list)
    top_sql_cpu: List[Dict[str, Any]] = field(default_factory=list)
    top_sql_gets: List[Dict[str, Any]] = field(default_factory=list)
    top_sql_reads: List[Dict[str, Any]] = field(default_factory=list)

    # SQL执行计划数据（来自 AWR SQL Plan Statistics / DBA_HIST_SQL_PLAN）
    sql_plan_statistics: Dict[str, Any] = field(default_factory=dict)
    # 完整 SQL Plan 树（每条 Top SQL 的执行计划步骤）
    sql_plan_tree: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)

    problem_domains: List[ProblemDomain] = field(default_factory=list)


@dataclass
class DiagnosisResult:
    analyzer_type: str
    title: str
    severity: str
    main_bottleneck: str
    summary: str

    conclusions: List[str] = field(default_factory=list)
    abnormal_findings: List[Finding] = field(default_factory=list)
    root_causes: List[str] = field(default_factory=list)
    evidence: Dict[str, List[EvidenceItem]] = field(default_factory=dict)
    recommendations: List[Recommendation] = field(default_factory=list)
    root_cause_flows: List[CauseFlow] = field(default_factory=list)

    raw_metrics: Dict[str, Any] = field(default_factory=dict)
    raw_sections: Dict[str, Any] = field(default_factory=dict)
    llm_deep_analysis: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict, converting nested dataclasses."""
        return asdict(self)
