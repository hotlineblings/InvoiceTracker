"""
Serwis diagnostyczny.
Logika diagnostyki wysylki maili (DRY RUN), analiza konfiguracji.
"""
import logging
from collections import Counter
from datetime import date, datetime

from ..extensions import db
from ..models import Account, Invoice, Case, NotificationLog, NotificationSettings, AccountScheduleSettings
from .mail_utils import generate_email
from .send_email import send_email_for_account

log = logging.getLogger(__name__)


def _analyze_duplicate_offsets(notification_settings):
    """
    Analizuje ustawienia powiadomien pod katem zduplikowanych offset_days.

    Args:
        notification_settings: dict {stage_name: offset_days}

    Returns:
        tuple: (has_duplicates, duplicate_offset_values)
    """
    offset_values = list(notification_settings.values())
    has_duplicates = len(offset_values) != len(set(offset_values))

    duplicate_offsets = []
    if has_duplicates:
        counts = Counter(offset_values)
        duplicate_offsets = [val for val, count in counts.items() if count > 1]

    return has_duplicates, duplicate_offsets


def _process_invoice_for_diagnostic(invoice, account, notification_settings, today,
                                     simulate_break=False, send_real_emails=False):
    """
    Przetwarza pojedyncza fakture w trybie diagnostycznym.

    Args:
        invoice: Obiekt Invoice
        account: Obiekt Account
        notification_settings: dict {stage_name: offset_days}
        today: Dzisiejsza data
        simulate_break: Czy symulowac break po pierwszym stage
        send_real_emails: Czy faktycznie wysylac emaile

    Returns:
        dict lub None: Dane faktury lub None jesli pominieta
    """
    # Pomijaj faktury bez payment_due_date
    if not invoice.payment_due_date:
        return None

    # Pomijaj oplacone
    if invoice.left_to_pay == 0 or invoice.status == 'paid':
        return None

    # Oblicz days_diff
    days_diff = (today - invoice.payment_due_date).days

    # Sprawdz email
    effective_email = invoice.get_effective_email()
    if not effective_email or effective_email == "N/A":
        return None

    # Dane faktury
    invoice_data = {
        "invoice_number": invoice.invoice_number,
        "payment_due_date": str(invoice.payment_due_date),
        "days_diff": days_diff,
        "debt_amount_pln": round(invoice.left_to_pay / 100.0, 2),
        "effective_email": effective_email,
        "stages_matched": [],
        "total_emails_would_send": 0
    }

    # KLUCZOWA LOGIKA: Iteruj po stages
    stages_that_would_send = []
    first_stage_to_send = None

    for stage_name, offset_value in notification_settings.items():
        stage_short = stage_name[:40] + "..." if len(stage_name) > 40 else stage_name

        if days_diff == offset_value:
            # Sprawdz czy juz wyslano
            existing_log = NotificationLog.query.filter_by(
                invoice_number=invoice.invoice_number,
                stage=stage_name,
                account_id=account.id
            ).first()

            already_sent = existing_log is not None
            would_send = not already_sent
            stopped_by_break = False

            # Jesli symulujemy break
            if simulate_break and first_stage_to_send is None and would_send:
                first_stage_to_send = stage_name

            if simulate_break and first_stage_to_send and first_stage_to_send != stage_name and would_send:
                stopped_by_break = True
                would_send = False

            stage_info = {
                "stage": stage_short,
                "offset": offset_value,
                "already_sent": already_sent,
                "would_send": would_send,
                "stopped_by_break": stopped_by_break
            }

            if already_sent:
                stage_info["sent_at"] = existing_log.sent_at.strftime("%Y-%m-%d %H:%M")

            invoice_data["stages_matched"].append(stage_info)

            if would_send:
                stages_that_would_send.append(stage_name)
                invoice_data["total_emails_would_send"] += 1

    # Jesli faktyczna wysylka wlaczona (UWAGA: uzywaj ostroznie!)
    if send_real_emails and len(stages_that_would_send) > 0:
        for stage_name in stages_that_would_send:
            try:
                subject, body_html = generate_email(stage_name, invoice, account)
                if subject and body_html:
                    send_email_for_account(account, effective_email, subject, body_html, html=True)

                    # Loguj do NotificationLog
                    new_log = NotificationLog(
                        account_id=account.id,
                        client_id=invoice.client_id,
                        invoice_number=invoice.invoice_number,
                        email_to=effective_email,
                        subject=subject,
                        body=body_html,
                        stage=stage_name,
                        mode="Test (via /test/mail-debug)",
                        scheduled_date=datetime.now()
                    )
                    db.session.add(new_log)
                    db.session.commit()
            except Exception as e:
                log.error(f"Error sending test email: {e}")

    # Dodaj informacje o break
    if simulate_break and first_stage_to_send:
        invoice_data["break_would_stop_after"] = first_stage_to_send

    # Zwroc tylko jesli sa dopasowania
    if len(invoice_data["stages_matched"]) > 0:
        return invoice_data

    return None


