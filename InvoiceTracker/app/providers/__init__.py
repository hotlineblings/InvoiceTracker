"""
Warstwa abstrakcji dostawców danych fakturowych.
Umożliwia łatwą wymianę dostawcy (InFakt, wFirma, Fakturownia) bez zmian w logice synchronizacji.
"""
from .base import InvoiceProvider
from .factory import get_provider
from .infakt import InFaktProvider
from .wfirma import WFirmaProvider

__all__ = ['InvoiceProvider', 'get_provider', 'InFaktProvider', 'WFirmaProvider']
