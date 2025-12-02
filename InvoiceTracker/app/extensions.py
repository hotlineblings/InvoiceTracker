"""
Rozszerzenia Flask.
Inicjalizacja obiektów SQLAlchemy i Migrate oraz konfiguracja multi-tenancy.
"""
import logging
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import event
from sqlalchemy.orm import with_loader_criteria

log = logging.getLogger(__name__)

db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()

# Modele wymagające filtrowania po account_id
TENANT_MODELS: set = set()


def register_tenant_model(model_class):
    """Rejestruje model jako wymagający filtrowania tenant."""
    TENANT_MODELS.add(model_class)


def configure_tenant_filtering(app):
    """
    Konfiguruje automatyczne filtrowanie zapytań po account_id.
    Wywoływane w create_app() po init_app.

    WAŻNE: Ta funkcja MUSI być wywołana PO wykonaniu migracji
    2025120101_syncstatus_account_not_null, która wymusza NOT NULL
    na SyncStatus.account_id.
    """
    from .tenant_context import get_tenant, is_sudo
    from .models import Case, NotificationLog, NotificationSettings, SyncStatus, AccountScheduleSettings

    # Zarejestruj modele z account_id
    for model in [Case, NotificationLog, NotificationSettings, SyncStatus, AccountScheduleSettings]:
        register_tenant_model(model)
        log.debug(f"[tenant] Zarejestrowano model: {model.__name__}")

    @event.listens_for(db.session, 'do_orm_execute')
    def _apply_tenant_filter(orm_execute_state):
        """
        Event handler - automatycznie dodaje WHERE account_id = X.

        Wykonuje się dla KAŻDEGO zapytania ORM. Dodaje filtr account_id
        tylko gdy:
        1. Jest to zapytanie SELECT
        2. NIE jesteśmy w trybie sudo()
        3. Tenant ID jest ustawiony (get_tenant() != None)
        4. Model jest zarejestrowany w TENANT_MODELS
        """
        # Tylko dla SELECT
        if not orm_execute_state.is_select:
            return

        # Pomiń w trybie sudo
        if is_sudo():
            return

        # Zabezpieczenie przed rekurencją - sprawdź czy filtr już zastosowany
        if orm_execute_state.execution_options.get('_tenant_filter_applied', False):
            return

        # Pobierz tenant ID
        tenant_id = get_tenant()
        if tenant_id is None:
            # Brak kontekstu - może być login page, pozwól przejść
            return

        # Oznacz że filtr został zastosowany (anti-recursion)
        orm_execute_state.execution_options = orm_execute_state.execution_options.union(
            {'_tenant_filter_applied': True}
        )

        # Znajdź modele w zapytaniu które wymagają filtrowania
        for mapper in orm_execute_state.all_mappers:
            model_class = mapper.class_

            # Sprawdź czy model jest zarejestrowany
            if model_class not in TENANT_MODELS:
                continue

            # Sprawdź czy model ma account_id (dodatkowe zabezpieczenie)
            if not hasattr(model_class, 'account_id'):
                continue

            # Dodaj filtr
            orm_execute_state.statement = orm_execute_state.statement.options(
                with_loader_criteria(
                    model_class,
                    model_class.account_id == tenant_id,
                    include_aliases=True
                )
            )
            log.debug(f"[tenant] Dodano filtr account_id={tenant_id} dla {model_class.__name__}")

    log.info("[tenant] Konfiguracja multi-tenancy filtering zakończona")
