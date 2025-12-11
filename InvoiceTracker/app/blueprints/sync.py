"""
Blueprint synchronizacji.
Reczna synchronizacja, CRON endpoint, status synchronizacji, diagnostyka maili.
"""
import os
import logging
from datetime import date, datetime, timedelta, timezone as dt_timezone, time as dt_time
from zoneinfo import ZoneInfo

from flask import Blueprint, render_template, redirect, url_for, request, flash, session, jsonify

from ..models import Account, SyncStatus, AccountScheduleSettings
from ..services import diagnostic_service
from ..services.cloud_tasks import enqueue_sync_task, enqueue_mail_task
from ..forms import ManualSyncForm

log = logging.getLogger(__name__)

sync_bp = Blueprint('sync', __name__)


@sync_bp.route('/manual_sync', methods=['POST'])
def manual_sync():
    """Reczna synchronizacja dla wybranego profilu (POST z CSRF)."""
    form = ManualSyncForm()
    if not session.get('logged_in'):
        flash("Musisz byc zalogowany, aby uruchomic synchronizacje.", "danger")
        return redirect(url_for('auth.login'))

    account_id = session.get('current_account_id')
    if not account_id:
        flash("Wybierz profil przed synchronizacja.", "warning")
        return redirect(url_for('auth.select_account'))

    # LAZY VALIDATION: Sprawdz czy konto ma skonfigurowany API provider
    account = Account.query.get(account_id)
    if account and not account.is_provider_configured:
        flash("Skonfiguruj najpierw klucz API w ustawieniach, aby uruchomic synchronizacje.", "warning")
        return redirect(url_for('settings.settings_view'))

    if form.validate_on_submit():
        account_name = session.get('current_account_name', f'ID:{account_id}')
        log.info(f"Zadanie recznej synchronizacji dla konta '{account_name}' (ID: {account_id}).")

        # Zakolejkuj task (Cloud Tasks na GAE, HTTP POST lokalnie)
        success = enqueue_sync_task(account_id, 'full')

        if success:
            flash(f"Synchronizacja uruchomiona dla profilu '{account_name}'. Wyniki pojawia sie w statusie synchronizacji.", "info")
        else:
            flash("Blad uruchamiania synchronizacji.", "danger")

    return redirect(url_for('cases.active_cases'))


@sync_bp.route('/cron/run_sync')
def cron_run_sync():
    """
    Smart CRON endpoint - uruchamiany co godzine.
    Sprawdza ktore konta wymagaja synchronizacji o danej godzinie UTC
    i uruchamia sync tylko dla nich.
    """
    is_cron_request = request.headers.get('X-Appengine-Cron') == 'true'

    # W srodowisku lokalnym pozwol na wywolanie CRON endpoint
    # gdy ustawiono ALLOW_LOCAL_CRON=true w .env
    is_local_dev = os.environ.get('GAE_ENV') != 'standard'
    allow_local_cron = os.environ.get('ALLOW_LOCAL_CRON', 'false').lower() == 'true'

    if not is_cron_request:
        if is_local_dev and allow_local_cron:
            log.info("[Smart CRON] LOCAL DEV MODE: Pozwalam na wywolanie CRON bez naglowka X-Appengine-Cron")
        else:
            log.warning("Nieautoryzowana proba wywolania /cron/run_sync (nie z Cron).")
            return jsonify({"status": "ignored", "message": "Request not from App Engine Cron"}), 200

    now_utc = datetime.now(dt_timezone.utc)
    current_hour = now_utc.hour
    current_minute = now_utc.minute

    log.info(f"[Smart CRON] Otrzymano zadanie z App Engine Cron: /cron/run_sync. Czas UTC: {current_hour:02d}:{current_minute:02d}")

    active_accounts = Account.query.filter_by(is_active=True).all()

    if not active_accounts:
        log.warning("[Smart CRON] Brak aktywnych kont.")
        return jsonify({"status": "no_accounts", "message": "No active accounts"}), 200

    accounts_to_sync = []

    for account in active_accounts:
        settings = AccountScheduleSettings.get_for_account(account.id)

        if not settings.is_sync_enabled:
            log.info(f"[Smart CRON] Pomijam {account.name} - synchronizacja wylaczona")
            continue

        if current_hour == settings.sync_hour:
            accounts_to_sync.append(account)
            log.info(f"[Smart CRON] Konto {account.name} (ID: {account.id}) - zaplanowana synchronizacja o {settings.sync_hour:02d}:{settings.sync_minute:02d} UTC")
        else:
            log.debug(f"[Smart CRON] Pomijam {account.name} - zaplanowane: {settings.sync_hour:02d}:{settings.sync_minute:02d} UTC, teraz: {current_hour:02d}:{current_minute:02d} UTC")

    if not accounts_to_sync:
        log.info(f"[Smart CRON] Brak kont do synchronizacji o godzinie {current_hour:02d}:{current_minute:02d} UTC")
        return jsonify({
            "status": "no_sync_needed",
            "message": f"No accounts scheduled for sync at {current_hour:02d}:{current_minute:02d} UTC",
            "current_time_utc": f"{current_hour:02d}:{current_minute:02d}"
        }), 200

    log.info(f"[Smart CRON] Kolejkuje synchronizacje dla {len(accounts_to_sync)} kont...")

    tasks_queued = 0
    for account in accounts_to_sync:
        log.info(f"[Smart CRON] Kolejkuje sync dla konta: {account.name} (ID: {account.id})")
        if enqueue_sync_task(account.id, 'full'):
            tasks_queued += 1

    log.info(f"[Smart CRON] Zakolejkowano {tasks_queued} zadan Cloud Tasks")
    return jsonify({
        "status": "accepted",
        "message": f"Sync tasks queued for {tasks_queued} accounts",
        "tasks_queued": tasks_queued,
        "current_time_utc": f"{current_hour:02d}:{current_minute:02d}",
        "accounts": [{"id": acc.id, "name": acc.name} for acc in accounts_to_sync]
    }), 202


