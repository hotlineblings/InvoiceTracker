"""
Abstrakcyjna klasa bazowa dla dostawców faktur.
Definiuje interfejs wymagany przez wszystkie implementacje providerów.
"""
from abc import ABC, abstractmethod
from typing import Optional


class InvoiceProvider(ABC):
    """
    Abstrakcyjna klasa bazowa dla dostawców faktur.

    Każdy provider (InFakt, wFirma, Fakturownia) musi implementować te metody.
    Dane zwracane przez metody są znormalizowane do wspólnej struktury.
    """

    @abstractmethod
    def fetch_invoices(
        self,
        query_params: Optional[dict] = None,
        offset: int = 0,
        limit: int = 100
    ) -> list[dict]:
        """
        Pobiera listę faktur z API dostawcy.

        Args:
            query_params: Parametry filtrowania, np.:
                - payment_date_eq: dokładna data płatności (YYYY-MM-DD)
                - payment_date_gteq: data płatności >= (YYYY-MM-DD)
                - payment_date_lteq: data płatności <= (YYYY-MM-DD)
            offset: Offset paginacji
            limit: Limit wyników na stronę

        Returns:
            Lista słowników NormalizedInvoice:
            {
                "external_id": int,         # ID z API dostawcy
                "number": str,              # Numer faktury
                "invoice_date": date,       # Data wystawienia
                "payment_due_date": date,   # Termin płatności
                "gross_price": int,         # Kwota brutto (grosz!)
                "paid_price": int,          # Zapłacono (grosz!)
                "status": str,              # "sent", "printed", "paid"
                "currency": str,            # "PLN"
                "payment_method": str,      # Metoda płatności
                "client_id": str,           # ID klienta z API
            }
        """
        pass

    @abstractmethod
    def get_client_details(self, client_id: str) -> Optional[dict]:
        """
        Pobiera szczegóły klienta z API dostawcy.

        Args:
            client_id: ID klienta w systemie dostawcy

        Returns:
            Słownik NormalizedClient lub None:
            {
                "external_id": str,         # ID klienta z API
                "email": str | None,        # Email kontaktowy
                "nip": str | None,          # NIP firmy
                "company_name": str | None, # Nazwa firmy
                "first_name": str | None,   # Imię (osoba fizyczna)
                "last_name": str | None,    # Nazwisko
                "street": str | None,       # Ulica
                "street_number": str | None,
                "flat_number": str | None,
                "postal_code": str | None,
                "city": str | None,
            }
        """
        pass

    @abstractmethod
    def test_connection(self) -> bool:
        """
        Testuje połączenie z API dostawcy.

        Wykonuje rzeczywiste zapytanie do API (np. pobiera 1 fakturę)
        aby zweryfikować poprawność konfiguracji i dostępność usługi.

        Returns:
            True jeśli połączenie działa, False w przeciwnym razie
        """
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """
        Nazwa dostawcy (np. 'infakt', 'wfirma').

        Używana do logowania i identyfikacji providera.
        """
        pass
