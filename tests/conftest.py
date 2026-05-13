import pytest
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.models import db as _db, User


class TestConfig:
    TESTING = True
    SECRET_KEY = 'test-secret-key'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = '/tmp/test_uploads'
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024
    WTF_CSRF_ENABLED = False
    LLM_PROVIDER = 'none'
    LLM_API_KEY = ''
    LLM_API_URL = ''
    LLM_MODEL = ''


@pytest.fixture(scope='session')
def app():
    app = create_app()
    app.config.from_object(TestConfig)
    # Re-init db with test config
    with app.app_context():
        _db.drop_all()
        _db.create_all()
        # Create test user
        user = User(username='testuser', email='test@test.com', role='admin')
        user.set_password('testpass')
        _db.session.add(user)
        _db.session.commit()
    yield app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    with app.app_context():
        yield _db


@pytest.fixture
def auth_client(client, app):
    """Client that is already logged in."""
    with client.session_transaction() as sess:
        sess['_user_id'] = '1'
        sess['_csrf_token'] = 'test-csrf-token'
    return client
