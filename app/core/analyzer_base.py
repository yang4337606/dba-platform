from abc import ABC, abstractmethod

from app.core.models import DiagnosisResult


class AnalyzerBase(ABC):
    analyzer_type: str
    display_name: str
    description: str = ""
    implemented: bool = True

    @abstractmethod
    def parse(self, input_data):
        pass

    @abstractmethod
    def extract_metrics(self, parsed_data):
        pass

    @abstractmethod
    def diagnose(self, metrics) -> DiagnosisResult:
        pass

    def analyze(self, input_data) -> DiagnosisResult:
        parsed_data = self.parse(input_data)
        metrics = self.extract_metrics(parsed_data)
        result = self.diagnose(metrics)
        result.raw_sections = parsed_data if isinstance(parsed_data, dict) else {}
        return result
