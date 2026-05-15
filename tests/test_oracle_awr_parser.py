from app.analyzers.oracle_awr.parser import parse_awr


def test_parser_extracts_key_awr_sections():
    html = """
    <html>
      <head><title>AWR Report for DB: TESTDB, Inst: test1, Snaps: 1-2</title></head>
      <body>
        <h3>Top Timed Events</h3>
        <table summary="Top Timed Events">
          <tr><th>Event</th><th>Wait Class</th><th>% DB time</th></tr>
          <tr><td>DB CPU</td><td>CPU</td><td>89.0</td></tr>
        </table>
        <h3>Wait Classes</h3>
        <table summary="Wait Classes">
          <tr><th>Wait Class</th><th>% DB time</th></tr>
          <tr><td>User I/O</td><td>7.2</td></tr>
        </table>
        <h3>SQL ordered by Elapsed Time</h3>
        <table summary="SQL ordered by Elapsed Time">
          <tr><th>SQL Id</th><th>Elapsed Time (s)</th></tr>
          <tr><td>6k4tndpf1w4zk</td><td>120</td></tr>
        </table>
      </body>
    </html>
    """

    parsed = parse_awr(html)

    assert parsed["db_info"]["db_name"] == "TESTDB"
    assert parsed["top_events"][0]["event"] == "DB CPU"
    assert parsed["wait_classes"][0]["wait_class"] == "User I/O"
    assert parsed["top_sql_elapsed"][0]["sql_id"] == "6k4tndpf1w4zk"
