"""
Blueprinty aplikacji.
"""
from .auth import auth_bp
from .cases import cases_bp
from .settings import settings_bp
from .sync import sync_bp
from .tasks import tasks_bp


def register_blueprints(app):
    """
    Rejestruje wszystkie blueprinty w aplikacji Flask.

    Args:
        app: Instancja Flask application
    """
    app.register_blueprint(auth_bp)
    app.register_blueprint(cases_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(sync_bp)
    app.register_blueprint(tasks_bp)
