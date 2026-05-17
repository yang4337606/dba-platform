import logging
import os
import warnings

logger = logging.getLogger(__name__)


class Config:
    _secret_key = os.environ.get("SECRET_KEY")
    if not _secret_key:
        _secret_key = os.urandom(32).hex()
        warnings.warn(
            "SECRET_KEY is not set via environment variable. "
            "A random key has been generated. Sessions will not "
            "persist across restarts. Set SECRET_KEY in production.",
            RuntimeWarning,
            stacklevel=2,
        )
    SECRET_KEY = _secret_key
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB, reasonable for AWR HTML
    UPLOAD_EXTENSIONS = [".html", ".htm", ".txt"]
