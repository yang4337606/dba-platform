import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'awr-platform-secret-key-change-in-production')
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'app.db')}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB max upload

    # LLM Integration defaults
    LLM_PROVIDER = 'none'  # none, openai, deepseek, custom
    LLM_API_KEY = ''
    LLM_API_URL = ''
    LLM_MODEL = ''
