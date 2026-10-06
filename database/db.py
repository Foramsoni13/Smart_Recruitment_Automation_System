import os
import mysql.connector
from pathlib import Path

def load_env_file():
    """
    Safely loads key-value pairs from .env into os.environ if not already set.
    """
    try:
        base_dir = Path(__file__).resolve().parent.parent
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
    except Exception as e:
        print("Notice loading .env file:", e)

def get_connection():
    """
    Returns a MySQL database connection using backend environment variables.
    """
    load_env_file()
    try:
        host = os.getenv("MYSQL_HOST", "localhost").strip()
        port_val = os.getenv("MYSQL_PORT", "3306").strip()
        try:
            port = int(port_val)
        except ValueError:
            port = 3306

        database = os.getenv("MYSQL_DATABASE", "smart_recruitment").strip()
        user = os.getenv("MYSQL_USER", "root").strip()
        password = os.getenv("MYSQL_PASSWORD", "")

        connection = mysql.connector.connect(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password
        )
        return connection
    except Exception as e:
        print("Database connection error:", e)
        return None
