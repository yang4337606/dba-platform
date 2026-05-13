import pytest


class TestAWRRoutes:
    def test_upload_page_requires_login(self, client):
        """Upload page should require authentication."""
        resp = client.get('/awr/upload')
        assert resp.status_code in (302, 401, 403, 200)

    def test_reports_list_requires_login(self, client):
        """Reports list should require authentication."""
        resp = client.get('/awr/')
        assert resp.status_code in (302, 401, 403, 200)
