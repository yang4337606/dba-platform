from app.analyzers.oracle_awr.metrics import extract_awr_metrics


def test_extracts_db_cpu_pct():
    metrics = extract_awr_metrics(
        {
            "top_events": [{"event": "DB CPU", "pct_db_time": "89.0"}],
            "wait_classes": [],
            "time_model": {},
        }
    )
    assert metrics["db_cpu_pct_db_time"] == 89.0


def test_extracts_db_cpu_pct_from_time_model_when_not_in_top_events():
    metrics = extract_awr_metrics(
        {
            "top_events": [{"event": "log file sync", "pct_db_time": "5.8"}],
            "wait_classes": [],
            "time_model": {"DB CPU": {"pct_db_time": "76.55"}},
        }
    )
    assert metrics["db_cpu_pct_db_time"] == 76.55


def test_extracts_user_io_pct():
    metrics = extract_awr_metrics(
        {
            "top_events": [],
            "wait_classes": [{"wait_class": "User I/O", "pct_db_time": "7.2"}],
            "time_model": {},
        }
    )
    assert metrics["user_io_pct_db_time"] == 7.2


def test_extracts_commit_pct():
    metrics = extract_awr_metrics(
        {
            "top_events": [],
            "wait_classes": [{"wait_class": "Commit", "pct_db_time": "2.7"}],
            "time_model": {},
        }
    )
    assert metrics["commit_pct_db_time"] == 2.7


def test_extracts_top_sql():
    metrics = extract_awr_metrics(
        {
            "top_events": [],
            "wait_classes": [],
            "time_model": {},
            "top_sql_elapsed": [{"sql_id": "6k4tndpf1w4zk"}],
        }
    )
    assert metrics["top_sql_elapsed"][0]["sql_id"] == "6k4tndpf1w4zk"


def test_event_semantics_detect_temp_and_redo_pipeline():
    metrics = extract_awr_metrics(
        {
            "top_events": [
                {"event": "direct path write temp", "pct_db_time": "12.5", "time_s": "100"},
                {"event": "log buffer space", "pct_db_time": "8.0", "time_s": "64"},
            ],
            "wait_classes": [],
            "time_model": {},
        }
    )

    assert metrics["event_semantics"]["temp_pressure"]["pct_db_time"] == 12.5
    assert metrics["event_semantics"]["redo_pipeline"]["pct_db_time"] == 8.0
    assert metrics["waiting_vs_cpu_model"] == "waiting_dominant"


def test_detects_idle_workload_type():
    metrics = extract_awr_metrics(
        {
            "top_events": [],
            "wait_classes": [],
            "time_model": {"DB CPU": {"pct_db_time": "1.0"}},
        }
    )
    assert metrics["workload_type"] == "Idle"


def test_detects_read_heavy_workload_as_olap_not_etl():
    metrics = extract_awr_metrics(
        {
            "top_events": [
                {"event": "direct path read", "pct_db_time": "3.5"},
                {"event": "db file scattered read", "pct_db_time": "2.0"},
            ],
            "wait_classes": [{"wait_class": "User I/O", "pct_db_time": "6.0"}],
            "time_model": {"DB CPU": {"pct_db_time": "45.0"}},
            "load_profile": {
                "Read IO (MB):": {"per_second": "650"},
                "Write IO (MB):": {"per_second": "1"},
                "Physical read (blocks):": {"per_second": "80000"},
            },
        }
    )

    assert metrics["workload_type"] == "OLAP"


def test_classifies_top_sql_behaviors():
    metrics = extract_awr_metrics(
        {
            "top_events": [],
            "wait_classes": [],
            "time_model": {},
            "top_sql_gets": [{"sql_id": "abc", "buffer_gets": "2,000,000"}],
            "top_sql_reads": [{"sql_id": "def", "physical_reads": "300,000"}],
        }
    )
    categories = {item["category"] for item in metrics["top_sql_behaviors"]}
    assert "高逻辑读 SQL" in categories
    assert "高物理读 SQL" in categories
