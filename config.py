import os
from pathlib import Path

def load_env_file():
    """
    Safely loads key-value pairs from .env into os.environ if not already present.
    """
    try:
        base_dir = Path(__file__).resolve().parent
        env_path = base_dir / ".env"
        if env_path.is_file():
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if k and k not in os.environ:
                            os.environ[k] = v
    except Exception:
        pass

load_env_file()

SECRET_KEY = os.getenv("SECRET_KEY", "smart_recruitment_secret_key")
APP_NAME = os.getenv("APP_NAME", "Smart Recruitment Automation System")
QR_CODE_FOLDER = os.getenv("QR_CODE_FOLDER", "static/qrcodes")

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@company.com").strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin_secret_pass")
