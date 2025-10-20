# scheduler.py
from datetime import datetime, timedelta, date
import time
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.events import EVENT_SCHEDULER_SHUTDOWN
from dotenv import load_dotenv

# Usunięto import do update_database:
# from .update_db import update_database

from .models import db, Invoice, NotificationLog, Case, NotificationSettings, Account
from .send_email import send_email_for_account, close_smtp_connection
from .mail_utils import generate_email

load_dotenv()

def stage_to_number(text):
    mapping = {
        "Przypomnienie o zbliżającym się terminie płatności": 1,
        "Powiadomienie o upływie terminu płatności": 2,
        "Wezwanie do zapłaty": 3,
        "Powiadomienie o zamiarze skierowania sprawy do windykatora zewnętrznego i publikacji na giełdzie wierzytelności": 4,
        "Przekazanie sprawy do windykatora zewnętrznego": 5
    }
    return mapping.get(text, 0)

def run_sync_with_context(app):
    """
    Usuwamy starą funkcję update_database, więc nic tu nie robimy,
    albo usuwamy tę funkcję całkowicie z harmonogramu.
    """
    with app.app_context():
        print("[scheduler] run_sync_with_context() – brak starej logiki")

def run_mail_with_context(app):
    """
    Automatyczna wysyłka powiadomień e-mail w kontekście aplikacji.
    MULTI-TENANCY: Iteruje po wszystkich aktywnych kontach i wysyła powiadomienia
    niezależnie dla każdego profilu.
    """
    with app.app_context():
        print("[scheduler] Rozpoczynam automatyczną wysyłkę maili dla wszystkich aktywnych kont...")
        today = date.today()

        # MULTI-TENANCY: Pobierz wszystkie aktywne konta
        active_accounts = Account.query.filter_by(is_active=True).all()

        if not active_accounts:
            print("[scheduler] Brak aktywnych kont do przetworzenia.")
            return

        print(f"[scheduler] Znaleziono {len(active_accounts)} aktywnych kont.")

        # Iteruj po każdym koncie
        for account in active_accounts:
            print(f"[scheduler] === Przetwarzanie konta: {account.name} (ID: {account.id}) ===")

            # Pobierz ustawienia powiadomień dla tego konta
            notification_settings = NotificationSettings.get_all_settings(account.id)

            if not notification_settings:
                print(f"[scheduler] Brak ustawień powiadomień dla konta {account.name}. Pomijam.")
                continue

            # Track successfully processed invoices per account
            processed_count = 0
            error_count = 0
            batch_size = 100
            offset = 0

            while True:
                # MULTI-TENANCY: Pobierz faktury tylko dla tego konta
                active_invoices = (Invoice.query.join(Case, Invoice.case_id == Case.id)
                                   .filter(Case.status == "active")
                                   .filter(Case.account_id == account.id)
                                   .order_by(Invoice.invoice_date.desc())
                                   .offset(offset)
                                   .limit(batch_size)
                                   .all())
                if not active_invoices:
                    break

                for inv in active_invoices:
                    if not inv.payment_due_date:
                        continue

                    # FILTR: Pomijaj opłacone faktury
                    if inv.left_to_pay == 0 or inv.status == 'paid':
                        continue

                    days_diff = (today - inv.payment_due_date).days

                    # Skip if no email is available
                    if not inv.client_email or inv.client_email == "N/A":
                        continue

                    notification_sent = False
                    for stage_name, offset_value in notification_settings.items():
                        if days_diff == offset_value:
                            # MULTI-TENANCY: Check if this notification was already sent FOR THIS ACCOUNT
                            existing_log = NotificationLog.query.filter_by(
                                invoice_number=inv.invoice_number,
                                stage=stage_name,
                                account_id=account.id
                            ).first()

                            if existing_log:
                                continue

                            # POPRAWIONE WCIĘCIE: Wysyłanie TYLKO dla pasującego days_diff!
                            # MULTI-TENANCY: Przekaż account do generate_email
                            subject, body_html = generate_email(stage_name, inv, account)
                            if not subject or not body_html:
                                print(f"[scheduler] Brak szablonu dla {stage_name}, pomijam fakturę {inv.invoice_number}.")
                                continue

                            # Split multiple emails and send to each
                            emails = [email.strip() for email in inv.client_email.split(',') if email.strip()]
                            email_sent_success = False

                            for email in emails:
                                retries = 3
                                for attempt in range(retries):
                                    try:
                                        # POPRAWIONE: Używamy send_email_for_account z dedykowanym SMTP
                                        send_email_for_account(account, email, subject, body_html, html=True)
                                        email_sent_success = True
                                        break
                                    except Exception as e:
                                        print(f"[scheduler] Błąd wysyłki maila do {email} dla faktury {inv.invoice_number} (próba {attempt+1}): {e}")
                                        if attempt == retries - 1:  # Last attempt
                                            error_count += 1
                                        time.sleep(5)

                            if email_sent_success:
                                # Log the notification
                                new_log = NotificationLog(
                                    account_id=account.id,  # MULTI-TENANCY: Przypisz do konta
                                    client_id=inv.client_id,
                                    invoice_number=inv.invoice_number,
                                    email_to=inv.client_email,
                                    subject=subject,
                                    body=body_html,
                                    stage=stage_name,
                                    mode="Automatyczne",
                                    scheduled_date=datetime.now()
                                )
                                db.session.add(new_log)
                                db.session.commit()
                                processed_count += 1
                                notification_sent = True
                                print(f"[scheduler] Wysłano mail dla {inv.invoice_number}, etap={stage_name}")

                    # Auto-zamykanie sprawy TYLKO PO WYSŁANIU STAGE 5
                    # Działa poprawnie gdy wysyłany jest tylko jeden etap (po naprawie wcięcia)
                    if notification_sent:
                        # Sprawdź czy właśnie wysłano stage 5 dla tej faktury
                        stage5_log = NotificationLog.query.filter_by(
                            invoice_number=inv.invoice_number,
                            account_id=account.id,
                            stage="Przekazanie sprawy do windykatora zewnętrznego"
                        ).first()

                        if stage5_log:
                            case_obj = Case.query.filter_by(
                                case_number=inv.invoice_number,
                                account_id=account.id
                            ).first()
                            if case_obj and case_obj.status == "active":
                                case_obj.status = "closed_nieoplacone"
                                db.session.add(case_obj)
                                db.session.commit()
                                print(f"[scheduler] Zamknięto sprawę {inv.invoice_number} (wysłano etap 5)")

                offset += batch_size

            # Summary per account
            print(f"[scheduler] Konto '{account.name}': Wysłano {processed_count} powiadomień, błędów: {error_count}")

        # Final summary after all accounts
        print("[scheduler] Zakończono automatyczną wysyłkę maili dla wszystkich kont.")

def start_scheduler(app):
    """
    Inicjuje scheduler.
    - run_mail_with_context() wysyła powiadomienia codziennie o 17:00.
    """
    scheduler = BackgroundScheduler()
    # scheduler.add_job(lambda: run_sync_with_context(app), 'cron', hour=16, minute=55)musi być dwie godziny wstecz (jeśli wysyłka ma być o 11, ustawiamy 9:00)!
    scheduler.add_job(lambda: run_mail_with_context(app), 'cron', hour=9, minute=5)
    
    def shutdown_handler(event):
        close_smtp_connection()
    
    scheduler.add_listener(shutdown_handler, EVENT_SCHEDULER_SHUTDOWN)
    scheduler.start()
    print("[scheduler] Scheduler uruchomiony (z app context).")
