from app.core.analyzer_base import AnalyzerBase
from app.core.models import DiagnosisResult


class OracleAshAnalyzer(AnalyzerBase):
    analyzer_type = "oracle_ash"
    display_name = "Oracle ASH 报告分析"
    description = "预留模块：后续用于分析 Oracle ASH 报告中的活动会话、等待事件、SQL 和阻塞问题。"
    implemented = False

    def parse(self, input_data):
        raise NotImplementedError("Oracle ASH 分析模块尚未实现。")

    def extract_metrics(self, parsed_data):
        raise NotImplementedError("Oracle ASH 分析模块尚未实现。")

    def diagnose(self, metrics):
        return DiagnosisResult(
            analyzer_type=self.analyzer_type,
            title="Oracle ASH 智能诊断结果",
            severity="INFO",
            main_bottleneck="未实现",
            summary="Oracle ASH 分析模块尚未实现。",
            conclusions=["Oracle ASH 分析模块已预留，后续可扩展。"],
        )
