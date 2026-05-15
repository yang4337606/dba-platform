from app.core.analyzer_base import AnalyzerBase
from app.core.models import DiagnosisResult


class PostgreSQLOptimizeAnalyzer(AnalyzerBase):
    analyzer_type = "postgresql_optimize"
    display_name = "PostgreSQL 数据库优化分析"
    description = "预留模块：后续用于分析 PostgreSQL 慢 SQL、等待事件、缓存命中率、连接数、vacuum 和索引问题。"
    implemented = False

    def parse(self, input_data):
        raise NotImplementedError("PostgreSQL 优化分析模块尚未实现。")

    def extract_metrics(self, parsed_data):
        raise NotImplementedError("PostgreSQL 优化分析模块尚未实现。")

    def diagnose(self, metrics):
        return DiagnosisResult(
            analyzer_type=self.analyzer_type,
            title="PostgreSQL 数据库优化诊断结果",
            severity="INFO",
            main_bottleneck="未实现",
            summary="PostgreSQL 优化分析模块尚未实现。",
            conclusions=["PostgreSQL 优化分析模块已预留，后续可扩展。"],
        )
