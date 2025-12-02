"""
Klient HTTP do lokalnej symulacji Cloud Tasks.
Wysyla POST na localhost zamiast do GCP.
"""
import logging
import requests

log = logging.getLogger(__name__)


def send_local_post(url: str, payload: dict, headers: dict = None) -> bool:
    """
    Wysyla zadanie HTTP POST na lokalny endpoint.

    Args:
        url: Pelny URL endpointu (np. http://localhost:8080/tasks/...)
        payload: Dane JSON do wyslania
        headers: Opcjonalne naglowki

    Returns:
        bool: True jesli sukces (status 2xx), False w przeciwnym razie
    """
    try:
        default_headers = {'Content-Type': 'application/json'}
        if headers:
            default_headers.update(headers)

        response = requests.post(url, json=payload, headers=default_headers, timeout=300)

        if response.ok:
            log.info(f"[LocalHTTP] POST {url} -> {response.status_code}")
            return True
        else:
            log.error(f"[LocalHTTP] POST {url} failed: {response.status_code} {response.text}")
            return False

    except requests.exceptions.RequestException as e:
        log.error(f"[LocalHTTP] Connection error to {url}: {e}")
        return False
