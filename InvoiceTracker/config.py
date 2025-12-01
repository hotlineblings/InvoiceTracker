"""
Konfiguracja aplikacji Flask.
Klasy konfiguracyjne dla różnych środowisk.
"""
import os
import urllib.parse
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Bazowa konfiguracja."""
    SECRET_KEY = os.environ.get('SECRET_KEY')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Legacy SMTP (fallback - preferowane są ustawienia per-account w DB)
    INFAKT_API_KEY = os.environ.get('INFAKT_API_KEY')
    SMTP_SERVER = os.environ.get('SMTP_SERVER')
    SMTP_PORT = int(os.environ.get('SMTP_PORT', 587))
    SMTP_USERNAME = os.environ.get('SMTP_USERNAME')
    SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD')
    EMAIL_FROM = os.environ.get('EMAIL_FROM')


class DevelopmentConfig(Config):
    """Konfiguracja dla środowiska lokalnego (Cloud SQL Proxy)."""
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get('SQLALCHEMY_DATABASE_URI')


class ProductionConfig(Config):
    """Konfiguracja dla App Engine (unix socket)."""
    DEBUG = False

    @property
    def SQLALCHEMY_DATABASE_URI(self):
        db_user = os.environ.get('DB_USER')
        db_password = os.environ.get('DB_PASSWORD')
        db_name = os.environ.get('DB_NAME')
        instance_connection_name = os.environ.get('INSTANCE_CONNECTION_NAME')

        if not all([db_user, db_password, db_name, instance_connection_name]):
            raise ValueError("Brakujące zmienne środowiskowe bazy danych dla App Engine!")

        safe_password = urllib.parse.quote_plus(db_password)
        unix_socket_path = f'/cloudsql/{instance_connection_name}'
        return f"postgresql+psycopg2://{db_user}:{safe_password}@/{db_name}?host={unix_socket_path}"


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}


def get_config_name():
    """Automatycznie wykrywa środowisko."""
    if os.path.exists('/cloudsql'):
        return 'production'
    return 'development'
