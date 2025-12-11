"""
Application Factory Pattern dla Flask.
Główny punkt wejścia dla aplikacji InvoiceTracker.
"""
import os
import logging
import urllib.parse

from flask import Flask, session, request, redirect, url_for, flash
from dotenv import load_dotenv

from .extensions import db, migrate, csrf, login_manager
from .blueprints import register_blueprints
from .cli import register_cli
# Import wszystkich modeli - wymagane dla Alembic autogenerate
from .models import (
    Account, AccountScheduleSettings, Case, Invoice,
    NotificationLog, NotificationSettings, SyncStatus, User
)

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
log = logging.getLogger(__name__)


def create_app(config_class=None):
    """
    Application Factory - tworzy i konfiguruje instancję Flask.

    Args:
        config_class: Klasa konfiguracji (opcjonalna). Jeśli None, auto-wykrywa środowisko.

    Returns:
        Flask: Skonfigurowana instancja aplikacji Flask.
    """
    # Ścieżki do templates i static - względne do katalogu InvoiceTracker (rodzic app/)
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    template_folder = os.path.join(parent_dir, 'templates')
    static_folder = os.path.join(parent_dir, 'static')

    app = Flask(__name__, template_folder=template_folder, static_folder=static_folder)

    # Konfiguracja
    _configure_app(app, config_class)

    # Inicjalizacja rozszerzeń
    _init_extensions(app)

    # Rejestracja blueprintów
    register_blueprints(app)

    # Rejestracja komend CLI
    register_cli(app)

    # Middleware i context processors
    _register_middleware(app)

    log.info("Instancja aplikacji Flask została utworzona.")
    return app


def _configure_app(app, config_class):
    """Konfiguruje aplikację Flask."""
    # Secret key
    app.secret_key = os.environ.get('SECRET_KEY')
    if not app.secret_key:
        log.critical("KRYTYCZNY BŁĄD: Brak SECRET_KEY!")
        raise ValueError("Brak SECRET_KEY!")

    # Wykryj środowisko: App Engine (unix socket) vs lokalne (Cloud SQL Proxy)
    is_app_engine = os.path.exists('/cloudsql')

    if is_app_engine:
        # App Engine - połączenie przez unix socket
        db_user = os.environ.get('DB_USER')
        db_password = os.environ.get('DB_PASSWORD')
        db_name = os.environ.get('DB_NAME')
        instance_connection_name = os.environ.get('INSTANCE_CONNECTION_NAME')

        if not all([db_user, db_password, db_name, instance_connection_name]):
            log.critical("KRYTYCZNY BŁĄD: Brak zmiennych środowiskowych bazy danych!")
            raise ValueError("Brakujące zmienne środowiskowe bazy danych!")

        safe_password = urllib.parse.quote_plus(db_password)
        unix_socket_path = f'/cloudsql/{instance_connection_name}'
        db_uri = f"postgresql+psycopg2://{db_user}:{safe_password}@/{db_name}?host={unix_socket_path}"
        log.info(f"DB Config (App Engine Socket): postgresql+psycopg2://{db_user}:*****@/{db_name}?host={unix_socket_path}")
    else:
        # Środowisko lokalne - użyj SQLALCHEMY_DATABASE_URI z .env
        db_uri = os.environ.get('SQLALCHEMY_DATABASE_URI')
        if not db_uri:
            log.critical("KRYTYCZNY BŁĄD: Brak SQLALCHEMY_DATABASE_URI w .env!")
            raise ValueError("Brak SQLALCHEMY_DATABASE_URI!")
        log.info(f"DB Config (Local/Cloud SQL Proxy): {db_uri.split('@')[0]}@***")

    app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # Legacy SMTP config (fallback)
    app.config['INFAKT_API_KEY'] = os.environ.get('INFAKT_API_KEY')
    app.config['SMTP_SERVER'] = os.environ.get('SMTP_SERVER')
    app.config['SMTP_PORT'] = int(os.environ.get('SMTP_PORT', 587))
    app.config['SMTP_USERNAME'] = os.environ.get('SMTP_USERNAME')
    app.config['SMTP_PASSWORD'] = os.environ.get('SMTP_PASSWORD')
    app.config['EMAIL_FROM'] = os.environ.get('EMAIL_FROM', app.config.get('SMTP_USERNAME'))

    if not app.config['INFAKT_API_KEY']:
        log.warning("Brak INFAKT_API_KEY!")
    if not all([app.config['SMTP_SERVER'], app.config['SMTP_USERNAME'], app.config['SMTP_PASSWORD']]):
        log.warning("Brak pełnej konfiguracji SMTP!")


