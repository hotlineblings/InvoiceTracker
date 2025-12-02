"""
Multi-tenancy context management.
Przechowuje informację o aktualnym tenancie w sposób thread-safe.

Usage:
    # W request middleware (before_request):
    set_tenant(session['current_account_id'])

    # W background jobs:
    with tenant_context(account.id):
        cases = Case.query.all()  # automatycznie filtrowane

    # Dla operacji systemowych (bez filtrów):
    with sudo():
        all_accounts = Account.query.all()
"""
from contextvars import ContextVar
from contextlib import contextmanager
from typing import Optional

# Context variables (thread-safe, async-safe)
_current_tenant: ContextVar[Optional[int]] = ContextVar('current_tenant', default=None)
_sudo_mode: ContextVar[bool] = ContextVar('sudo_mode', default=False)


def set_tenant(account_id: int) -> None:
    """Ustawia aktualnego tenanta dla bieżącego kontekstu."""
    _current_tenant.set(account_id)


def get_tenant() -> Optional[int]:
    """Zwraca ID aktualnego tenanta lub None."""
    return _current_tenant.get()


def clear_tenant() -> None:
    """Czyści kontekst tenanta."""
    _current_tenant.set(None)


def is_sudo() -> bool:
    """Sprawdza czy jesteśmy w trybie sudo (bez filtrów)."""
    return _sudo_mode.get()


@contextmanager
def tenant_context(account_id: int):
    """
    Context manager do tymczasowego ustawienia tenanta.

    Usage:
        with tenant_context(account.id):
            cases = Case.query.all()  # automatycznie filtrowane
    """
    old_tenant = _current_tenant.get()
    _current_tenant.set(account_id)
    try:
        yield
    finally:
        _current_tenant.set(old_tenant)


@contextmanager
def sudo():
    """
    Context manager do tymczasowego wyłączenia filtrów.
    Używany dla operacji systemowych (CRON, scheduler).

    Usage:
        with sudo():
            all_accounts = Account.query.all()  # bez filtrów
    """
    old_sudo = _sudo_mode.get()
    _sudo_mode.set(True)
    try:
        yield
    finally:
        _sudo_mode.set(old_sudo)
