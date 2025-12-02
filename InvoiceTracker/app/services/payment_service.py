"""
Serwis operacji platnosci.
Oznaczanie faktur jako oplacone, przywracanie spraw.
"""
import logging
from datetime import date, datetime

from ..extensions import db
from ..models import Case, Invoice, NotificationLog

log = logging.getLogger(__name__)


def mark_invoice_as_paid(account_id, invoice_id):
    """
    Oznacza fakture jako oplacona i zamyka sprawe.

    Args:
        account_id: ID konta
        invoice_id: ID faktury

    Returns:
        dict: Wynik operacji z kluczami:
            - success: bool
            - message: str (komunikat flash)
            - message_type: str ("success", "danger")
            - invoice_number: str lub None
    """
    try:
        # Pobierz fakture z walidacja konta (Invoice ma teraz bezpośredni account_id)
        invoice = Invoice.query.filter_by(id=invoice_id, account_id=account_id).first()

        if not invoice:
            return {
                'success': False,
                'message': "Nie znaleziono faktury lub brak dostepu.",
                'message_type': 'danger',
                'invoice_number': None
            }

        case = Case.query.get(invoice.case_id)

        # Aktualizuj fakture
        invoice.status = "paid"
        invoice.paid_price = invoice.gross_price
        invoice.left_to_pay = 0
        invoice.paid_date = date.today()
        db.session.add(invoice)

        # Zamknij sprawe
        case.status = "closed_oplacone"
        db.session.add(case)

        # Utworz log systemowy
        log_entry = NotificationLog(
            account_id=account_id,
            client_id=invoice.client_id,
            invoice_number=invoice.invoice_number,
            email_to=invoice.client_email if invoice.client_email else "N/A",
            subject="Faktura oznaczona jako oplacona",
            body=f"Faktura {invoice.invoice_number} oznaczona jako oplacona dnia {date.today().strftime('%Y-%m-%d')}.",
            stage="Zamkniecie sprawy",
            mode="System",
            sent_at=datetime.utcnow()
        )
        db.session.add(log_entry)
        db.session.commit()

        return {
            'success': True,
            'message': f"Faktura {invoice.invoice_number} oznaczona jako oplacona, sprawa zamknieta.",
            'message_type': 'success',
            'invoice_number': invoice.invoice_number
        }

    except Exception as e:
        log.error(f"Error marking invoice {invoice_id} as paid: {e}", exc_info=True)
        db.session.rollback()
        return {
            'success': False,
            'message': f"Blad oznaczania jako oplaconej: {str(e)}",
            'message_type': 'danger',
            'invoice_number': None
        }


def reopen_case(account_id, case_number):
    """
    Przywraca zamknieta sprawe do statusu aktywnego.

    Args:
        account_id: ID konta
        case_number: Numer sprawy

    Returns:
        dict: Wynik operacji z kluczami:
            - success: bool
            - message: str (komunikat flash)
            - message_type: str ("success", "warning", "danger")
            - old_status: str lub None
    """
    try:
        case = Case.query.filter_by(
            case_number=case_number,
            account_id=account_id
        ).first()

        if not case:
            return {
                'success': False,
                'message': "Sprawa nie znaleziona.",
                'message_type': 'danger',
                'old_status': None
            }

        if case.status == "active":
            return {
                'success': False,
                'message': f"Sprawa {case_number} jest juz aktywna.",
                'message_type': 'warning',
                'old_status': 'active'
            }

        old_status = case.status
        case.status = "active"
        db.session.add(case)
        db.session.commit()

        return {
            'success': True,
            'message': f"Sprawa {case_number} przywrocona (byla: {old_status}).",
            'message_type': 'success',
            'old_status': old_status
        }

    except Exception as e:
        log.error(f"Blad przywracania sprawy {case_number}: {e}", exc_info=True)
        db.session.rollback()
        return {
            'success': False,
            'message': "Blad przywracania sprawy.",
            'message_type': 'danger',
            'old_status': None
        }
