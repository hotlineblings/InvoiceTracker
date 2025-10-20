# --- POCZĄTEK PLIKU: src/api/api_client.py (WERSJA FINALNA - bez 'fields' w get_client_details) ---
import os
import requests
import logging
from dotenv import load_dotenv

# Wczytanie zmiennych środowiskowych z pliku .env
load_dotenv()

class InFaktAPIClient:
    def __init__(self, api_key=None):
        """
        Initialize InFakt API Client.

        Args:
            api_key (str, optional): API key for InFakt. If not provided, will try to load from .env
        """
        # Jeśli api_key podany jawnie - użyj go (dla multi-tenancy)
        # W przeciwnym razie pobierz z .env (backward compatibility)
        if api_key:
            self.api_key = api_key
        else:
            self.api_key = os.getenv('INFAKT_API_KEY')

        self.base_url = "https://api.infakt.pl/api/v3"
        if not self.api_key or self.api_key == "YOUR_INFAKT_API_KEY":
            raise ValueError("Klucz API inFakt nie został ustawiony. Sprawdź plik .env lub zmienne środowiskowe!")

        # Nagłówki tylko dla żądań GET (bez Content-Type)
        self.get_headers = {
            'X-inFakt-ApiKey': self.api_key,
            'Accept': 'application/json',
        }
        # Nagłówki dla żądań POST/PUT (z Content-Type) - na przyszłość
        self.post_put_headers = {
            'X-inFakt-ApiKey': self.api_key,
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }

        self._session = requests.Session()
        self.log = logging.getLogger(__name__)
        if not logging.getLogger().handlers:
             logging.basicConfig(
                 level=logging.INFO,
                 format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
             )

    def test(self):
        self.log.info("InFaktAPIClient jest poprawnie skonfigurowany!")

    def list_invoices(self, offset=0, limit=100, fields=None, order=None, query_params=None):
        """Pobiera listę faktur. Używa nagłówków GET."""
        url = f"{self.base_url}/invoices.json"
        params = {"offset": offset, "limit": limit}
        if fields:
            if isinstance(fields, str): fields = fields.split(',')
            params['fields'] = ','.join(f.strip() for f in fields)
        if order: params['order'] = order
        if query_params: params.update(query_params)

        self.log.debug(f"Wywołanie list_invoices z params: {params}")
        try:
            response = self._session.get(url, headers=self.get_headers, params=params, timeout=30)
            self.log.debug(f"list_invoices ({url}) - Status: {response.status_code}, Nagłówki Żądania: {response.request.headers}")
            response.raise_for_status()
            data = response.json()
            self.log.info(f"Pobrano {len(data.get('entities', []))} faktur: offset={offset}, limit={limit}")
            return data.get('entities', [])
        except requests.exceptions.HTTPError as http_err:
            self.log.error(f"Błąd HTTP {http_err.response.status_code} przy list_invoices ({url}): {http_err} - Odpowiedź: {http_err.response.text}", exc_info=False) # Zmieniono exc_info na False dla zwięzłości
        except requests.exceptions.RequestException as req_err:
            status_code = getattr(getattr(req_err, 'response', None), 'status_code', 'N/A')
            response_text = getattr(getattr(req_err, 'response', None), 'text', 'N/A')
            self.log.error(f"Błąd RequestException przy list_invoices ({url}) (status: {status_code}): {req_err} - Odpowiedź: {response_text}", exc_info=False)
        except Exception as err:
            self.log.error(f"Inny błąd przy list_invoices ({url}): {err}", exc_info=True)
        return None

    def list_clients(self, offset=0, limit=100):
        """Pobiera listę klientów. Używa nagłówków GET."""
        url = f"{self.base_url}/clients.json"
        params = {"offset": offset, "limit": limit}
        self.log.debug(f"Wywołanie list_clients z params: {params}")
        try:
            response = self._session.get(url, headers=self.get_headers, params=params, timeout=30)
            self.log.debug(f"list_clients ({url}) - Status: {response.status_code}, Nagłówki Żądania: {response.request.headers}")
            response.raise_for_status()
            data = response.json()
            self.log.info(f"Pobrano {len(data.get('entities', []))} klientów: offset={offset}, limit={limit}")
            return data.get("entities", [])
        except requests.exceptions.HTTPError as http_err:
             self.log.error(f"Błąd HTTP {http_err.response.status_code} przy list_clients ({url}): {http_err} - Odpowiedź: {http_err.response.text}", exc_info=False)
        except requests.exceptions.RequestException as req_err:
            status_code = getattr(getattr(req_err, 'response', None), 'status_code', 'N/A')
            response_text = getattr(getattr(req_err, 'response', None), 'text', 'N/A')
            self.log.error(f"Błąd RequestException przy list_clients ({url}) (status: {status_code}): {req_err} - Odpowiedź: {response_text}", exc_info=False)
        except Exception as err:
            self.log.error(f"Inny błąd przy list_clients ({url}): {err}", exc_info=True)
        return None

    def get_client_details(self, client_id):
        """
        Pobiera szczegóły klienta. Używa nagłówków GET.
        **Nie używa parametru 'fields', aby uniknąć błędu 500.**
        """
        if not client_id:
             self.log.warning("Próba wywołania get_client_details bez client_id.")
             return None
        url = f"{self.base_url}/clients/{client_id}.json"
        # ***** KLUCZOWA ZMIANA: Usunięto parametr 'params' z wywołania GET *****
        self.log.debug(f"Wywołanie get_client_details dla ID: {client_id} (bez parametru 'fields')")
        try:
            # ***** Wywołanie GET bez parametru 'params' *****
            response = self._session.get(url, headers=self.get_headers, timeout=15)
            self.log.debug(f"get_client_details ({url}) - Status: {response.status_code}, Nagłówki Żądania: {response.request.headers}")
            response.raise_for_status()
            client_data = response.json() # Otrzymujemy pełny obiekt klienta
            self.log.info(f"Pobrano pełne szczegóły klienta ID: {client_id}")
            return client_data
        except requests.exceptions.HTTPError as http_err:
            if http_err.response.status_code == 404:
                self.log.warning(f"Klient ID: {client_id} nie został znaleziony w inFakt (404 Not Found) - URL: {url}")
            else:
                # Logujemy błąd, ale już bez pełnego tracebacku, żeby nie zaśmiecać logów przy częstych błędach 500
                self.log.error(f"Błąd HTTP {http_err.response.status_code} przy get_client_details ({url}): {http_err} - Odpowiedź: {http_err.response.text}", exc_info=False)
        except requests.exceptions.RequestException as req_err:
            status_code = getattr(getattr(req_err, 'response', None), 'status_code', 'N/A')
            response_text = getattr(getattr(req_err, 'response', None), 'text', 'N/A')
            self.log.error(f"Błąd RequestException przy get_client_details ({url}) (status: {status_code}): {req_err} - Odpowiedź: {response_text}", exc_info=False)
        except Exception as err:
            self.log.error(f"Inny błąd przy get_client_details ({url}): {err}", exc_info=True)
        return None

    # Funkcja get_multiple_client_details pozostaje bez zmian, nadal wywołuje (poprawioną) get_client_details
    def get_multiple_client_details(self, client_ids):
        client_details_map = {}
        unique_client_ids = set(filter(None, client_ids))
        if not unique_client_ids: return {}
        self.log.info(f"Pobieranie szczegółów dla {len(unique_client_ids)} klientów (iteracyjnie)...")
        for client_id in unique_client_ids:
            details = self.get_client_details(client_id)
            if details:
                client_details_map[str(client_id)] = details
            else:
               self.log.warning(f"Nie udało się pobrać szczegółów dla klienta ID: {client_id} w ramach get_multiple_client_details.")
        self.log.info(f"Zakończono get_multiple_client_details. Pobrano: {len(client_details_map)}/{len(unique_client_ids)}.")
        return client_details_map

# --- KONIEC PLIKU: src/api/api_client.py ---