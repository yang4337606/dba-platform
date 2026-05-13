import os
import secrets

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Generate a persistent random key when none is provided via environment
_secret_key_file = os.path.join(BASE_DIR, 'instance', '.secret_key')
def _get_or_create_secret_key():
    env_key = os.environ.get('SECRET_KEY')
    if env_key:
        return env_key
    os.makedirs(os.path.dirname(_secret_key_file), exist_ok=True)
    if os.path.exists(_secret_key_file):
        with open(_secret_key_file, 'r') as f:
            return f.read().strip()
    key = secrets.token_hex(32)
    with open(_secret_key_file, 'w') as f:
        f.write(key)
    return key

class Config:
    SECRET_KEY = _get_or_create_secret_key()
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'app.db')}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB max upload

    # LLM Integration defaults
    LLM_PROVIDER = 'none'  # none, openai, deepseek, custom
    LLM_API_KEY = ''
    LLM_API_URL = ''
    LLM_MODEL = ''
