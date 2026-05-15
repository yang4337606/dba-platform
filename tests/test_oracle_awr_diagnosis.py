from app.analyzers.oracle_awr.analyzer import OracleAwrAnalyzer


def test_cpu_bottleneck_when_db_cpu_high():
    analyzer = OracleAwrAnalyzer()
    assert analyzer.detect_main_bottleneck({"db_cpu_pct_db_time": 70}) == "CPU"


def test_io_bottleneck_when_user_io_high():
    analyzer = OracleAwrAnalyzer()
    assert analyzer.detect_main_bottleneck({"user_io_pct_db_time": 30}) == "I/O"


def test_commit_bottleneck_when_commit_high():
    analyzer = OracleAwrAnalyzer()
    assert analyzer.detect_main_bottleneck({"commit_pct_db_time": 20}) == "Commit"


def test_diagnosis_generates_expected_sections():
    analyzer = OracleAwrAnalyzer()
    result = analyzer.diagnose(
        {
            "db_cpu_pct_db_time": 89.0,
            "user_io_pct_db_time": 7.2,
            "commit_pct_db_time": 2.7,
            "parse_time_pct_db_time": 1.0,
            "top_events": [{"event": "DB CPU", "pct_db_time": 89.0}],
            "wait_classes": [{"wait_class": "User I/O", "pct_db_time": 7.2}],
            "top_sql_elapsed": [{"sql_id": "6k4tndpf1w4zk", "elapsed_time": "120"}],
            "top_sql_cpu": [],
            "top_sql_gets": [],
            "top_sql_reads": [],
        }
    )

    assert result.main_bottleneck == "CPU"
    assert result.conclusions
    assert result.abnormal_findings
    assert result.root_causes
    assert result.recommendations


def test_diagnosis_reports_parse_failure_for_invalid_awr_content():
    analyzer = OracleAwrAnalyzer()
    result = analyzer.analyze(b"\x01\x02not an awr html report")

    assert result.severity == "WARNING"
    assert result.main_bottleneck == "无法解析有效 AWR 内容"
    assert result.abnormal_findings[0].name == "AWR 报告解析失败"


def test_cpu_checkpoint_combo_bottleneck():
    analyzer = OracleAwrAnalyzer()
    result = analyzer.diagnose(
        {
            "parse_success": True,
            "db_cpu_pct_db_time": 49.35,
            "user_io_pct_db_time": 7.0,
            "configuration_pct_db_time": 3.6,
            "commit_pct_db_time": 0.2,
            "parse_time_pct_db_time": 1.68,
            "log_file_switch_checkpoint_incomplete_pct_db_time": 3.54,
            "log_file_switch_checkpoint_incomplete_avg_ms": 776,
            "log_file_sync_avg_ms": 2,
            "logical_read_blocks_per_sec": 1172444.9,
            "physical_read_blocks_per_sec": 163234.9,
            "read_io_mb_per_sec": 1275.3,
            "db_time_minutes": 1017.66,
            "elapsed_minutes": 60.17,
            "aas": 16.91,
            "db_cpu_seconds": 30130.06,
            "top_events": [
                {"event": "DB CPU", "time_s": 30130.06, "pct_db_time": 49.35},
                {"event": "log file switch (checkpoint incomplete)", "time_s": "2,163", "avg_wait_ms": 776, "pct_db_time": 3.54},
            ],
            "wait_classes": [],
            "top_sql_elapsed": [{"sql_id": "c83wqa2f8f7y5", "elapsed_time": "4,283.39"}],
            "top_sql_cpu": [],
            "top_sql_gets": [],
            "top_sql_reads": [],
        }
    )

    assert result.severity == "WARNING"
    assert result.main_bottleneck == "CPU"
    assert "DB CPU 是最大的时间消耗来源" in result.summary
    assert "Redo/LGWR 写入链路异常" in result.summary
    assert any("Redo/LGWR 写入链路异常" in finding.name for finding in result.abnormal_findings)


def test_temp_pressure_semantic_domain():
    analyzer = OracleAwrAnalyzer()
    result = analyzer.diagnose(
        {
            "parse_success": True,
            "db_cpu_pct_db_time": 10.0,
            "user_io_pct_db_time": 15.0,
            "configuration_pct_db_time": 0.0,
            "commit_pct_db_time": 0.0,
            "parse_time_pct_db_time": 0.0,
            "event_semantics": {
                "temp_pressure": {
                    "pct_db_time": 12.5,
                    "events": [{"event": "direct path write temp", "pct_db_time": 12.5}],
                }
            },
            "workload_type": "ETL",
            "waiting_vs_cpu_model": "waiting_dominant",
            "top_events": [{"event": "direct path write temp", "pct_db_time": 12.5}],
            "top_sql_elapsed": [],
            "top_sql_cpu": [],
            "top_sql_gets": [],
            "top_sql_reads": [],
        }
    )

    assert any("TEMP/PGA" in finding.name for finding in result.abnormal_findings)
    assert any("TEMP/PGA 压力" in cause for cause in result.root_causes)