@sync_bp.route('/cron/run_mail')
def cron_run_mail():
    """
    Smart CRON endpoint dla wysylki maili - uruchamiany co godzine.
    Sprawdza ktore konta wymagaja wysylki o danej godzinie UTC.
    """
    is_cron_request = request.headers.get('X-Appengine-Cron') == 'true'

    is_local_dev = os.environ.get('GAE_ENV') != 'standard'
    allow_local_cron = os.environ.get('ALLOW_LOCAL_CRON', 'false').lower() == 'true'

    if not is_cron_request:
        if is_local_dev and allow_local_cron:
            log.info("[Smart CRON Mail] LOCAL DEV MODE: Pozwalam na wywolanie bez naglowka")
        else:
            log.warning("Nieautoryzowana proba wywolania /cron/run_mail")
            return jsonify({"status": "ignored", "message": "Request not from App Engine Cron"}), 200

    now_utc = datetime.now(dt_timezone.utc)
    current_hour = now_utc.hour
    current_minute = now_utc.minute

    log.info(f"[Smart CRON Mail] Czas UTC: {current_hour:02d}:{current_minute:02d}")

    active_accounts = Account.query.filter_by(is_active=True).all()

    if not active_accounts:
        log.warning("[Smart CRON Mail] Brak aktywnych kont.")
        return jsonify({"status": "no_accounts"}), 200

    accounts_to_mail = []

    for account in active_accounts:
        settings = AccountScheduleSettings.get_for_account(account.id)

        if not settings.is_mail_enabled:
            log.info(f"[Smart CRON Mail] Pomijam {account.name} - wysylka wylaczona")
            continue

        if current_hour == settings.mail_send_hour:
            accounts_to_mail.append(account)
            log.info(f"[Smart CRON Mail] Konto {account.name} - zaplanowana wysylka o {settings.mail_send_hour:02d}:{settings.mail_send_minute:02d} UTC")
        else:
            log.debug(f"[Smart CRON Mail] Pomijam {account.name} - zaplanowane: {settings.mail_send_hour:02d} UTC, teraz: {current_hour:02d} UTC")

    if not accounts_to_mail:
        log.info(f"[Smart CRON Mail] Brak kont do wysylki o godzinie {current_hour:02d} UTC")
        return jsonify({
            "status": "no_mail_needed",
            "current_hour_utc": current_hour
        }), 200

    log.info(f"[Smart CRON Mail] Kolejkuje wysylke dla {len(accounts_to_mail)} kont...")

    tasks_queued = 0
    for account in accounts_to_mail:
        if enqueue_mail_task(account.id):
            tasks_queued += 1

    log.info(f"[Smart CRON Mail] Zakolejkowano {tasks_queued} zadan")
    return jsonify({
        "status": "accepted",
        "tasks_queued": tasks_queued,
        "current_hour_utc": current_hour,
        "accounts": [{"id": acc.id, "name": acc.name} for acc in accounts_to_mail]
    }), 202


