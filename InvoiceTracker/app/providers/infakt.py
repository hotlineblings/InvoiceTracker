"""
Adapter dla InFakt API.
Implementacja InvoiceProvider dla systemu InFakt (https://www.infakt.pl).
"""
import logging
from datetime import datetime
from typing import Optional

import requests

from .base import InvoiceProvider

log = logging.getLogger(__name__)


class InFaktProvider(InvoiceProvider):
    """
    Adapter dla InFakt API.

    Obsługuje pobieranie faktur i danych klientów z InFakt,
    normalizując je do wspólnej struktury używanej przez aplikację.
    """

    BASE_URL = "https://api.infakt.pl/api/v3"

    def __init__(self, api_key: str):
        """
        Inicjalizuje provider InFakt.

        Args:
            api_key: Klucz API InFakt

        Raises:
            ValueError: Gdy api_key jest pusty lub None
        """
        if not api_key:
            raise ValueError("InFakt API key is required")

        self.api_key = api_key
        self._session = requests.Session()
        self._headers = {
            'X-inFakt-ApiKey': api_key,
            'Accept': 'application/json',
        }

    @property
    def provider_name(self) -> str:
        return "infakt"

    def fetch_invoices(
        self,
        query_params: Optional[dict] = None,
        offset: int = 0,
        limit: int = 100
    ) -> list[dict]:
        """
        Pobiera faktury z InFakt i normalizuje do ujednoliconej struktury.

        Args:
            query_params: Parametry filtrowania:
                - payment_date_eq: dokładna data płatności
                - payment_date_gteq: data płatności >=
                - payment_date_lteq: data płatności <=
            offset: Offset paginacji
            limit: Limit wyników

        Returns:
            Lista znormalizowanych słowników faktur
        """
        url = f"{self.BASE_URL}/invoices.json"

        params = {
            "offset": offset,
            "limit": limit,
            "fields": "id,uuid,number,invoice_date,gross_price,status,"
                      "client_id,payment_date,paid_price,payment_method,currency,paid_date",
            "order": "invoice_date desc"
        }

        # Mapowanie query_params na format InFakt
        if query_params:
            if "payment_date_eq" in query_params:
                params["q[payment_date_eq]"] = query_params["payment_date_eq"]
            if "payment_date_gteq" in query_params:
                params["q[payment_date_gteq]"] = query_params["payment_date_gteq"]
            if "payment_date_lteq" in query_params:
                params["q[payment_date_lteq]"] = query_params["payment_date_lteq"]

        try:
            log.debug(f"[InFaktProvider] fetch_invoices: offset={offset}, limit={limit}, params={query_params}")
            response = self._session.get(
                url, headers=self._headers, params=params, timeout=30
            )
            response.raise_for_status()
            raw_invoices = response.json().get('entities', [])

            log.info(f"[InFaktProvider] Pobrano {len(raw_invoices)} faktur z API")

            # Normalizacja do ujednoliconej struktury
            return [self._normalize_invoice(inv) for inv in raw_invoices]

        except requests.exceptions.HTTPError as http_err:
            log.error(
                f"[InFaktProvider] HTTP Error {http_err.response.status_code} "
                f"w fetch_invoices: {http_err}"
            )
        except requests.exceptions.RequestException as req_err:
            log.error(f"[InFaktProvider] Request Error w fetch_invoices: {req_err}")
        except Exception as e:
            log.error(f"[InFaktProvider] Nieoczekiwany błąd w fetch_invoices: {e}", exc_info=True)

        return []

    def get_client_details(self, client_id: str) -> Optional[dict]:
        """
        Pobiera dane klienta z InFakt.

        UWAGA: API InFakt zwraca HTTP 500 gdy podamy parametr 'fields'
        do endpointu /clients/{id}.json - dlatego NIE używamy tego parametru.

        Args:
            client_id: ID klienta w InFakt

        Returns:
            Znormalizowany słownik klienta lub None
        """
        if not client_id:
            log.warning("[InFaktProvider] get_client_details wywołane bez client_id")
            return None

        url = f"{self.BASE_URL}/clients/{client_id}.json"

        try:
            log.debug(f"[InFaktProvider] get_client_details dla client_id={client_id}")
            # KLUCZOWE: Brak parametru 'params' - InFakt zwraca 500 z 'fields'
            response = self._session.get(url, headers=self._headers, timeout=15)
            response.raise_for_status()
            raw_client = response.json()

            log.info(f"[InFaktProvider] Pobrano dane klienta ID: {client_id}")
            return self._normalize_client(raw_client)

        except requests.exceptions.HTTPError as http_err:
            if http_err.response.status_code == 404:
                log.warning(f"[InFaktProvider] Klient {client_id} nie znaleziony (404)")
            else:
                log.error(
                    f"[InFaktProvider] HTTP Error {http_err.response.status_code} "
                    f"w get_client_details: {http_err}"
                )
        except requests.exceptions.RequestException as req_err:
            log.error(f"[InFaktProvider] Request Error w get_client_details: {req_err}")
        except Exception as e:
            log.error(f"[InFaktProvider] Nieoczekiwany błąd w get_client_details: {e}", exc_info=True)

        return None

    def test_connection(self) -> bool:
        """
        Testuje połączenie wykonując zapytanie o 1 fakturę.

        Returns:
            True jeśli API odpowiada poprawnie, False w przeciwnym razie
        """
        try:
            url = f"{self.BASE_URL}/invoices.json"
            params = {"limit": 1, "fields": "id"}
            response = self._session.get(
                url, headers=self._headers, params=params, timeout=10
            )
            response.raise_for_status()
            log.info("[InFaktProvider] test_connection: OK")
            return True
        except Exception as e:
            log.error(f"[InFaktProvider] test_connection failed: {e}")
            return False

    def _normalize_invoice(self, raw: dict) -> dict:
        """
        Mapuje pola InFakt na ujednoliconą strukturę NormalizedInvoice.

        Args:
            raw: Surowe dane faktury z API InFakt

        Returns:
            Znormalizowany słownik faktury
        """
        invoice_date = None
        payment_due_date = None
        paid_date = None

        if raw.get('invoice_date'):
            try:
                invoice_date = datetime.strptime(
                    raw['invoice_date'], '%Y-%m-%d'
                ).date()
            except ValueError:
                pass

        if raw.get('payment_date'):
            try:
                payment_due_date = datetime.strptime(
                    raw['payment_date'], '%Y-%m-%d'
                ).date()
            except ValueError:
                pass

        if raw.get('paid_date'):
            try:
                paid_date = datetime.strptime(
                    raw['paid_date'], '%Y-%m-%d'
                ).date()
            except ValueError:
                pass

        return {
            "external_id": raw.get('id'),
            "number": raw.get('number', f"ID_{raw.get('id')}"),
            "invoice_date": invoice_date,
            "payment_due_date": payment_due_date,
            "gross_price": raw.get('gross_price', 0),
            "paid_price": raw.get('paid_price', 0),
            "status": raw.get('status', ''),
            "currency": raw.get('currency', 'PLN'),
            "payment_method": raw.get('payment_method'),
            "client_id": str(raw.get('client_id', '')),
            "paid_date": paid_date,
        }

    def _normalize_client(self, raw: dict) -> dict:
        """
        Mapuje pola klienta InFakt na ujednoliconą strukturę NormalizedClient.

        Args:
            raw: Surowe dane klienta z API InFakt

        Returns:
            Znormalizowany słownik klienta
        """
        return {
            "external_id": str(raw.get('id', '')),
            "email": raw.get('email'),
            "nip": raw.get('nip'),
            "company_name": raw.get('company_name'),
            "first_name": raw.get('first_name'),
            "last_name": raw.get('last_name'),
            "street": raw.get('street'),
            "street_number": raw.get('street_number'),
            "flat_number": raw.get('flat_number'),
            "postal_code": raw.get('postal_code'),
            "city": raw.get('city'),
        }
