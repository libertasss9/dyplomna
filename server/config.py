import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATABASE_DIR = BASE_DIR / "database"
DATABASE_PATH = Path(os.environ.get("DATA_ANALYZER_DATABASE", DATABASE_DIR / "app.sqlite3"))

CREATE_DEFAULT_ADMIN = os.environ.get("DATA_ANALYZER_CREATE_DEFAULT_ADMIN", "0").lower() in {
    "1",
    "true",
    "yes",
}
DEFAULT_ADMIN_USERNAME = os.environ.get("DATA_ANALYZER_ADMIN_USERNAME", "admin").strip().lower()
DEFAULT_ADMIN_PASSWORD = os.environ.get("DATA_ANALYZER_ADMIN_PASSWORD", "")

SESSION_TTL_SECONDS = int(os.environ.get("DATA_ANALYZER_SESSION_TTL_SECONDS", "86400"))
MAX_UPLOAD_MB = int(os.environ.get("DATA_ANALYZER_MAX_UPLOAD_MB", "50"))
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "DATA_ANALYZER_ALLOWED_ORIGINS",
        "http://127.0.0.1:5500,http://localhost:5500",
    ).split(",")
    if origin.strip()
]
FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "0").lower() in {"1", "true", "yes"}
