# scheduler.py - APScheduler service
from datetime import datetime, timedelta, date
import time
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.events import EVENT_SCHEDULER_SHUTDOWN
from dotenv import load_dotenv

from ..extensions import db
from ..models import Invoice, NotificationLog, Case, NotificationSettings, Account, AccountScheduleSettings
from ..tenant_context import tenant_context, sudo
from .send_email import send_email_for_account, close_smtp_connection
from .mail_utils import generate_email

load_dotenv()


def stage_to_number(text):
    mapping = {
        "Przypomnienie o zblizajacym sie terminie platnosci": 1,
        "Powiadomienie o uplywie terminu platnosci": 2,
        "Wezwanie do zaplaty": 3,
        "Powiadomienie o zamiarze skierowania sprawy do windykatora zewnetrznego i publikacji na gieldzie wierzytelnosci": 4,
        "Przekazanie sprawy do windykatora zewnetrznego": 5
    }
    return mapping.get(text, 0)


def run_sync_with_context(app):
    """
    Usuwamy stara funkcje update_database, wiec nic tu nie robimy,
    albo usuwamy te funkcje calkowicie z harmonogramu.
    """
    with app.app_context():
        print("[scheduler] run_sync_with_context() - brak starej logiki")


def run_mail_for_single_account(app, account_id):
    """
    Wysylka powiadomien dla pojedynczego konta.
    Wywolane przez scheduler per-profil.

    Args:
        app: Flask application context
        account_id (int): ID konta dla ktorego wyslac maile
    """
    with app.app_context(), tenant_context(account_id):
        # Używamy sudo() dla zapytania o Account (nie ma account_id)
        with sudo():
            account = Account.query.get(account_id)
        if not account or not account.is_active:
            print(f"[scheduler] Konto ID:{account_id} nie istnieje lub nieaktywne.")
            return

        # Pobierz ustawienia harmonogramu
        settings = AccountScheduleSettings.get_for_account(account_id)
        if not settings.is_mail_enabled:
            print(f"[scheduler] Wysylka wylaczona dla konta '{account.name}'.")
            return

        print(f"[scheduler] START wysylki dla konta: {account.name} (ID: {account_id})")
        today = date.today()

        # Pobierz ustawienia powiadomien dla tego konta
        notification_settings = NotificationSettings.get_all_settings(account.id)

        if not notification_settings:
            print(f"[scheduler] Brak ustawien powiadomien dla konta {account.name}. Pomijam.")
            return

        processed_count = 0
        error_count = 0
        batch_size = 100
        offset = 0

        # Uzyj auto_close_after_stage5 z ustawien zaawansowanych
        auto_close_enabled = settings.auto_close_after_stage5

        while True:
            # Pobierz faktury tylko dla tego konta
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

                # FILTR: Pomijaj oplacone faktury
                if inv.left_to_pay == 0 or inv.status == 'paid':
                    continue

                days_diff = (today - inv.payment_due_date).days

                # Skip if no email is available (uzywamy effective email)
                effective_email = inv.get_effective_email()
                if not effective_email or effective_email == "N/A":
                    continue

                notification_sent = False
                for stage_name, offset_value in notification_settings.items():
                    if days_diff == offset_value:
                        # Check if this notification was already sent
                        existing_log = NotificationLog.query.filter_by(
                            invoice_number=inv.invoice_number,
                            stage=stage_name,
                            account_id=account.id
                        ).first()

                        if existing_log:
                            continue

                        # Generuj i wyslij email
                        subject, body_html = generate_email(stage_name, inv, account)
                        if not subject or not body_html:
                            print(f"[scheduler] Brak szablonu dla {stage_name}, pomijam fakture {inv.invoice_number}.")
                            continue

                        # Split multiple emails and send to each (uzywamy effective email)
                        emails = [email.strip() for email in effective_email.split(',') if email.strip()]
                        email_sent_success = False

                        for email in emails:
                            retries = 3
                            for attempt in range(retries):
                                try:
                                    send_email_for_account(account, email, subject, body_html, html=True)
                                    email_sent_success = True
                                    break
                                except Exception as e:
                                    print(f"[scheduler] Blad wysylki maila do {email} dla faktury {inv.invoice_number} (proba {attempt+1}): {e}")
                                    if attempt == retries - 1:
                                        error_count += 1
                                    time.sleep(5)

                        if email_sent_success:
                            # Log the notification (uzywamy effective email)
                            new_log = NotificationLog(
                                account_id=account.id,
                                client_id=inv.client_id,
                                invoice_number=inv.invoice_number,
                                email_to=effective_email,
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
                            print(f"[scheduler] Wyslano mail dla {inv.invoice_number}, etap={stage_name}")

                # Auto-zamykanie sprawy TYLKO PO WYSLANIU STAGE 5 (jesli wlaczone)
                if notification_sent and auto_close_enabled:
                    # Sprawdz czy wlasnie wyslano stage 5 dla tej faktury
                    stage5_log = NotificationLog.query.filter_by(
                        invoice_number=inv.invoice_number,
                        account_id=account.id,
                        stage="Przekazanie sprawy do windykatora zewnetrznego"
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
                            print(f"[scheduler] Zamknieto sprawe {inv.invoice_number} (wyslano etap 5)")

            offset += batch_size

        # Summary
        print(f"[scheduler] KONIEC dla konta '{account.name}': Wyslano {processed_count} powiadomien, bledow: {error_count}")


def start_scheduler(app):
    """
    Inicjuje scheduler z dynamicznymi jobami per-profil.
    Dla kazdego aktywnego konta tworzy osobny job o czasie okreslonym w AccountScheduleSettings.
    """
    scheduler = BackgroundScheduler()

    with app.app_context():
        # Pobierz wszystkie aktywne konta (sudo - Account nie ma account_id)
        with sudo():
            active_accounts = Account.query.filter_by(is_active=True).all()

        print(f"[scheduler] Inicjalizacja schedulera dla {len(active_accounts)} aktywnych kont...")

        for account in active_accounts:
            # Użyj tenant_context dla pobierania ustawień
            with tenant_context(account.id):
                settings = AccountScheduleSettings.get_for_account(account.id)

            if not settings.is_mail_enabled:
                print(f"[scheduler] Pomijam konto '{account.name}' - wysylka wylaczona")
                continue

            # Dodaj job dla tego konta
            scheduler.add_job(
                func=lambda acc_id=account.id: run_mail_for_single_account(app, acc_id),
                trigger='cron',
                hour=settings.mail_send_hour,
                minute=settings.mail_send_minute,
                id=f'mail_account_{account.id}',
                name=f'Mail: {account.name}',
                replace_existing=True,
                misfire_grace_time=300  # 5 minut tolerancji
            )

            print(f"[scheduler] Job dodany: '{account.name}' -> {settings.mail_send_hour:02d}:{settings.mail_send_minute:02d} UTC")

    # Handler zamykajacy SMTP przy wylaczeniu schedulera
    def shutdown_handler(event):
        close_smtp_connection()

    scheduler.add_listener(shutdown_handler, EVENT_SCHEDULER_SHUTDOWN)
    scheduler.start()

    print("[scheduler] Scheduler uruchomiony z dynamicznymi jobami per-profil")
