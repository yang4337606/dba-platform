import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or os.urandom(32).hex()
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024
    UPLOAD_EXTENSIONS = [".html", ".htm", ".txt"]
