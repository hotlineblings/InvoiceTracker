"""
Blueprint ustawień.
Panel ustawień profilu, aktualizacja emaili.
"""
import logging
from flask import Blueprint, render_template, redirect, url_for, request, flash, session, jsonify

from ..extensions import db
from ..models import Account, Invoice, Case, NotificationSettings, AccountScheduleSettings
from ..constants import CANONICAL_NOTIFICATION_STAGES
from ..forms import SettingsForm, EmailUpdateForm

log = logging.getLogger(__name__)

settings_bp = Blueprint('settings', __name__)


@settings_bp.route('/settings', methods=['GET', 'POST'])
def settings_view():
    """
    Zunifikowany panel ustawień łączący:
    - Ustawienia API (InFakt API Key)
    - Ustawienia wysyłki powiadomień (offsets dla 5 etapów)
    - Ustawienia synchronizacji
    - Dane firmowe (do szablonów maili)
    - Opcje dodatkowe (auto-close)

    Czas wyświetlany w Europe/Warsaw, przechowywany w UTC.

    Uwaga: Formularz używa hybrydowego podejścia - WTForms dla walidacji CSRF
    i standardowych pól, request.form dla dynamicznych stage offsets.
    """
    form = SettingsForm()

    try:
        account_id = session.get('current_account_id')
        if not account_id:
            flash("Wybierz profil.", "warning")
            return redirect(url_for('auth.select_account'))

        account = Account.query.get(account_id)
        if not account:
            flash("Nie znaleziono konta.", "danger")
            return redirect(url_for('auth.select_account'))

        # SELF-HEALING: Normalizacja automatycznie usuwa stare wpisy i dodaje brakujące
        notification_settings = NotificationSettings.normalize_for_account(account_id)

        # Załaduj AccountScheduleSettings (harmonogramy)
        schedule_settings = AccountScheduleSettings.get_for_account(account_id)

        if form.validate_on_submit():
            try:
                # === SEKCJA 1: API Key ===
                api_key = request.form.get('infakt_api_key', '').strip()
                if api_key:
                    account.infakt_api_key = api_key

                # === SEKCJA 2: Wysyłka powiadomień ===
                mail_send_hour_utc = int(request.form.get('mail_send_hour', 7))
                mail_send_minute_utc = int(request.form.get('mail_send_minute', 0))
                schedule_settings.mail_send_hour = mail_send_hour_utc
                schedule_settings.mail_send_minute = mail_send_minute_utc
                schedule_settings.is_mail_enabled = request.form.get('is_mail_enabled') == 'on'

                # Offsets dla 5 etapów powiadomień
                new_notification_settings = {}
                for stage_name, current_offset in notification_settings.items():
                    try:
                        offset_value = int(request.form.get(stage_name, current_offset))
                        new_notification_settings[stage_name] = offset_value
                    except (ValueError, TypeError):
                        flash(f"Nieprawidłowa wartość dla {stage_name}.", "warning")
                        new_notification_settings[stage_name] = current_offset

                if new_notification_settings:
                    NotificationSettings.update_settings(account_id, new_notification_settings)

                # === SEKCJA 3: Synchronizacja ===
                sync_hour_utc = int(request.form.get('sync_hour', 9))
                sync_minute_utc = int(request.form.get('sync_minute', 0))
                schedule_settings.sync_hour = sync_hour_utc
                schedule_settings.sync_minute = sync_minute_utc
                schedule_settings.is_sync_enabled = request.form.get('is_sync_enabled') == 'on'
                schedule_settings.invoice_fetch_days_before = int(request.form.get('invoice_fetch_days_before', 1))

                # === SEKCJA 4: Dane firmowe ===
                account.company_full_name = request.form.get('company_full_name', '').strip()
                account.company_phone = request.form.get('company_phone', '').strip()
                account.company_email_contact = request.form.get('company_email_contact', '').strip()
                account.company_bank_account = request.form.get('company_bank_account', '').strip()

                # === SEKCJA 5: Opcje dodatkowe ===
                schedule_settings.auto_close_after_stage5 = request.form.get('auto_close_after_stage5') == 'on'
                schedule_settings.timezone = 'Europe/Warsaw'

                # Walidacja
                is_valid, errors = schedule_settings.validate()
                if not is_valid:
                    for error in errors:
                        flash(error, "danger")
                    return render_template('settings.html',
                                         form=form,
                                         account=account,
                                         notification_settings=notification_settings,
                                         schedule_settings=schedule_settings,
                                         CANONICAL_STAGES=CANONICAL_NOTIFICATION_STAGES)

                # Zapis do bazy
                db.session.add(account)
                db.session.add(schedule_settings)
                db.session.commit()

                flash("Wszystkie ustawienia zostały pomyślnie zapisane.", "success")
                log.info(f"[settings] Zaktualizowano ustawienia dla konta {account.name} (ID: {account_id})")

                return redirect(url_for('settings.settings_view'))

            except ValueError as e:
                flash(f"Błąd walidacji danych: {e}", "danger")
                db.session.rollback()
            except Exception as e:
                flash(f"Błąd zapisu ustawień: {e}", "danger")
                log.error(f"[settings] Błąd zapisu dla konta {account_id}: {e}", exc_info=True)
                db.session.rollback()

        # GET - renderuj formularz
        return render_template('settings.html',
                             form=form,
                             account=account,
                             notification_settings=notification_settings,
                             schedule_settings=schedule_settings,
                             CANONICAL_STAGES=CANONICAL_NOTIFICATION_STAGES)

    except Exception as e:
        log.error(f"[settings] Błąd ogólny: {e}", exc_info=True)
        flash("Wystąpił błąd podczas ładowania ustawień.", "danger")
        return redirect(url_for('cases.active_cases'))


