"""
Adapter dla wFirma API (api2.wfirma.pl).
Implementacja InvoiceProvider dla systemu wFirma.

Specyfika API wFirma:
- Autoryzacja przez 3 custom headers: accessKey, secretKey, appKey
- company_id jako parametr URL (nie w body)
- Metoda POST dla wszystkich endpointów
- Paginacja: page/limit (nie offset/limit)
- Ceny jako float PLN (wymagana konwersja na grosze przez Decimal)
- Response może mieć strukturę {"0": {...}, "1": {...}} zamiast [...]
"""
import logging
from datetime import datetime
from decimal import Decimal
from typing import Optional

import requests

from .base import InvoiceProvider

log = logging.getLogger(__name__)


class WFirmaProvider(InvoiceProvider):
    """
    Adapter dla wFirma API.

    Obsługuje pobieranie faktur i danych kontrahentów z wFirma,
    normalizując je do wspólnej struktury używanej przez aplikację.
    """

    BASE_URL = "https://api2.wfirma.pl"

    def __init__(self, access_key: str, secret_key: str, app_key: str, company_id: str):
        """
        Inicjalizuje provider wFirma.

        Args:
            access_key: Klucz dostępu API wFirma
            secret_key: Klucz sekretny API wFirma
            app_key: Klucz aplikacji API wFirma
            company_id: ID firmy w wFirma

        Raises:
            ValueError: Gdy którykolwiek z wymaganych parametrów jest pusty
        """
        if not all([access_key, secret_key, app_key, company_id]):
            missing = []
            if not access_key:
                missing.append('access_key')
            if not secret_key:
                missing.append('secret_key')
            if not app_key:
                missing.append('app_key')
            if not company_id:
                missing.append('company_id')
            raise ValueError(f"wFirma: brak wymaganych credentials: {', '.join(missing)}")

        self.company_id = company_id
        self._session = requests.Session()
        # UWAGA: Custom headers - NIE używamy Basic Auth!
        self._headers = {
            "accessKey": access_key,
            "secretKey": secret_key,
            "appKey": app_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    @property
    def provider_name(self) -> str:
        return "wfirma"

    def _build_url(self, endpoint: str) -> str:
        """
        Buduje pełny URL z wymaganymi parametrami.

        wFirma wymaga parametrów inputFormat, outputFormat i company_id w URL.
        """
        return (
            f"{self.BASE_URL}/{endpoint}"
            f"?inputFormat=json&outputFormat=json&company_id={self.company_id}"
        )

    def _build_conditions(self, query_params: dict) -> list[dict]:
        """
        Mapuje query_params (styl InFakt) na conditions (styl wFirma).

        Args:
            query_params: Parametry w formacie InFakt:
                - payment_date_eq: dokładna data
                - payment_date_gteq: data >=
                - payment_date_lteq: data <=

        Returns:
            Lista conditions w formacie wFirma
        """
        conditions = []
        if query_params:
            if "payment_date_gteq" in query_params:
                conditions.append({
                    "condition": {
                        "field": "paymentdate",
                        "operator": "ge",
                        "value": query_params["payment_date_gteq"]
                    }
                })
            if "payment_date_lteq" in query_params:
                conditions.append({
                    "condition": {
                        "field": "paymentdate",
                        "operator": "le",
                        "value": query_params["payment_date_lteq"]
                    }
                })
            if "payment_date_eq" in query_params:
                conditions.append({
                    "condition": {
                        "field": "paymentdate",
                        "operator": "eq",
                        "value": query_params["payment_date_eq"]
                    }
                })
        return conditions

    def _parse_invoice_list(self, data) -> list[dict]:
        """
        Konwertuje odpowiedź wFirma na listę faktur.

        wFirma może zwracać:
        - listę: [...]
        - obiekt z numerycznymi kluczami: {"0": {...}, "1": {...}}

        Args:
            data: Dane z response['invoices']

        Returns:
            Lista słowników faktur
        """
        if data is None:
            return []

        if isinstance(data, list):
            return data

        if isinstance(data, dict):
            # Obsługa {"0": {...}, "1": {...}} -> [...]
            try:
                # Sortuj po kluczach numerycznych i zwróć wartości
                sorted_items = sorted(
                    data.items(),
                    key=lambda x: int(x[0]) if x[0].isdigit() else 0
                )
                return [v for k, v in sorted_items]
            except (ValueError, AttributeError) as e:
                log.warning(f"[WFirmaProvider] Błąd parsowania numeric keys: {e}")
                return list(data.values())

        log.warning(f"[WFirmaProvider] Nieoczekiwany typ danych invoices: {type(data)}")
        return []

    def fetch_invoices(
        self,
        query_params: Optional[dict] = None,
        offset: int = 0,
        limit: int = 100
    ) -> list[dict]:
        """
        Pobiera faktury z wFirma i normalizuje do ujednoliconej struktury.

        Args:
            query_params: Parametry filtrowania (styl InFakt)
            offset: Offset paginacji (konwertowany na page)
            limit: Limit wyników

        Returns:
            Lista znormalizowanych słowników faktur
        """
        url = self._build_url("invoices/find")
        page = (offset // limit) + 1
        conditions = self._build_conditions(query_params or {})

        payload = {
            "invoices": {
                "parameters": {
                    "limit": limit,
                    "page": page,
                    "conditions": conditions
                }
            }
        }

        log.info(
            f"[WFirmaProvider] POST {self.BASE_URL}/invoices/find "
            f"(page={page}, limit={limit}, conditions={len(conditions)})"
        )

        try:
            response = self._session.post(
                url,
                headers=self._headers,
                json=payload,
                timeout=30
            )
            log.debug(f"[WFirmaProvider] Response status: {response.status_code}")
            response.raise_for_status()

            data = response.json()

            # Sprawdź status odpowiedzi
            status = data.get("status", {})
            if status.get("code") != "OK":
                log.error(f"[WFirmaProvider] API error: {status}")
                return []

            # Parsuj listę faktur (obsługa numeric keys)
            invoices_data = data.get("invoices", {})
            raw_invoices = self._parse_invoice_list(invoices_data)

            log.info(f"[WFirmaProvider] Pobrano {len(raw_invoices)} faktur z API")

            # Normalizuj do ujednoliconej struktury
            return [self._normalize_invoice(inv) for inv in raw_invoices]

        except requests.exceptions.HTTPError as e:
            log.error(
                f"[WFirmaProvider] HTTP {e.response.status_code} "
                f"w fetch_invoices: {e}"
            )
            # Log response body for debugging (bez credentials)
            try:
                error_body = e.response.text[:500]
                log.debug(f"[WFirmaProvider] Response body: {error_body}")
            except Exception:
                pass
        except requests.exceptions.RequestException as e:
            log.error(f"[WFirmaProvider] Request error w fetch_invoices: {e}")
        except Exception as e:
            log.error(
                f"[WFirmaProvider] Nieoczekiwany błąd w fetch_invoices: {e}",
                exc_info=True
            )

        return []

    def _normalize_invoice(self, raw: dict) -> dict:
        """
        Mapuje pola wFirma na ujednoliconą strukturę NormalizedInvoice.

        Mapowanie pól (potwierdzone z dokumentacji wFirma):
        - id -> external_id
        - fullnumber -> number
        - date -> invoice_date
        - paymentdate -> payment_due_date
        - total -> gross_price (Decimal * 100)
        - alreadypaid -> paid_price (Decimal * 100)
        - paymentstate -> status
        - contractor -> client data

        Args:
            raw: Surowe dane faktury z API wFirma

        Returns:
            Znormalizowany słownik faktury
        """
        # wFirma może zwracać {"invoice": {...}} lub bezpośrednio {...}
        inv = raw.get("invoice", raw)

        # Parsowanie dat
        invoice_date = None
        payment_due_date = None

        if inv.get("date"):
            try:
                invoice_date = datetime.strptime(inv["date"], "%Y-%m-%d").date()
            except ValueError:
                log.warning(f"[WFirmaProvider] Nieprawidłowy format daty: {inv.get('date')}")

        if inv.get("paymentdate"):
            try:
                payment_due_date = datetime.strptime(inv["paymentdate"], "%Y-%m-%d").date()
            except ValueError:
                log.warning(f"[WFirmaProvider] Nieprawidłowy format paymentdate: {inv.get('paymentdate')}")

        # DECIMAL PRECISION - krytyczne dla poprawności finansowej!
        # wFirma zwraca float PLN, system wymaga int groszy
        # Defensywna obsługa None/empty string
        total_raw = inv.get("total")
        if total_raw is None or total_raw == "":
            gross_price = 0
        else:
            gross_price = int(Decimal(str(total_raw)) * 100)

        # paid_price - pole "alreadypaid" potwierdzone w dokumentacji
        paid_raw = inv.get("alreadypaid")
        if paid_raw is None or paid_raw == "":
            paid_price = 0
        else:
            paid_price = int(Decimal(str(paid_raw)) * 100)

        # Contractor (zagnieżdżony obiekt)
        contractor = inv.get("contractor", {}) or {}
        client_id = str(contractor.get("id", "")) if contractor else ""

        # external_id MUSI być int (zgodność z Invoice.id: db.Integer)
        external_id = inv.get("id")
        if external_id is not None:
            external_id = int(external_id)

        return {
            "external_id": external_id,
            "number": inv.get("fullnumber", f"ID_{inv.get('id')}"),
            "invoice_date": invoice_date,
            "payment_due_date": payment_due_date,
            "gross_price": gross_price,
            "paid_price": paid_price,
            "status": self._map_status(inv.get("paymentstate", "")),
            "currency": inv.get("currency", "PLN"),
            "payment_method": inv.get("paymentmethod"),
            "client_id": client_id,
            "paid_date": None,  # API wFirma nie zwraca paid_date w /invoices/find
        }

    def _map_status(self, wfirma_status: str) -> str:
        """
        Mapuje status wFirma na status InvoiceTracker.

        wFirma statusy (potwierdzone z dokumentacji):
        - 'paid' -> faktura opłacona
        - 'unpaid' -> faktura nieopłacona
        - 'undefined' -> status nieokreślony

        Args:
            wfirma_status: Status z API wFirma (paymentstate)

        Returns:
            Status w formacie InvoiceTracker: 'sent' lub 'paid'
        """
        if not wfirma_status:
            return "sent"

        status_map = {
            "paid": "paid",
            "unpaid": "sent",
            "undefined": "sent",
        }
        return status_map.get(wfirma_status.lower(), "sent")

    def get_client_details(self, client_id: str) -> Optional[dict]:
        """
        Pobiera dane kontrahenta z wFirma.

        Args:
            client_id: ID kontrahenta w wFirma

        Returns:
            Znormalizowany słownik klienta lub None
        """
        if not client_id:
            log.warning("[WFirmaProvider] get_client_details wywołane bez client_id")
            return None

        url = self._build_url(f"contractors/get/{client_id}")

        log.debug(f"[WFirmaProvider] POST contractors/get/{client_id}")

        try:
            # wFirma wymaga POST nawet dla GET-like operacji
            response = self._session.post(
                url,
                headers=self._headers,
                json={"contractors": {"parameters": {"limit": 1}}},
                timeout=15
            )
            response.raise_for_status()
            data = response.json()

            # Parsuj odpowiedź - może mieć strukturę {"0": {"contractor": {...}}}
            contractors_data = data.get("contractors", {})

            # Obsługa numeric keys
            if isinstance(contractors_data, dict):
                first_item = contractors_data.get("0", {})
                contractor = first_item.get("contractor", first_item)
            else:
                contractor = {}

            if not contractor:
                log.warning(f"[WFirmaProvider] Nie znaleziono kontrahenta {client_id}")
                return None

            log.info(f"[WFirmaProvider] Pobrano dane kontrahenta ID: {client_id}")

            return self._normalize_client(contractor)

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                log.warning(f"[WFirmaProvider] Kontrahent {client_id} nie znaleziony (404)")
            else:
                log.error(
                    f"[WFirmaProvider] HTTP {e.response.status_code} "
                    f"w get_client_details: {e}"
                )
        except requests.exceptions.RequestException as e:
            log.error(f"[WFirmaProvider] Request error w get_client_details: {e}")
        except Exception as e:
            log.error(
                f"[WFirmaProvider] Nieoczekiwany błąd w get_client_details: {e}",
                exc_info=True
            )

        return None

    def _normalize_client(self, raw: dict) -> dict:
        """
        Mapuje pola kontrahenta wFirma na ujednoliconą strukturę NormalizedClient.

        UWAGA: wFirma może nie rozdzielać first_name/last_name - tylko "name".
        Logika w update_db.py obsłuży to fallbackiem.

        Args:
            raw: Surowe dane kontrahenta z API wFirma

        Returns:
            Znormalizowany słownik klienta
        """
        return {
            "external_id": str(raw.get("id", "")),
            "email": raw.get("email"),
            "nip": raw.get("nip"),
            "company_name": raw.get("name"),
            "first_name": raw.get("first_name"),  # może być None
            "last_name": raw.get("last_name"),    # może być None
            "street": raw.get("street"),
            "street_number": raw.get("street_number"),  # może być None
            "flat_number": raw.get("flat_number"),      # może być None
            "postal_code": raw.get("zip"),
            "city": raw.get("city"),
        }

    def test_connection(self) -> bool:
        """
        Testuje połączenie z API wFirma.

        Wykonuje zapytanie o 1 fakturę aby zweryfikować credentials.

        Returns:
            True jeśli połączenie działa, False w przeciwnym razie
        """
        try:
            url = self._build_url("invoices/find")
            payload = {
                "invoices": {
                    "parameters": {
                        "limit": 1,
                        "page": 1
                    }
                }
            }

            response = self._session.post(
                url,
                headers=self._headers,
                json=payload,
                timeout=10
            )
            response.raise_for_status()

            data = response.json()
            status = data.get("status", {})
            ok = status.get("code") == "OK"

            log.info(f"[WFirmaProvider] test_connection: {'OK' if ok else 'FAILED'}")
            return ok

        except Exception as e:
            log.error(f"[WFirmaProvider] test_connection failed: {e}")
            return False