def run_mail_diagnostic(account_id, simulate_break=False, send_real_emails=False):
    """
    Uruchamia diagnostyke wysylki maili (DRY RUN).
    Symuluje dokladnie to samo co scheduler, ale domyslnie NIE WYSYLA emaili.

    Args:
        account_id: ID konta
        simulate_break: Czy symulowac break po pierwszym stage
        send_real_emails: Czy faktycznie wysylac emaile (OSTROZNIE!)

    Returns:
        dict: Wyniki diagnostyki z kluczami:
            - success: bool
            - error: str (jesli blad)
            - test_mode: str
            - account: dict
            - schedule_settings: dict
            - notification_settings: dict
            - duplicates_detected: bool
            - duplicate_offset_values: list
            - invoices_processed: list
            - summary: dict
    """
    # Pobierz konto
    account = Account.query.get(account_id)
    if not account:
        return {
            'success': False,
            'error': f"Account ID {account_id} not found"
        }

    if not account.is_active:
        return {
            'success': False,
            'error': f"Account '{account.name}' is not active"
        }

    # Pobierz ustawienia
    settings = AccountScheduleSettings.get_for_account(account_id)
    notification_settings = NotificationSettings.get_all_settings(account.id)

    if not notification_settings:
        return {
            'success': False,
            'error': f"No notification settings found for account '{account.name}'",
            'account_id': account_id
        }

    # Analiza duplikatow offset_days
    has_duplicates, duplicate_offsets = _analyze_duplicate_offsets(notification_settings)

    # Przygotuj dane wyjsciowe
    result = {
        "success": True,
        "test_mode": "DRY RUN (no emails sent)" if not send_real_emails else "REAL EMAILS SENT",
        "simulate_break": simulate_break,
        "account": {
            "id": account.id,
            "name": account.name
        },
        "schedule_settings": {
            "is_mail_enabled": settings.is_mail_enabled,
            "mail_send_hour_utc": settings.mail_send_hour,
            "mail_send_minute_utc": settings.mail_send_minute
        },
        "notification_settings": {},
        "duplicates_detected": has_duplicates,
        "duplicate_offset_values": duplicate_offsets,
        "invoices_processed": [],
        "summary": {}
    }

    # Dodaj notification settings do wyniku
    for stage_name, offset_days in notification_settings.items():
        stage_short = stage_name[:50] + "..." if len(stage_name) > 50 else stage_name
        result["notification_settings"][stage_short] = offset_days

    # Jesli wysylka wylaczona, zwroc info
    if not settings.is_mail_enabled:
        result["warning"] = f"Mail sending is DISABLED for account '{account.name}'"
        result["summary"] = {
            "total_invoices": 0,
            "total_emails_would_send": 0,
            "problem_detected": "MAIL_DISABLED"
        }
        return result

    # Pobierz faktury (dokladnie tak samo jak scheduler)
    today = date.today()
    batch_size = 100
    offset = 0

    total_invoices = 0
    total_emails_would_send = 0
    invoices_with_multiple_stages = []

    while True:
        active_invoices = (
            Invoice.query.join(Case, Invoice.case_id == Case.id)
            .filter(Case.status == "active")
            .filter(Case.account_id == account.id)
            .order_by(Invoice.invoice_date.desc())
            .offset(offset)
            .limit(batch_size)
            .all()
        )

        if not active_invoices:
            break

        for inv in active_invoices:
            invoice_data = _process_invoice_for_diagnostic(
                invoice=inv,
                account=account,
                notification_settings=notification_settings,
                today=today,
                simulate_break=simulate_break,
                send_real_emails=send_real_emails
            )

            if invoice_data:
                total_invoices += 1
                total_emails_would_send += invoice_data["total_emails_would_send"]
                result["invoices_processed"].append(invoice_data)

                # Oznacz faktury z wieloma stages
                if invoice_data["total_emails_would_send"] > 1:
                    invoices_with_multiple_stages.append(inv.invoice_number)

        offset += batch_size

    # Podsumowanie
    problem_detected = "NO"
    recommendation = "Configuration looks correct. Only 1 email per invoice."

    if has_duplicates:
        problem_detected = "DUPLICATE_OFFSETS"
        recommendation = f"CRITICAL: Duplicate offset_days detected! Values: {duplicate_offsets}. This will cause multiple emails to be sent."

    if len(invoices_with_multiple_stages) > 0 and not simulate_break:
        problem_detected = "MULTIPLE_EMAILS_PER_INVOICE"
        recommendation = f"CRITICAL: {len(invoices_with_multiple_stages)} invoices would receive multiple stages. Add 'break' after email sending in scheduler.py!"

    if simulate_break and has_duplicates and len(invoices_with_multiple_stages) == 0:
        problem_detected = "FIXED_BY_BREAK"
        recommendation = "Adding 'break' would fix the duplicate offset_days problem. But you should also fix the database configuration."

    result["summary"] = {
        "total_invoices_processed": total_invoices,
        "total_invoices_with_matches": len(result["invoices_processed"]),
        "total_emails_would_send": total_emails_would_send,
        "invoices_with_multiple_stages": invoices_with_multiple_stages,
        "problem_detected": problem_detected,
        "recommendation": recommendation
    }

    return result
