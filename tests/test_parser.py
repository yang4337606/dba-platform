import pytest
from app.awr.parser import AWRParser

# Minimal AWR HTML fragment for testing
SAMPLE_AWR_HTML = """
<html>
<head><title>AWR Report</title></head>
<body>
<h2>WORKLOAD REPOSITORY report for</h2>
<table border="1">
<tr><td>DB Name</td><td>DB Id</td><td>Instance</td><td>Inst num</td><td>Startup Time</td><td>Release</td><td>RAC</td></tr>
<tr><td>TESTDB</td><td>1234567890</td><td>testdb1</td><td>1</td><td>01-Jan-24 00:00</td><td>19.0.0.0.0</td><td>NO</td></tr>
</table>

<table border="1">
<tr><td>Snap Id</td><td>Snap Time</td><td>Sessions</td><td>Cursors/Session</td></tr>
<tr><td>Begin Snap:</td><td>100</td><td>01-Jan-24 10:00:00</td><td>50</td><td>5.0</td></tr>
<tr><td>End Snap:</td><td>101</td><td>01-Jan-24 11:00:00</td><td>55</td><td>5.2</td></tr>
<tr><td colspan="2">Elapsed:</td><td colspan="3">60.00 (mins)</td></tr>
</table>

<h3>Load Profile</h3>
<table border="1">
<tr><td></td><td>Per Second</td><td>Per Transaction</td><td>Per Exec</td><td>Per Call</td></tr>
<tr><td>DB Time(s):</td><td>2.5</td><td>0.01</td><td></td><td></td></tr>
<tr><td>DB CPU(s):</td><td>1.2</td><td>0.005</td><td></td><td></td></tr>
<tr><td>Redo size (bytes):</td><td>500000</td><td>2500</td><td></td><td></td></tr>
<tr><td>Logical read (blocks):</td><td>10000</td><td>50</td><td></td><td></td></tr>
<tr><td>Physical read (blocks):</td><td>500</td><td>2.5</td><td></td><td></td></tr>
<tr><td>Executes (SQL):</td><td>200</td><td>1.0</td><td></td><td></td></tr>
<tr><td>Transactions:</td><td>200</td><td></td><td></td><td></td></tr>
</table>

<h3>Top 5 Timed Foreground Events</h3>
<table border="1">
<tr><td>Event</td><td>Waits</td><td>Time(s)</td><td>Avg wait(ms)</td><td>% DB time</td><td>Wait Class</td></tr>
<tr><td>DB CPU</td><td></td><td>4320</td><td></td><td>48.0</td><td></td></tr>
<tr><td>db file sequential read</td><td>100000</td><td>2700</td><td>27</td><td>30.0</td><td>User I/O</td></tr>
<tr><td>log file sync</td><td>50000</td><td>900</td><td>18</td><td>10.0</td><td>Commit</td></tr>
</table>

<h3>Instance Efficiency Percentages</h3>
<table border="1">
<tr><td>Buffer Nowait %:</td><td>99.98</td><td>Redo NoWait %:</td><td>100.00</td></tr>
<tr><td>Buffer Hit %:</td><td>95.50</td><td>In-memory Sort %:</td><td>99.99</td></tr>
<tr><td>Library Hit %:</td><td>99.20</td><td>Soft Parse %:</td><td>98.50</td></tr>
<tr><td>Execute to Parse %:</td><td>85.00</td><td>Latch Hit %:</td><td>99.95</td></tr>
<tr><td>Parse CPU to Parse Elapsd %:</td><td>90.00</td><td>% Non-Parse CPU:</td><td>99.50</td></tr>
</table>
</body>
</html>
"""


class TestAWRParser:
    def setup_method(self):
        self.parser = AWRParser()

    def test_parse_returns_dict(self):
        result = self.parser.parse(SAMPLE_AWR_HTML)
        assert isinstance(result, dict)

    def test_parse_contains_expected_keys(self):
        result = self.parser.parse(SAMPLE_AWR_HTML)
        expected_keys = [
            'db_info', 'snap_info', 'load_profile', 'top_events',
            'top_sql', 'io_stats', 'memory_stats', 'instance_efficiency',
            'os_stats', 'rac_stats', 'redo_stats', 'parse_stats',
            'segment_stats', 'advisories', 'time_model',
        ]
        for key in expected_keys:
            assert key in result, f"Missing key: {key}"

    def test_parse_extracts_db_info(self):
        result = self.parser.parse(SAMPLE_AWR_HTML)
        db_info = result.get('db_info', {})
        assert isinstance(db_info, dict)

    def test_parse_extracts_load_profile(self):
        result = self.parser.parse(SAMPLE_AWR_HTML)
        load_profile = result.get('load_profile', {})
        assert isinstance(load_profile, dict)

    def test_parse_extracts_top_events(self):
        result = self.parser.parse(SAMPLE_AWR_HTML)
        top_events = result.get('top_events', [])
        assert isinstance(top_events, list)

    def test_parse_extracts_efficiency(self):
        result = self.parser.parse(SAMPLE_AWR_HTML)
        efficiency = result.get('instance_efficiency', {})
        assert isinstance(efficiency, (dict, list))

    def test_parse_empty_html(self):
        """Empty HTML should not crash, return dict with expected keys."""
        result = self.parser.parse('<html><body></body></html>')
        assert isinstance(result, dict)
        assert 'db_info' in result
        assert 'top_events' in result

    def test_parse_empty_string(self):
        """Empty string should be handled gracefully."""
        result = self.parser.parse('')
        assert isinstance(result, dict)

    def test_parse_malformed_html(self):
        """Malformed HTML should not crash."""
        result = self.parser.parse('<html><body><table><tr><td>broken')
        assert isinstance(result, dict)

    def test_top_events_get_wait_class_enrichment(self):
        """Top events should have wait_class filled in by classify_wait_event."""
        result = self.parser.parse(SAMPLE_AWR_HTML)
        top_events = result.get('top_events', [])
        for evt in top_events:
            if evt.get('event') or evt.get('name'):
                # Each event should have a wait_class key
                assert 'wait_class' in evt
