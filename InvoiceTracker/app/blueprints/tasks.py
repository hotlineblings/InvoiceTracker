"""
Blueprint zadan w tle (Cloud Tasks).
Endpoint wywolywany przez Cloud Tasks lub lokalny HTTP client.
"""
import logging
from flask import Blueprint, request, jsonify

from ..services.update_db import run_full_sync
from ..tenant_context import tenant_context

log = logging.getLogger(__name__)

tasks_bp = Blueprint('tasks', __name__)


def _is_valid_task_request() -> bool:
    """
    Weryfikuje czy zadanie pochodzi z Cloud Tasks lub lokalnego dev.

    Na GAE: Sprawdza naglowek X-AppEngine-QueueName (ustawiany przez Cloud Tasks)
    Lokalnie: Akceptuje zadania z naglowkiem X-AppEngine-QueueName (symulowany)
    """
    queue_name = request.headers.get('X-AppEngine-QueueName')

    if queue_name:
        log.debug(f"[Tasks] Valid task request from queue: {queue_name}")
        return True

    # Dodatkowe sprawdzenie - czy to request od Cloud Tasks na GAE?
    task_name = request.headers.get('X-CloudTasks-TaskName')
    if task_name:
        log.debug(f"[Tasks] Valid task request, task name: {task_name}")
        return True

    return False


@tasks_bp.route('/tasks/run_sync_for_account', methods=['POST'])
def run_sync_for_account():
    """
    Endpoint wykonujacy synchronizacje dla konta.
    Wywolywany przez Cloud Tasks (prod) lub HTTP POST (local).

    Expected JSON body:
        {
            "account_id": int,
            "task_type": str  # 'full', 'new', 'update'
        }
    """
    # Weryfikacja zrodla zadania
    if not _is_valid_task_request():
        log.warning("[Tasks] Unauthorized request to /tasks/run_sync_for_account")
        return jsonify({
            'status': 'error',
            'message': 'Unauthorized - not a valid task request'
        }), 403

    # Parsowanie danych
    data = request.get_json()
    if not data:
        return jsonify({
            'status': 'error',
            'message': 'Missing JSON body'
        }), 400

    account_id = data.get('account_id')
    task_type = data.get('task_type', 'full')

    if not account_id:
        return jsonify({
            'status': 'error',
            'message': 'Missing account_id'
        }), 400

    try:
        log.info(f"[Tasks] Starting {task_type} sync for account_id={account_id}")

        # Ustaw tenant context dla background task
        # Cloud Tasks nie ma sesji, wiec musimy recznie ustawic kontekst
        with tenant_context(account_id):
            # Wykonaj synchronizacje w kontekscie tenanta
            processed = run_full_sync(account_id)

        log.info(f"[Tasks] Completed {task_type} sync for account_id={account_id}, processed={processed}")

        return jsonify({
            'status': 'success',
            'account_id': account_id,
            'task_type': task_type,
            'processed': processed
        }), 200

    except Exception as e:
        log.error(f"[Tasks] Error in sync for account_id={account_id}: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500


@tasks_bp.route('/tasks/run_mail_for_account', methods=['POST'])
def run_mail_for_account():
    """
    Endpoint wykonujacy wysylke maili dla konta.
    Wywolywany przez Cloud Tasks (prod) lub background thread (local).

    Expected JSON body:
        {
            "account_id": int
        }
    """
    if not _is_valid_task_request():
        log.warning("[Tasks] Unauthorized request to /tasks/run_mail_for_account")
        return jsonify({
            'status': 'error',
            'message': 'Unauthorized - not a valid task request'
        }), 403

    data = request.get_json()
    if not data:
        return jsonify({'status': 'error', 'message': 'Missing JSON body'}), 400

    account_id = data.get('account_id')
    if not account_id:
        return jsonify({'status': 'error', 'message': 'Missing account_id'}), 400

    try:
        log.info(f"[Tasks] Starting mail task for account_id={account_id}")

        from ..services.scheduler import run_mail_for_single_account
        from flask import current_app

        app = current_app._get_current_object()
        run_mail_for_single_account(app, account_id)

        log.info(f"[Tasks] Completed mail task for account_id={account_id}")

        return jsonify({
            'status': 'success',
            'account_id': account_id,
            'task_type': 'mail'
        }), 200

    except Exception as e:
        log.error(f"[Tasks] Error in mail task for account_id={account_id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500
