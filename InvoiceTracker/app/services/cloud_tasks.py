"""
Serwis Cloud Tasks - kolejkowanie zadan synchronizacji.
Na GAE uzywa Google Cloud Tasks API, lokalnie symuluje przez HTTP POST.
"""
import os
import logging
import json

log = logging.getLogger(__name__)

# Stale konfiguracyjne
GCP_PROJECT = os.environ.get('GOOGLE_CLOUD_PROJECT', 'invoicetracker-451108')
GCP_LOCATION = os.environ.get('CLOUD_TASKS_LOCATION', 'europe-west3')
GCP_QUEUE = os.environ.get('CLOUD_TASKS_QUEUE', 'INVOICETRACKER')


def is_gae_environment() -> bool:
    """Sprawdza czy aplikacja dziala na Google App Engine."""
    return os.environ.get('GAE_ENV') == 'standard'


def get_app_url() -> str:
    """Zwraca bazowy URL aplikacji."""
    if is_gae_environment():
        # Na GAE - uzyj domeny aplikacji
        project_id = os.environ.get('GOOGLE_CLOUD_PROJECT', 'invoicetracker-451108')
        return f"https://{project_id}.ew.r.appspot.com"
    else:
        # Lokalnie - localhost
        port = os.environ.get('PORT', '8080')
        return f"http://localhost:{port}"


def enqueue_sync_task(account_id: int, task_type: str = 'full') -> bool:
    """
    Kolejkuje zadanie synchronizacji dla konta.

    Na GAE: Tworzy task w Cloud Tasks queue
    Lokalnie: Wysyla HTTP POST bezposrednio na endpoint

    Args:
        account_id: ID konta do synchronizacji
        task_type: Typ synchronizacji ('full', 'new', 'update')

    Returns:
        bool: True jesli zadanie zostalo zakolejkowane/wykonane
    """
    payload = {
        'account_id': account_id,
        'task_type': task_type
    }

    target_url = f"{get_app_url()}/tasks/run_sync_for_account"

    if is_gae_environment():
        return _enqueue_cloud_task(target_url, payload)
    else:
        return _enqueue_local_task(target_url, payload)


def _enqueue_cloud_task(target_url: str, payload: dict) -> bool:
    """Tworzy zadanie w Google Cloud Tasks."""
    try:
        from google.cloud import tasks_v2

        client = tasks_v2.CloudTasksClient()

        parent = client.queue_path(GCP_PROJECT, GCP_LOCATION, GCP_QUEUE)

        task = {
            'http_request': {
                'http_method': tasks_v2.HttpMethod.POST,
                'url': target_url,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps(payload).encode(),
            }
        }

        response = client.create_task(parent=parent, task=task)
        log.info(f"[CloudTasks] Task created: {response.name}")
        return True

    except Exception as e:
        log.error(f"[CloudTasks] Failed to create task: {e}", exc_info=True)
        return False


def _enqueue_local_task(target_url: str, payload: dict) -> bool:
    """Symuluje Cloud Tasks przez lokalny HTTP POST."""
    from .local_http_client import send_local_post

    log.info(f"[CloudTasks] LOCAL MODE: Sending POST to {target_url}")

    # Dodaj naglowek symulujacy Cloud Tasks
    headers = {
        'X-AppEngine-QueueName': 'local-dev-queue',
        'X-CloudTasks-TaskName': f'local-sync-{payload.get("account_id")}'
    }

    return send_local_post(target_url, payload, headers)