@settings_bp.route('/update_email/<int:invoice_id>', methods=['POST'])
def update_email(invoice_id):
    """
    Endpoint do aktualizacji override_email dla faktury (AJAX).
    Umożliwia administratorowi ręczne nadpisanie emaila klienta z API.

    CSRF token jest walidowany automatycznie przez Flask-WTF.
    Token musi być przekazany w FormData jako 'csrf_token'.
    """
    form = EmailUpdateForm()

    try:
        account_id = session.get('current_account_id')
        if not account_id:
            return jsonify({"success": False, "message": "Wybierz profil."}), 403

        # Walidacja CSRF przez WTForms (form.validate() sprawdza CSRF)
        if not form.validate():
            errors = [str(e) for field_errors in form.errors.values() for e in field_errors]
            return jsonify({"success": False, "message": f"Błąd walidacji: {', '.join(errors)}"}), 400

        new_email = form.new_email.data.strip() if form.new_email.data else ''

        invoice = (
            Invoice.query
            .join(Case, Invoice.case_id == Case.id)
            .filter(Invoice.id == invoice_id)
            .filter(Case.account_id == account_id)
            .first()
        )

        if not invoice:
            return jsonify({"success": False, "message": "Nie znaleziono faktury lub brak dostępu."}), 404

        if new_email and '@' not in new_email:
            return jsonify({"success": False, "message": "Nieprawidłowy format emaila."}), 400

        if new_email:
            invoice.override_email = new_email
            log.info(f"[update_email] Ustawiono override_email={new_email} dla faktury {invoice.invoice_number}")
        else:
            invoice.override_email = None
            log.info(f"[update_email] Usunięto override_email dla faktury {invoice.invoice_number}")

        db.session.add(invoice)
        db.session.commit()

        effective_email = invoice.get_effective_email()

        return jsonify({
            "success": True,
            "message": "Email zaktualizowany pomyślnie.",
            "effective_email": effective_email,
            "override_email": invoice.override_email,
            "client_email": invoice.client_email
        }), 200

    except Exception as e:
        log.error(f"[update_email] Błąd aktualizacji emaila dla invoice_id={invoice_id}: {e}", exc_info=True)
        db.session.rollback()
        return jsonify({"success": False, "message": f"Błąd serwera: {str(e)}"}), 500


@settings_bp.route('/shipping_settings', methods=['GET', 'POST'])
def shipping_settings_view():
    """Stary endpoint - przekierowanie do nowego zunifikowanego panelu ustawień."""
    flash("Panel ustawień został przeniesiony do nowej lokalizacji.", "info")
    return redirect(url_for('settings.settings_view'))


@settings_bp.route('/advanced_settings', methods=['GET', 'POST'])
def advanced_settings_view():
    """Stary endpoint - przekierowanie do nowego zunifikowanego panelu ustawień."""
    flash("Panel ustawień został przeniesiony do nowej lokalizacji.", "info")
    return redirect(url_for('settings.settings_view'))
