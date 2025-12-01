"""
Serwis powiadomien.
Logika wysylki manualnych powiadomien, sprawdzanie duplikatow, logowanie.
"""
import logging
from datetime import datetime

from ..extensions import db
from ..models import Case, Invoice, NotificationLog, Account
from ..utils import map_stage, stage_to_number
from .send_email import send_email_for_account
from .mail_utils import generate_email

log = logging.getLogger(__name__)


def check_notification_already_sent(account_id, invoice_number, stage):
    """
    Sprawdza czy powiadomienie dla danego etapu zostalo juz wyslane.

    Args:
        account_id: ID konta
        invoice_number: Numer faktury
        stage: Nazwa etapu (pelna)

    Returns:
        NotificationLog lub None: Istniejacy log lub None
    """
    return NotificationLog.query.filter_by(
        invoice_number=invoice_number,
        stage=stage,
        account_id=account_id
    ).first()


def create_notification_log(account_id, invoice, stage, mode, subject, body, email_to):
    """
    Tworzy i zapisuje wpis logu powiadomienia.

    Args:
        account_id: ID konta
        invoice: Obiekt Invoice
        stage: Nazwa etapu
        mode: Tryb wysylki ("Automatyczne", "Manualne", "System")
        subject: Temat emaila
        body: Tresc emaila
        email_to: Adres(y) email

    Returns:
        NotificationLog: Utworzony wpis logu
    """
    log_entry = NotificationLog(
        account_id=account_id,
        client_id=invoice.client_id,
        invoice_number=invoice.invoice_number,
        email_to=email_to,
        subject=subject,
        body=body,
        stage=stage,
        mode=mode,
        sent_at=datetime.utcnow()
    )
    db.session.add(log_entry)
    return log_entry


def send_manual_notification(account_id, case_number, stage):
    """
    Wysyla manualne powiadomienie dla sprawy.

    Args:
        account_id: ID konta
        case_number: Numer sprawy
        stage: Skrot etapu (np. "7dni", "14dni")

    Returns:
        dict: Wynik operacji z kluczami:
            - success: bool
            - message: str (komunikat flash)
            - message_type: str ("success", "warning", "danger", "info")
            - case_closed: bool (czy sprawa zostala zamknieta)
    """
    try:
        # Pobierz sprawe
        case_obj = Case.query.filter_by(
            case_number=case_number,
            account_id=account_id
        ).first()

        if not case_obj:
            return {
                'success': False,
                'message': "Sprawa nie znaleziona.",
                'message_type': 'danger',
                'case_closed': False
            }

        # Pobierz fakture
        inv = (
            Invoice.query.filter_by(case_id=case_obj.id).first()
            or Invoice.query.filter_by(invoice_number=case_number).first()
        )

        if not inv:
            return {
                'success': False,
                'message': "Faktura nie znaleziona.",
                'message_type': 'danger',
                'case_closed': False
            }

        # Walidacja emaila
        effective_email = inv.get_effective_email()
        if not effective_email or '@' not in effective_email:
            return {
                'success': False,
                'message': "Brak lub niepoprawny email klienta.",
                'message_type': 'danger',
                'case_closed': False
            }

        # Mapowanie etapu
        mapped = map_stage(stage)
        if not mapped:
            return {
                'success': False,
                'message': "Nieprawidlowy etap.",
                'message_type': 'danger',
                'case_closed': False
            }

        # Pobierz konto
        account = Account.query.get(account_id)
        if not account:
            return {
                'success': False,
                'message': "Blad: nie znaleziono konta.",
                'message_type': 'danger',
                'case_closed': False
            }

        # Generuj email
        subject, body_html = generate_email(mapped, inv, account)
        if not subject or not body_html:
            return {
                'success': False,
                'message': "Blad szablonu.",
                'message_type': 'danger',
                'case_closed': False
            }

        # Sprawdz duplikat
        existing_log = check_notification_already_sent(account_id, inv.invoice_number, mapped)
        if existing_log:
            return {
                'success': False,
                'message': f"Powiadomienie ({mapped}) juz wyslane {existing_log.sent_at.strftime('%Y-%m-%d %H:%M')}.",
                'message_type': 'warning',
                'case_closed': False
            }

        # Wyslij email(e)
        email_success = False
        email_errors = []
        emails = [email.strip() for email in effective_email.split(',') if email.strip()]

        for email in emails:
            try:
                if send_email_for_account(account, email, subject, body_html, html=True):
                    email_success = True
                else:
                    email_errors.append(f"Nieudana wysylka do {email}")
            except Exception as e:
                email_errors.append(f"{email}: {str(e)}")
                log.error(f"Error sending manual email to {email}: {e}", exc_info=True)

        if not email_success:
            error_msg = "; ".join(email_errors) if email_errors else "Nieznany blad."
            return {
                'success': False,
                'message': f"Blad wysylki: {error_msg}",
                'message_type': 'danger',
                'case_closed': False
            }

        # Aktualizuj fakture i utworz log
        inv.debt_status = mapped
        create_notification_log(
            account_id=account_id,
            invoice=inv,
            stage=mapped,
            mode="Manualne",
            subject=subject,
            body=body_html,
            email_to=effective_email
        )
        db.session.add(inv)
        db.session.commit()

        # Zamknij sprawe po etapie 5
        case_closed = False
        if stage_to_number(mapped) >= 5 and case_obj.status == 'active':
            case_obj.status = "closed_nieoplacone"
            db.session.add(case_obj)
            db.session.commit()
            case_closed = True

        message = "Powiadomienie wyslane."
        if case_closed:
            message = "Powiadomienie wyslane. Sprawa zamknieta (nieoplacona) po wyslaniu etapu 5."

        return {
            'success': True,
            'message': message,
            'message_type': 'success' if not case_closed else 'info',
            'case_closed': case_closed
        }

    except Exception as e:
        log.error(f"Error in send_manual_notification for {case_number}: {e}", exc_info=True)
        db.session.rollback()
        return {
            'success': False,
            'message': f"Nieoczekiwany blad wysylki: {str(e)}",
            'message_type': 'danger',
            'case_closed': False
        }