@sync_bp.route('/test/mail-debug/<int:account_id>')
def test_mail_debug(account_id):
    """
    ENDPOINT DIAGNOSTYCZNY - DRY RUN wysylki powiadomien.
    Symuluje dokladnie to samo co scheduler, ale NIE WYSYLA emaili.

    Parametry query:
    - simulate_break=true/false : Test z/bez break (domyslnie false)
    - send_real_emails=false    : Faktyczna wysylka (domyslnie false - DRY RUN)

    Przyklady:
    /test/mail-debug/1?simulate_break=false  # Aquatest bez break
    /test/mail-debug/2?simulate_break=true   # Pozytron z break
    """
    # Sprawdz autoryzacje (tylko zalogowani admini)
    if not session.get('logged_in'):
        return jsonify({"error": "Unauthorized - login required"}), 401

    # Parametry
    simulate_break = request.args.get('simulate_break', 'false').lower() == 'true'
    send_real_emails = request.args.get('send_real_emails', 'false').lower() == 'true'

    # Uruchom diagnostyke przez serwis
    result = diagnostic_service.run_mail_diagnostic(
        account_id=account_id,
        simulate_break=simulate_break,
        send_real_emails=send_real_emails
    )

    if not result.get('success', True):
        error = result.get('error', 'Unknown error')
        return jsonify({"error": error}), 400 if 'not found' not in error.lower() else 404

    return jsonify(result), 200


@sync_bp.route('/sync_status')
def sync_status():
    """
    Panel monitorowania synchronizacji z filtrowaniem, paginacja i dashboard metrics.
    """
    try:
        account_id = session.get('current_account_id')
        if not account_id:
            flash("Wybierz profil.", "warning")
            return redirect(url_for('auth.select_account'))

        # Mapowanie typow sync na polskie nazwy
        SYNC_TYPE_DISPLAY = {
            'new': 'Nowe faktury',
            'update': 'Aktualizacja aktywnych',
            'full': 'Pelna synchronizacja'
        }

        # Strefa czasowa Warsaw
        warsaw_tz = ZoneInfo('Europe/Warsaw')

        # === FILTROWANIE PO DACIE ===
        preset = request.args.get('preset')
        date_from_str = request.args.get('date_from')
        date_to_str = request.args.get('date_to')

        date_from = None
        date_to = None

        if preset == 'today':
            date_from = date.today()
            date_to = date.today()
        elif preset == '7days':
            date_from = date.today() - timedelta(days=7)
            date_to = date.today()
        elif preset == '30days':
            date_from = date.today() - timedelta(days=30)
            date_to = date.today()
        else:
            if date_from_str:
                try:
                    date_from = datetime.strptime(date_from_str, '%Y-%m-%d').date()
                except ValueError:
                    pass
            if date_to_str:
                try:
                    date_to = datetime.strptime(date_to_str, '%Y-%m-%d').date()
                except ValueError:
                    pass

        # === BUDOWANIE QUERY ===
        query = SyncStatus.query.filter_by(account_id=account_id)

        if date_from:
            query = query.filter(SyncStatus.timestamp >= datetime.combine(date_from, dt_time.min))
        if date_to:
            query = query.filter(SyncStatus.timestamp <= datetime.combine(date_to, dt_time.max))

        query = query.order_by(SyncStatus.timestamp.desc())

        # === PAGINACJA ===
        page = request.args.get('page', 1, type=int)
        per_page = 20
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        statuses = pagination.items

        # === KONWERSJA UTC -> WARSAW ===
        for status in statuses:
            utc_time = status.timestamp.replace(tzinfo=dt_timezone.utc)
            status.local_timestamp = utc_time.astimezone(warsaw_tz)

        return render_template(
            'sync_status.html',
            statuses=statuses,
            pagination=pagination,
            SYNC_TYPE_DISPLAY=SYNC_TYPE_DISPLAY,
            date_from=date_from,
            date_to=date_to
        )

    except Exception as e:
        log.error(f"Blad ladowania statusu synchronizacji: {e}", exc_info=True)
        flash("Blad ladowania historii synchronizacji.", "danger")
        return render_template(
            'sync_status.html',
            statuses=[],
            pagination=None,
            SYNC_TYPE_DISPLAY={},
            date_from=None,
            date_to=None
        )
