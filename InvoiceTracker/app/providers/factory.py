"""
Fabryka providerów.
Wybiera odpowiedni adapter na podstawie Account.provider_type.
"""
import logging
from typing import TYPE_CHECKING

from .base import InvoiceProvider
from .infakt import InFaktProvider
from .wfirma import WFirmaProvider

if TYPE_CHECKING:
    from ..models import Account

log = logging.getLogger(__name__)


# Mapa obsługiwanych providerów
PROVIDER_MAP: dict[str, type[InvoiceProvider]] = {
    'infakt': InFaktProvider,
    'wfirma': WFirmaProvider,
}


def get_provider(account: "Account") -> InvoiceProvider:
    """
    Zwraca odpowiedni provider dla danego konta.

    Args:
        account: Obiekt Account z provider_type i credentials

    Returns:
        Instancja InvoiceProvider

    Raises:
        ValueError: Gdy provider_type jest nieobsługiwany
        NotImplementedError: Gdy brak konfiguracji credentials dla providera
    """
    # Pobierz typ providera z konta (domyślnie 'infakt' dla wstecznej kompatybilności)
    provider_type = getattr(account, 'provider_type', 'infakt') or 'infakt'

    if provider_type not in PROVIDER_MAP:
        log.error(f"Nieobsługiwany provider: {provider_type}")
        raise ValueError(f"Nieobsługiwany provider: {provider_type}. "
                         f"Dostępne: {list(PROVIDER_MAP.keys())}")

    provider_class = PROVIDER_MAP[provider_type]

    # Konfiguracja credentials dla każdego typu providera
    if provider_type == 'infakt':
        # Użyj nowego formatu provider_settings z fallback na starą kolumnę
        settings = account.provider_settings or {}
        api_key = settings.get('api_key') or account.infakt_api_key
        log.debug(f"[factory] Tworzę InFaktProvider dla konta '{account.name}'")
        return provider_class(api_key=api_key)

    elif provider_type == 'wfirma':
        settings = account.provider_settings or {}
        log.debug(f"[factory] Tworzę WFirmaProvider dla konta '{account.name}'")
        return provider_class(
            access_key=settings.get('access_key'),
            secret_key=settings.get('secret_key'),
            app_key=settings.get('app_key'),
            company_id=settings.get('company_id'),
        )

    raise NotImplementedError(
        f"Brak konfiguracji credentials dla providera: {provider_type}"
    )
