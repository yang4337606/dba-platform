from app.analyzers.mysql_optimize.analyzer import MySQLOptimizeAnalyzer
from app.analyzers.oracle_ash.analyzer import OracleAshAnalyzer
from app.analyzers.oracle_awr.analyzer import OracleAwrAnalyzer
from app.analyzers.postgresql_optimize.analyzer import PostgreSQLOptimizeAnalyzer


ANALYZERS = {
    "oracle_awr": OracleAwrAnalyzer(),
    "oracle_ash": OracleAshAnalyzer(),
    "mysql_optimize": MySQLOptimizeAnalyzer(),
    "postgresql_optimize": PostgreSQLOptimizeAnalyzer(),
}


def get_analyzer(analyzer_type: str):
    analyzer = ANALYZERS.get(analyzer_type)
    if analyzer is None:
        raise ValueError(f"Unsupported analyzer type: {analyzer_type}")
    return analyzer


def list_analyzers():
    return [
        {
            "type": analyzer_type,
            "name": analyzer.display_name,
            "description": analyzer.description,
            "implemented": getattr(analyzer, "implemented", True),
        }
        for analyzer_type, analyzer in ANALYZERS.items()
    ]
