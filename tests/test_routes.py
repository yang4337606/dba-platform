from app import create_app


def test_index_lists_analyzers():
    app = create_app()
    app.config["TESTING"] = True

    client = app.test_client()
    response = client.get("/")

    assert response.status_code == 200
    assert "数据库智能诊断平台".encode("utf-8") in response.data
    assert "Oracle AWR".encode("utf-8") in response.data
    assert "预留".encode("utf-8") in response.data
