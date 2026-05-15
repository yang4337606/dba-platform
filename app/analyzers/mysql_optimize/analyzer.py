from app.core.analyzer_base import AnalyzerBase
from app.core.models import DiagnosisResult


class MySQLOptimizeAnalyzer(AnalyzerBase):
    analyzer_type = "mysql_optimize"
    display_name = "MySQL 数据库优化分析"
    description = "预留模块：后续用于分析 MySQL 慢 SQL、状态变量、InnoDB 指标、复制状态和性能瓶颈。"
    implemented = False

    def parse(self, input_data):
        raise NotImplementedError("MySQL 优化分析模块尚未实现。")

    def extract_metrics(self, parsed_data):
        raise NotImplementedError("MySQL 优化分析模块尚未实现。")

    def diagnose(self, metrics):
        return DiagnosisResult(
            analyzer_type=self.analyzer_type,
            title="MySQL 数据库优化诊断结果",
            severity="INFO",
            main_bottleneck="未实现",
            summary="MySQL 数据库优化分析模块尚未实现。",
            conclusions=["MySQL 优化分析模块已预留，后续可扩展。"],
        )