def _init_extensions(app):
    """Inicjalizuje rozszerzenia Flask."""
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    # Flask-Login initialization
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        """Flask-Login user loader callback."""
        return User.query.get(int(user_id))

    # Exempt tasks blueprint from CSRF (called by Cloud Tasks, not browser)
    from .blueprints.tasks import tasks_bp
    csrf.exempt(tasks_bp)

    # Konfiguracja multi-tenancy filtering
    from .extensions import configure_tenant_filtering
    configure_tenant_filtering(app)

    # Dodaj min do Jinja2
    app.jinja_env.globals.update(min=min)


def _register_middleware(app):
    """Rejestruje middleware i context processors."""
    from .tenant_context import set_tenant, clear_tenant
    from flask_login import current_user

    @app.context_processor
    def inject_active_accounts():
        """
        Wstrzykuje listę dostępnych kont do wszystkich szablonów.
        UPDATED: Filtruje po dostępie użytkownika (User.accounts).
        """
        if current_user.is_authenticated:
            # Zwróć tylko konta do których użytkownik ma dostęp
            accounts = current_user.get_accessible_accounts()
            return dict(active_accounts=accounts)
        return dict(active_accounts=[])

    @app.context_processor
    def inject_current_account():
        """
        Wstrzykuje aktualnie wybrany Account do szablonów.
        Uzywane dla:
        - Wyswietlania statusu konfiguracji (is_fully_configured)
        - Banerów onboardingowych
        """
        account_id = session.get('current_account_id')
        if account_id:
            account = Account.query.get(account_id)
            return dict(current_account=account)
        return dict(current_account=None)

    @app.before_request
    def require_login():
        """
        Wymaga logowania i wyboru profilu dla wszystkich endpointów
        poza publicznymi (login, select_account, static, cron).

        3-KROKOWA LOGIKA BEZPIECZEŃSTWA:
        1. Sprawdź autentykację (current_user.is_authenticated)
        2. Sprawdź wybór profilu (session['current_account_id'])
        3. Weryfikuj dostęp do wybranego profilu (has_access_to_account)
        """
        # Endpointy które nie wymagają logowania
        public_endpoints = {
            'static',
            'auth.login',
            'auth.register',  # Rejestracja nowych użytkowników
            'auth.select_account',
            'auth.switch_account',
            'auth.logout',
            'sync.cron_run_sync',
            'sync.cron_run_mail',  # Cloud Tasks CRON endpoint - mail
            'tasks.run_sync_for_account',  # Cloud Tasks endpoint - sync
            'tasks.run_mail_for_account'  # Cloud Tasks endpoint - mail
        }

        # Sprawdź czy to endpoint publiczny
        if request.endpoint in public_endpoints:
            return None

        # CLI blueprint nie wymaga logowania
        is_cli_bp = hasattr(request, 'blueprint') and request.blueprint == 'cli'
        if is_cli_bp:
            return None

        # KROK 1: Sprawdź autentykację (NAJPIERW!)
        if not current_user.is_authenticated:
            # Wyczyść ewentualne śmieci z sesji
            session.pop('current_account_id', None)
            session.pop('current_account_name', None)
            session.pop('logged_in', None)
            flash("Musisz się zalogować, aby uzyskać dostęp.", "warning")
            return redirect(url_for('auth.login'))

        # KROK 2: Sprawdź wybór profilu
        if not session.get('current_account_id'):
            flash("Wybierz profil aby kontynuować.", "warning")
            return redirect(url_for('auth.select_account'))

        # KROK 3: Weryfikuj dostęp do wybranego profilu (BEZWARUNKOWE)
        account_id = session.get('current_account_id')
        if not current_user.has_access_to_account(account_id):
            log.warning(f"Security Alert: User {current_user.id} tried accessing unauthorized account {account_id}")
            session.pop('current_account_id', None)
            session.pop('current_account_name', None)
            flash("Brak dostępu do tego profilu.", "danger")
            return redirect(url_for('auth.select_account'))

    @app.before_request
    def set_tenant_context():
        """Ustawia kontekst tenanta z sesji."""
        account_id = session.get('current_account_id')
        if account_id:
            set_tenant(account_id)

    @app.teardown_request
    def clear_tenant_context(exception=None):
        """Czyści kontekst tenanta po zakończeniu requestu."""
        clear_tenant()
