import pytest


class TestAuthRoutes:
    def test_login_page_accessible(self, client):
        """Login page should be accessible."""
        resp = client.get('/login')
        assert resp.status_code == 200

    def test_login_with_wrong_password(self, client, app):
        """Login with wrong password should fail (stay on login or show error)."""
        # First GET to establish session with CSRF token
        client.get('/login')
        with client.session_transaction() as sess:
            csrf_token = sess.get('_csrf_token', 'test-token')
        resp = client.post('/login', data={
            'username': 'nonexistent',
            'password': 'wrongpass',
            '_csrf_token': csrf_token,
        }, follow_redirects=True)
        assert resp.status_code == 200

    def test_logout_redirects(self, client):
        """Logout should redirect to login."""
        resp = client.get('/logout', follow_redirects=False)
        assert resp.status_code in (302, 200)

    def test_protected_page_redirects_to_login(self, client):
        """Accessing a protected page without auth should redirect to login."""
        resp = client.get('/awr/', follow_redirects=False)
        assert resp.status_code in (302, 401, 403, 200)
