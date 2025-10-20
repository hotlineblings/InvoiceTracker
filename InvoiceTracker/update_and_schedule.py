# update_and_schedule.py

import sys
from datetime import datetime, timedelta, date
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

from .src.api.api_client import InFaktAPIClient
from .models import db, NotificationLog, Invoice, Case, NotificationSettings, Account
from .send_email import send_email_for_account
from .mail_templates import MAIL_TEMPLATES
from .update_db import sync_new_invoices, update_existing_cases

load_dotenv()

def run_daily_notifications():
    """
    MULTI-TENANCY: Najpierw aktualizujemy dane faktur z API dla każdego aktywnego konta,
    a następnie dla każdej aktywnej sprawy (Case) wysyłamy powiadomienia,
    jeśli dzisiejsza data równa się (payment_due_date + offset) dla danego etapu.
    """
    # MULTI-TENANCY: Pobierz wszystkie aktywne konta
    active_accounts = Account.query.filter_by(is_active=True).all()

    if not active_accounts:
        print("[update_and_schedule] Brak aktywnych kont do przetworzenia.")
        return

    print(f"[update_and_schedule] Znaleziono {len(active_accounts)} aktywnych kont.")

    today = date.today()

    # Iteruj po każdym koncie
    for account in active_accounts:
        print(f"[update_and_schedule] === Przetwarzanie konta: {account.name} (ID: {account.id}) ===")

        try:
            # MULTI-TENANCY: Synchronizacja dla tego konta
            print(f"[update_and_schedule] Uruchamiam synchronizację dla konta {account.name}...")
            sync_new_invoices(account.id, start_offset=0, limit=100)
            update_existing_cases(account.id, start_offset=0, limit=100)
        except Exception as e:
            print(f"[update_and_schedule] Błąd aktualizacji bazy dla konta {account.name}: {e}")
            continue

        # MULTI-TENANCY: Pobierz faktury tylko dla tego konta
        active_invoices = (Invoice.query.join(Case, Invoice.case_id == Case.id)
                                        .filter(Case.status == "active")
                                        .filter(Case.account_id == account.id)
                                        .all())

        # Get notification settings for this account
        notification_settings = NotificationSettings.get_all_settings(account.id)

        if not notification_settings:
            print(f"[update_and_schedule] Brak ustawień powiadomień dla konta {account.name}. Pomijam.")
            continue

        notifications_sent = 0

        for invoice in active_invoices:
            if not invoice.payment_due_date:
                continue

            # FILTR: Pomijaj opłacone faktury
            if invoice.left_to_pay == 0 or invoice.status == 'paid':
                continue

            # MULTI-TENANCY: Filter logs by account_id
            logs = NotificationLog.query.filter_by(
                invoice_number=invoice.invoice_number,
                client_id=invoice.client_id,
                account_id=account.id
            ).all()
            sent_stages = [int(log.stage) for log in logs if log.stage.isdigit()]
            next_stage = 1 if not sent_stages else max(sent_stages) + 1
            if next_stage > 5:
                continue

            stage_mapping = {
                1: ("Przypomnienie o zbliżającym się terminie płatności", "stage_1"),
                2: ("Powiadomienie o upływie terminu płatności", "stage_2"),
                3: ("Wezwanie do zapłaty", "stage_3"),
                4: ("Powiadomienie o zamiarze skierowania sprawy do windykatora zewnętrznego i publikacji na giełdzie wierzytelności", "stage_4"),
                5: ("Przekazanie sprawy do windykatora zewnętrznego", "stage_5"),
            }
            stage_text, template_key = stage_mapping.get(next_stage, (None, None))
            if stage_text is None:
                continue

            offset_value = notification_settings.get(stage_text)
            if offset_value is None:
                continue

            scheduled_date = invoice.payment_due_date + timedelta(days=offset_value)
            if scheduled_date == today:
                template = MAIL_TEMPLATES.get(template_key)
                if not template:
                    continue

                subject = template["subject"].format(case_number=invoice.invoice_number)

                # Get the offset value for stage 4 from notification settings
                stage_4_offset = notification_settings.get("Powiadomienie o zamiarze skierowania sprawy do windykatora zewnętrznego i publikacji na giełdzie wierzytelności", 21)
                stage_4_date = (invoice.payment_due_date + timedelta(days=stage_4_offset)).strftime('%Y-%m-%d')

                body_html = template["body_html"].format(
                    company_name=invoice.client_company_name,
                    due_date=invoice.payment_due_date.strftime('%Y-%m-%d'),
                    case_number=invoice.invoice_number,
                    street_address=invoice.client_address,
                    postal_code="",
                    city="",
                    nip=invoice.client_nip,
                    debt_amount="%.2f" % (invoice.gross_price / 100 if invoice.gross_price else 0),
                    stage_4_date=stage_4_date
                )
                recipient = invoice.client_email
                if recipient and recipient != "N/A":
                    # POPRAWIONE: Używamy send_email_for_account z dedykowanym SMTP
                    send_email_for_account(account, recipient, subject, body_html, html=True)
                    # MULTI-TENANCY: Add account_id to notification log
                    log = NotificationLog(
                        account_id=account.id,
                        client_id=invoice.client_id,
                        invoice_number=invoice.invoice_number,
                        email_to=recipient,
                        subject=subject,
                        body=body_html,
                        stage=stage_text,  # POPRAWIONE: Używamy pełnego tekstu zamiast liczby
                        mode="automatyczny",
                        scheduled_date=datetime.combine(scheduled_date, datetime.min.time())
                    )
                    db.session.add(log)
                    db.session.commit()
                    notifications_sent += 1
                    print(f"[update_and_schedule] Automatyczne powiadomienie etapu {next_stage}/5 wysłane dla faktury {invoice.invoice_number}")
                else:
                    print(f"[update_and_schedule] Brak prawidłowego adresu email dla faktury {invoice.invoice_number}")

        # Summary per account
        print(f"[update_and_schedule] Konto '{account.name}': Wysłano {notifications_sent} powiadomień")

    # Final summary after all accounts
    print("[update_and_schedule] Zakończono automatyczną wysyłkę powiadomień dla wszystkich kont.")

def start_daily_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(run_daily_notifications, 'cron', hour=12, minute=0)
    scheduler.start()
    print("Scheduler powiadomień automatycznych uruchomiony. Sprawdzanie następuje codziennie o 12:00.")
    try:
        while True:
            pass
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        print("Scheduler został zatrzymany.")

if __name__ == "__main__":
    start_daily_scheduler()