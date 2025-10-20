# --- POCZĄTEK PLIKU: InvoiceTracker/app.py (Zaktualizowana wersja) ---
import os
import threading
from datetime import date, datetime, timedelta
from flask import Flask, render_template, redirect, url_for, request, flash, session, jsonify  # Dodano jsonify
from dotenv import load_dotenv
import logging
import urllib.parse

try:
    from .models import db, Invoice, NotificationLog, Case, SyncStatus, NotificationSettings, Account
    from .send_email import send_email_for_account
    from .mail_templates import MAIL_TEMPLATES
    from .scheduler import start_scheduler
    from .mail_utils import generate_email
    from .update_db import run_full_sync
except ImportError as e_imp1:
    try:
        from models import db, Invoice, NotificationLog, Case, SyncStatus, NotificationSettings
        from send_email import send_email_for_account
        from mail_templates import MAIL_TEMPLATES
        from scheduler import start_scheduler
        from mail_utils import generate_email
        from update_db import run_full_sync
    except ImportError as e_imp2:
        print(f"Krytyczny błąd importu: {e_imp1} / {e_imp2}. Sprawdź strukturę i PYTHONPATH.")
        raise SystemExit(f"Błąd importu: {e_imp2}")

from flask_migrate import Migrate

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
log = logging.getLogger(__name__)

def map_stage(stage):
    """Mapuje skróty etapów na pełne nazwy."""
    mapping = {
        "przeds": "Przypomnienie o zbliżającym się terminie płatności",
        "7dni": "Powiadomienie o upływie terminu płatności",
        "14dni": "Wezwanie do zapłaty",
        "21dni": "Powiadomienie o zamiarze skierowania sprawy do windykatora zewnętrznego i publikacji na giełdzie wierzytelności",
        "30dni": "Przekazanie sprawy do windykatora zewnętrznego"
    }
    return mapping.get(stage, stage)

STAGE_LABELS = {
    "Przypomnienie o zbliżającym się terminie płatności": "Przypomnienie o zbliżającym się terminie płatności",
    "Powiadomienie o upływie terminu płatności": "Powiadomienie o upływie terminu płatności",
    "Wezwanie do zapłaty": "Wezwanie do zapłaty",
    "Powiadomienie o zamiarze skierowania sprawy do windykatora zewnętrznego i publikacji na giełdzie wierzytelności":
        "Powiadomienie o zamiarze skierowania sprawy do windykatora zewnętrznego i publikacji na giełdzie wierzytelności",
    "Przekazanie sprawy do windykatora zewnętrznego": "Przekazanie sprawy do windykatora zewnętrznego"
}

def create_app():
    app = Flask(__name__, template_folder='templates', static_folder='static')
    app.secret_key = os.environ.get('SECRET_KEY')
    if not app.secret_key:
        log.critical("KRYTYCZNY BŁĄD: Brak SECRET_KEY w app.yaml!")
        raise ValueError("Brak SECRET_KEY!")

    # Wykryj środowisko: App Engine (unix socket) vs lokalne (Cloud SQL Proxy)
    is_app_engine = os.path.exists('/cloudsql')

    if is_app_engine:
        # App Engine - połączenie przez unix socket
        db_user = os.environ.get('DB_USER')
        db_password = os.environ.get('DB_PASSWORD')
        db_name = os.environ.get('DB_NAME')
        instance_connection_name = os.environ.get('INSTANCE_CONNECTION_NAME')
        if not all([db_user, db_password, db_name, instance_connection_name]):
            log.critical("KRYTYCZNY BŁĄD: Brak zmiennych środowiskowych bazy danych w app.yaml!")
            raise ValueError("Brakujące zmienne środowiskowe bazy danych!")
        safe_password = urllib.parse.quote_plus(db_password)
        unix_socket_path = f'/cloudsql/{instance_connection_name}'
        db_uri = f"postgresql+psycopg2://{db_user}:{safe_password}@/{db_name}?host={unix_socket_path}"
        log.info(f"DB Config (App Engine Socket): postgresql+psycopg2://{db_user}:*****@/{db_name}?host={unix_socket_path}")
    else:
        # Środowisko lokalne - użyj SQLALCHEMY_DATABASE_URI z .env
        db_uri = os.environ.get('SQLALCHEMY_DATABASE_URI')
        if not db_uri:
            log.critical("KRYTYCZNY BŁĄD: Brak SQLALCHEMY_DATABASE_URI w .env dla środowiska lokalnego!")
            raise ValueError("Brak SQLALCHEMY_DATABASE_URI!")
        log.info(f"DB Config (Local/Cloud SQL Proxy): {db_uri.split('@')[0]}@***")

    app.config['SQLALCHEMY_DATABASE_URI'] = db_uri
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    app.config['INFAKT_API_KEY'] = os.environ.get('INFAKT_API_KEY')
    app.config['SMTP_SERVER'] = os.environ.get('SMTP_SERVER')
    app.config['SMTP_PORT'] = int(os.environ.get('SMTP_PORT', 587))
    app.config['SMTP_USERNAME'] = os.environ.get('SMTP_USERNAME')
    app.config['SMTP_PASSWORD'] = os.environ.get('SMTP_PASSWORD')
    app.config['EMAIL_FROM'] = os.environ.get('EMAIL_FROM', app.config.get('SMTP_USERNAME'))
    if not app.config['INFAKT_API_KEY']:
        log.warning("Brak INFAKT_API_KEY!")
    if not all([app.config['SMTP_SERVER'], app.config['SMTP_USERNAME'], app.config['SMTP_PASSWORD']]):
        log.warning("Brak pełnej konfiguracji SMTP!")

    db.init_app(app)
    migrate = Migrate(app, db)
    app.jinja_env.globals.update(min=min)

    @app.context_processor
    def inject_active_accounts():
        """
        Wstrzykuje listę aktywnych kont do wszystkich szablonów.
        Potrzebne dla dropdown w navbarze.
        """
        if session.get('logged_in'):
            accounts = Account.query.filter_by(is_active=True).order_by(Account.name).all()
            return dict(active_accounts=accounts)
        return dict(active_accounts=[])

    @app.before_request
    def require_login():
        is_cli_bp = hasattr(request, 'blueprint') and request.blueprint == 'cli'
        # Dodano 'select_account', 'switch_account', 'cron_run_sync' do listy endpointów zwalnianych
        if request.endpoint in ('static', 'login', 'select_account', 'switch_account', 'cron_run_sync') or is_cli_bp:
            return None

        if not session.get('logged_in'):
            flash("Musisz się zalogować, aby uzyskać dostęp.", "warning")
            return redirect(url_for('login'))

        # NOWE: Sprawdź czy wybrany profil
        if not session.get('current_account_id'):
            flash("Wybierz profil aby kontynuować.", "warning")
            return redirect(url_for('select_account'))

    @app.route('/')
    def active_cases():
        try:
            # Sprawdź czy wybrany profil
            account_id = session.get('current_account_id')
            if not account_id:
                flash("Wybierz profil.", "warning")
                return redirect(url_for('select_account'))

            import time
            start_time = time.time()

            search_query = request.args.get('search', '').strip().lower()
            sort_by = request.args.get('sort_by', 'case_number')
            sort_order = request.args.get('sort_order', 'asc')
            page = request.args.get('page', 1, type=int)
            per_page = 100

            stage_mapping_progress = {
                "Przypomnienie o zbliżającym się terminie płatności": 1,
                "Powiadomienie o upływie terminu płatności": 2,
                "Wezwanie do zapłaty": 3,
                "Powiadomienie o zamiarze skierowania sprawy do windykatora zewnętrznego i publikacji na giełdzie wierzytelności": 4,
                "Przekazanie sprawy do windykatora zewnętrznego": 5
            }

            def stage_from_log_text(text):
                stage_key = str(text).split(" (")[0]
                return stage_mapping_progress.get(stage_key, 0)

            # OPTYMALIZACJA: Pobierz Case z Invoice w jednym zapytaniu (JOIN)
            # Filtruj po account_id dla multi-tenancy
            from sqlalchemy.orm import joinedload
            cases_with_invoices = (
                Case.query
                .options(joinedload(Case.invoice))
                .filter_by(status="active", account_id=account_id)
                .all()
            )

            log.info(f"[active_cases] Pobrano {len(cases_with_invoices)} spraw aktywnych w {time.time()-start_time:.2f}s")

            # Zbierz wszystkie invoice_numbers dla jednego zapytania do NotificationLog
            invoice_numbers = [case.invoice.invoice_number for case in cases_with_invoices if case.invoice]

            # OPTYMALIZACJA: Pobierz wszystkie NotificationLog w JEDNYM zapytaniu
            # MULTI-TENANCY: Filtruj również po account_id
            all_logs = []
            if invoice_numbers:
                all_logs = NotificationLog.query.filter(
                    NotificationLog.invoice_number.in_(invoice_numbers),
                    NotificationLog.account_id == account_id
                ).all()

            # Zgrupuj logi po invoice_number dla szybkiego dostępu
            logs_by_invoice = {}
            for log_entry in all_logs:
                if log_entry.invoice_number not in logs_by_invoice:
                    logs_by_invoice[log_entry.invoice_number] = []
                logs_by_invoice[log_entry.invoice_number].append(log_entry)

            log.info(f"[active_cases] Pobrano {len(all_logs)} logów powiadomień w {time.time()-start_time:.2f}s")

            # Przetwarzanie danych (bez dodatkowych queries!)
            cases_list = []
            total_debt_all_cents = 0

            for case_obj in cases_with_invoices:
                inv = case_obj.invoice
                if not inv:
                    continue

                left = inv.left_to_pay if inv.left_to_pay is not None else (inv.gross_price - (inv.paid_price or 0))
                total_debt_cents = left if left is not None else 0
                total_debt_all_cents += total_debt_cents
                day_diff = (date.today() - inv.payment_due_date).days if inv.payment_due_date else None

                # Użyj pre-loaded logów zamiast query
                logs_for_invoice = logs_by_invoice.get(inv.invoice_number, [])
                max_stage = 0
                for lg in logs_for_invoice:
                    st = stage_from_log_text(lg.stage)
                    max_stage = max(max_stage, st)

                progress_val = int((max_stage / 5) * 100)

                cases_list.append({
                    'case_number': case_obj.case_number,
                    'client_id': case_obj.client_id,
                    'client_company_name': case_obj.client_company_name,
                    'client_nip': inv.client_nip,
                    'client_email': inv.client_email if inv.client_email else "Brak",
                    'total_debt': total_debt_cents / 100.0,
                    'days_diff': day_diff,
                    'progress_percent': progress_val,
                    'status': case_obj.status
                })

            # Filtrowanie po wyszukiwaniu
            if search_query:
                cases_list = [
                    c for c in cases_list
                    if search_query in (c.get('client_id') or '').lower()
                    or search_query in (str(c.get('client_nip') or '')).lower()
                    or search_query in (c.get('client_company_name') or '').lower()
                    or search_query in (c.get('case_number') or '').lower()
                    or search_query in (c.get('client_email') or '').lower()
                ]

            # Sortowanie
            if cases_list:
                try:
                    key_func = lambda x: x.get(sort_by, 0)
                    if sort_by == 'days_diff':
                        key_func = lambda x: (x.get(sort_by, -float('inf')) if x.get(sort_by) is not None else -float('inf'))
                    elif sort_by == 'progress_percent':
                        key_func = lambda x: x.get('progress_percent', 0)
                    elif sort_by in cases_list[0]:
                        first_val = cases_list[0].get(sort_by)
                        if isinstance(first_val, str):
                            key_func = lambda x: (x.get(sort_by) or "").lower()
                        elif isinstance(first_val, (int, float)):
                            key_func = lambda x: x.get(sort_by, 0)
                    cases_list.sort(key=key_func, reverse=(sort_order == "desc"))
                except Exception as e:
                    log.error(f"Sortowanie error w active_cases: {e}", exc_info=True)

            # Paginacja
            total_count = len(cases_list)
            total_pages = (total_count + per_page - 1) // per_page if per_page > 0 else 1
            start_idx = (page - 1) * per_page
            end_idx = min(start_idx + per_page, total_count)
            paginated_cases = cases_list[start_idx:end_idx]
            total_debt_all = total_debt_all_cents / 100.0
            active_count = total_count

            elapsed = time.time() - start_time
            log.info(f"[active_cases] Zakończono w {elapsed:.2f}s, zwrócono {len(paginated_cases)}/{total_count} spraw")

            return render_template(
                'cases.html',
                cases=paginated_cases,
                search_query=search_query,
                sort_by=sort_by,
                sort_order=sort_order,
                total_debt_all=total_debt_all,
                active_count=active_count,
                page=page,
                per_page=per_page,
                total_pages=total_pages,
                total_count=total_count
            )
        except Exception as e:
            log.error(f"General error in active_cases: {e}", exc_info=True)
            flash("Wystąpił błąd podczas ładowania spraw aktywnych.", "danger")
            return render_template('cases.html', cases=[], search_query="", sort_by="case_number", sort_order="asc", total_debt_all=0, active_count=0, page=1, per_page=100, total_pages=0, total_count=0)

    @app.route('/completed')
    def completed_cases():
        try:
            # Sprawdź czy wybrany profil
            account_id = session.get('current_account_id')
            if not account_id:
                flash("Wybierz profil.", "warning")
                return redirect(url_for('select_account'))

            import time
            start_time = time.time()

            search_query = request.args.get('search', '').strip().lower()
            sort_by = request.args.get('sort_by', 'case_number')
            sort_order = request.args.get('sort_order', 'asc')
            page = request.args.get('page', 1, type=int)
            per_page = 100

            stage_mapping_progress = {
                "Przypomnienie o zbliżającym się terminie płatności": 1,
                "Powiadomienie o upływie terminu płatności": 2,
                "Wezwanie do zapłaty": 3,
                "Powiadomienie o zamiarze skierowania sprawy do windykatora zewnętrznego i publikacji na giełdzie wierzytelności": 4,
                "Przekazanie sprawy do windykatora zewnętrznego": 5
            }

            def stage_from_log_text(text):
                stage_key = str(text).split(" (")[0]
                return stage_mapping_progress.get(stage_key, 0)

            # OPTYMALIZACJA: Pobierz Case z Invoice w jednym zapytaniu (JOIN)
            # Filtruj po account_id dla multi-tenancy
            from sqlalchemy.orm import joinedload
            cases_with_invoices = (
                Case.query
                .options(joinedload(Case.invoice))
                .filter(Case.status != "active")
                .filter_by(account_id=account_id)
                .order_by(Case.updated_at.desc())
                .all()
            )

            log.info(f"[completed_cases] Pobrano {len(cases_with_invoices)} spraw zamkniętych w {time.time()-start_time:.2f}s")

            # Zbierz wszystkie invoice_numbers dla jednego zapytania do NotificationLog
            invoice_numbers = [case.invoice.invoice_number for case in cases_with_invoices if case.invoice]

            # OPTYMALIZACJA: Pobierz wszystkie NotificationLog w JEDNYM zapytaniu
            # MULTI-TENANCY: Filtruj również po account_id
            all_logs = []
            if invoice_numbers:
                all_logs = NotificationLog.query.filter(
                    NotificationLog.invoice_number.in_(invoice_numbers),
                    NotificationLog.account_id == account_id
                ).all()

            # Zgrupuj logi po invoice_number dla szybkiego dostępu
            logs_by_invoice = {}
            for log_entry in all_logs:
                if log_entry.invoice_number not in logs_by_invoice:
                    logs_by_invoice[log_entry.invoice_number] = []
                logs_by_invoice[log_entry.invoice_number].append(log_entry)

            log.info(f"[completed_cases] Pobrano {len(all_logs)} logów powiadomień w {time.time()-start_time:.2f}s")

            # Przetwarzanie danych (bez dodatkowych queries!)
            cases_list = []
            stage_counts = {i: 0 for i in range(1, 6)}

            for case_obj in cases_with_invoices:
                inv = case_obj.invoice
                if not inv:
                    continue

                left = inv.left_to_pay if inv.left_to_pay is not None else (inv.gross_price - (inv.paid_price or 0))
                day_diff = (date.today() - inv.payment_due_date).days if inv.payment_due_date else None

                # Użyj pre-loaded logów zamiast query
                logs_for_invoice = logs_by_invoice.get(inv.invoice_number, [])
                max_stage = 0
                for lg in logs_for_invoice:
                    st = stage_from_log_text(lg.stage)
                    max_stage = max(max_stage, st)

                progress_val = int((max_stage / 5) * 100)
                stage_num = max(1, min(int(max_stage), 5))
                if stage_num > 0:
                    stage_counts[stage_num] += 1

                payment_info = {
                    'paid_date': inv.paid_date.strftime('%Y-%m-%d') if inv.paid_date else None,
                    'paid_amount': inv.paid_price / 100.0 if inv.paid_price else 0.0,
                    'total_amount': inv.gross_price / 100.0 if inv.gross_price else 0.0,
                    'payment_method': inv.payment_method or "N/A"
                }
                cases_list.append({
                    'case_number': case_obj.case_number,
                    'client_id': case_obj.client_id,
                    'client_company_name': case_obj.client_company_name,
                    'client_nip': inv.client_nip,
                    'client_email': inv.client_email if inv.client_email else "Brak",
                    'total_debt': (left / 100.0) if left else 0.0,
                    'days_diff': day_diff,
                    'progress_percent': progress_val,
                    'status': case_obj.status,
                    'payment_info': payment_info,
                    'invoice_date': inv.invoice_date.strftime('%Y-%m-%d') if inv.invoice_date else None,
                    'payment_due_date': inv.payment_due_date.strftime('%Y-%m-%d') if inv.payment_due_date else None
                })

            # Filtrowanie po wyszukiwaniu
            if search_query:
                cases_list = [
                    c for c in cases_list
                    if search_query in (c.get('client_id') or '').lower()
                    or search_query in (str(c.get('client_nip') or '')).lower()
                    or search_query in (c.get('client_company_name') or '').lower()
                    or search_query in (c.get('case_number') or '').lower()
                    or search_query in (c.get('client_email') or '').lower()
                ]

            # Sortowanie
            if cases_list:
                try:
                    key_func = lambda x: x.get(sort_by, 0)
                    if sort_by == 'days_diff':
                        key_func = lambda x: (x.get(sort_by, -float('inf')) if x.get(sort_by) is not None else -float('inf'))
                    elif sort_by == 'progress_percent':
                        key_func = lambda x: x.get('progress_percent', 0)
                    elif sort_by in cases_list[0]:
                        first_val = cases_list[0].get(sort_by)
                        if isinstance(first_val, str):
                            key_func = lambda x: (x.get(sort_by) or "").lower()
                        elif isinstance(first_val, (int, float)):
                            key_func = lambda x: x.get(sort_by, 0)
                    cases_list.sort(key=key_func, reverse=(sort_order == "desc"))
                except Exception as e:
                    log.error(f"Sortowanie error w completed_cases: {e}", exc_info=True)

            # Paginacja
            total_count = len(cases_list)
            total_pages = (total_count + per_page - 1) // per_page if per_page > 0 else 1
            start_idx = (page - 1) * per_page
            end_idx = min(start_idx + per_page, total_count)
            paginated_cases = cases_list[start_idx:end_idx]
            completed_count = total_count

            elapsed = time.time() - start_time
            log.info(f"[completed_cases] Zakończono w {elapsed:.2f}s, zwrócono {len(paginated_cases)}/{total_count} spraw")

            return render_template(
                'completed.html',
                cases=paginated_cases,
                search_query=search_query,
                sort_by=sort_by,
                sort_order=sort_order,
                completed_count=completed_count,
                stage_counts=stage_counts,
                page=page,
                per_page=per_page,
                total_pages=total_pages,
                total_count=total_count
            )
        except Exception as e:
            log.error(f"General error in completed_cases: {e}", exc_info=True)
            flash("Błąd ładowania spraw zakończonych.", "danger")
            return render_template('completed.html', cases=[], stage_counts={i: 0 for i in range(1, 6)}, completed_count=0, search_query="", sort_by="case_number", sort_order="asc", page=1, per_page=100, total_pages=0, total_count=0)

    @app.route('/case/<path:case_number>')
    def case_detail(case_number):
        try:
            # Sprawdź czy wybrany profil
            account_id = session.get('current_account_id')
            if not account_id:
                flash("Wybierz profil.", "warning")
                return redirect(url_for('select_account'))

            case_obj = Case.query.filter_by(case_number=case_number, account_id=account_id).first_or_404()
            inv = Invoice.query.filter_by(case_id=case_obj.id).first() or Invoice.query.filter_by(invoice_number=case_number).first_or_404()
            if inv and not inv.case_id:
                inv.case_id = case_obj.id
                db.session.add(inv)
                db.session.commit()
                log.info(f"Dowiązano fakturę {inv.invoice_number} do sprawy {case_obj.id}")
            left = inv.left_to_pay if inv.left_to_pay is not None else (inv.gross_price - (inv.paid_price or 0))
            day_diff = (date.today() - inv.payment_due_date).days if inv.payment_due_date else None
            # MULTI-TENANCY: Filtruj logi po account_id
            logs = NotificationLog.query.filter_by(
                invoice_number=inv.invoice_number,
                account_id=account_id
            ).order_by(NotificationLog.sent_at.desc()).all()
            modified_logs = []
            max_stage_num = 0
            stage_mapping_progress = {
                "Przypomnienie o zbliżającym się terminie płatności": 1,
                "Powiadomienie o upływie terminu płatności": 2,
                "Wezwanie do zapłaty": 3,
                "Powiadomienie o zamiarze skierowania sprawy do windykatora zewnętrznego i publikacji na giełdzie wierzytelności": 4,
                "Przekazanie sprawy do windykatora zewnętrznego": 5
            }
            def stage_from_log_text(text):
                stage_key = str(text).split(" (")[0]
                return stage_mapping_progress.get(stage_key, 0)
            for lg in logs:
                st = stage_from_log_text(lg.stage)
                max_stage_num = max(max_stage_num, st)
                modified_logs.append({
                    "id": lg.id,
                    "sent_at": lg.sent_at,
                    "stage": f"{lg.stage} ({lg.mode})",
                    "subject": lg.subject,
                    "body": lg.body
                })
            progress_val = int((max_stage_num / 5) * 100)
            return render_template('case_detail.html', case=case_obj, invoice=inv, left_to_pay=left, days_display=day_diff, progress_percent=progress_val, notifications=modified_logs)
        except Exception as e:
            log.error(f"Błąd w case_detail dla {case_number}: {e}", exc_info=True)
            flash(f"Błąd ładowania sprawy {case_number}.", "danger")
            return redirect(url_for('active_cases'))

    @app.route('/client/<client_id>')
    def client_cases(client_id):
        try:
            # Sprawdź czy wybrany profil
            account_id = session.get('current_account_id')
            if not account_id:
                flash("Wybierz profil.", "warning")
                return redirect(url_for('select_account'))

            current_date = date.today()
            # Filtruj Invoice po account_id poprzez JOIN z Case
            latest_invoice = (
                Invoice.query
                .join(Case, Invoice.case_id == Case.id)
                .filter(Case.account_id == account_id)
                .filter(Case.client_id == client_id)
                .order_by(Invoice.invoice_date.desc())
                .first()
            )
            client_details = {}
            if latest_invoice:
                client_details = {
                    'client_company_name': latest_invoice.client_company_name,
                    'client_nip': latest_invoice.client_nip,
                    'client_email': latest_invoice.client_email,
                    'client_address': latest_invoice.client_address
                }
            else:
                first_case = Case.query.filter_by(client_id=client_id, account_id=account_id).first()
                client_details = {
                    'client_company_name': first_case.client_company_name,
                    'client_nip': first_case.client_nip
                } if first_case else {}

            active_cases_list = []
            completed_cases_list = []
            total_debt_all_cents = 0
            all_cases_for_client = (
                db.session.query(Case, Invoice)
                .outerjoin(Invoice, Case.id == Invoice.case_id)
                .filter(Case.client_id == client_id)
                .filter(Case.account_id == account_id)
                .order_by(Case.status.asc(), Invoice.invoice_date.desc())
                .all()
            )
            stage_mapping_progress = {
                "Przypomnienie o zbliżającym się terminie płatności": 1,
                "Powiadomienie o upływie terminu płatności": 2,
                "Wezwanie do zapłaty": 3,
                "Powiadomienie o zamiarze skierowania sprawy do windykatora zewnętrznego i publikacji na giełdzie wierzytelności": 4,
                "Przekazanie sprawy do windykatora zewnętrznego": 5
            }
            def build_case_dict(case_obj, inv, account_id):
                if not inv:
                    return None
                left = inv.left_to_pay if inv.left_to_pay is not None else (inv.gross_price - (inv.paid_price or 0))
                total_debt = left / 100.0
                days_diff = (current_date - inv.payment_due_date).days if inv.payment_due_date else None
                try:
                    # MULTI-TENANCY: Filtruj logi po account_id
                    logs = NotificationLog.query.filter_by(
                        invoice_number=inv.invoice_number,
                        account_id=account_id
                    ).all()
                    max_stage = 0
                except Exception as e_log:
                    log.error(f"Błąd pobierania logów dla {inv.invoice_number}: {e_log}")
                    logs = []
                for lg in logs:
                    stage_text = str(lg.stage).split(" (")[0]
                    st = stage_mapping_progress.get(stage_text, 0)
                    max_stage = max(max_stage, st)
                progress_val = int((max_stage / 5) * 100)
                return {
                    'case_number': case_obj.case_number,
                    'client_id': case_obj.client_id,
                    'client_company_name': case_obj.client_company_name,
                    'client_nip': inv.client_nip,
                    'client_email': inv.client_email if inv.client_email else "Brak",
                    'total_debt': total_debt,
                    'days_diff': days_diff,
                    'progress_percent': progress_val,
                    'status': case_obj.status
                }
            for case_obj, inv in all_cases_for_client:
                res = build_case_dict(case_obj, inv, account_id)
                if res:
                    if case_obj.status == 'active':
                        total_debt_all_cents += int(res['total_debt'] * 100)
                        active_cases_list.append(res)
                    else:
                        completed_cases_list.append(res)
            active_count = len(active_cases_list)
            total_debt_all = total_debt_all_cents / 100.0
            active_cases_list.sort(key=lambda x: x['case_number'], reverse=True)
            completed_cases_list.sort(key=lambda x: x['case_number'], reverse=True)
            return render_template('client_cases.html', active_cases=active_cases_list, completed_cases=completed_cases_list, client_id=client_id, client_details=client_details, total_debt_all=total_debt_all, active_count=active_count, current_date=current_date)
        except Exception as e:
            log.error(f"Błąd w client_cases dla {client_id}: {e}", exc_info=True)
            flash(f"Błąd ładowania spraw klienta {client_id}.", "danger")
            return redirect(url_for('active_cases'))

    @app.route('/mark_paid/<int:invoice_id>')
    def mark_invoice_paid(invoice_id):
        try:
            # Sprawdź czy wybrany profil
            account_id = session.get('current_account_id')
            if not account_id:
                flash("Wybierz profil.", "warning")
                return redirect(url_for('select_account'))

            # MULTI-TENANCY: Pobierz fakturę przez JOIN z Case i sprawdź account_id
            invoice = (
                Invoice.query
                .join(Case, Invoice.case_id == Case.id)
                .filter(Invoice.id == invoice_id)
                .filter(Case.account_id == account_id)
                .first()
            )

            if not invoice:
                flash("Nie znaleziono faktury lub brak dostępu.", "danger")
                return redirect(url_for('active_cases'))

            # Pobierz case (mamy pewność że należy do account_id przez filtr w JOIN)
            case = Case.query.get(invoice.case_id)
            invoice.status = "paid"
            invoice.paid_price = invoice.gross_price
            invoice.left_to_pay = 0
            invoice.paid_date = date.today()
            db.session.add(invoice)
            case.status = "closed_oplacone"
            db.session.add(case)
            log_entry = NotificationLog(
                account_id=account_id,
                client_id=invoice.client_id,
                invoice_number=invoice.invoice_number,
                email_to=invoice.client_email if invoice.client_email else "N/A",
                subject="Faktura oznaczona jako opłacona",
                body=f"Faktura {invoice.invoice_number} oznaczona jako opłacona dnia {date.today().strftime('%Y-%m-%d')}.",
                stage="Zamknięcie sprawy",
                mode="System",
                sent_at=datetime.utcnow()
            )
            db.session.add(log_entry)
            db.session.commit()
            flash(f"Faktura {invoice.invoice_number} oznaczona jako opłacona, sprawa zamknięta.", "success")
        except Exception as e:
            log.error(f"Error marking invoice {invoice_id} as paid: {e}", exc_info=True)
            flash(f"Błąd oznaczania jako opłaconej: {str(e)}", "danger")
            db.session.rollback()
        return redirect(url_for('active_cases'))

    @app.route('/send_manual/<path:case_number>/<stage>')
    def send_manual(case_number, stage):
        inv = None
        try:
            # Sprawdź czy wybrany profil
            account_id = session.get('current_account_id')
            if not account_id:
                flash("Wybierz profil.", "warning")
                return redirect(url_for('select_account'))

            case_obj = Case.query.filter_by(case_number=case_number, account_id=account_id).first_or_404()
            inv = Invoice.query.filter_by(case_id=case_obj.id).first() or Invoice.query.filter_by(invoice_number=case_number).first()
            if not inv:
                flash("Faktura nie znaleziona.", "danger")
                return redirect(url_for('active_cases'))
            if not inv.client_email or '@' not in inv.client_email:
                flash("Brak lub niepoprawny email klienta.", "danger")
                return redirect(url_for('case_detail', case_number=case_number))
            mapped = map_stage(stage)
            if not mapped:
                flash("Nieprawidłowy etap.", "danger")
                return redirect(url_for('case_detail', case_number=case_number))

            # MULTI-TENANCY: Pobierz account dla generate_email
            account = Account.query.get(account_id)
            if not account:
                flash("Błąd: nie znaleziono konta.", "danger")
                return redirect(url_for('active_cases'))

            subject, body_html = generate_email(mapped, inv, account)
            if not subject or not body_html:
                flash("Błąd szablonu.", "danger")
                return redirect(url_for('case_detail', case_number=case_number))
            existing_log = NotificationLog.query.filter_by(invoice_number=inv.invoice_number, stage=mapped, account_id=account_id).first()
            if existing_log:
                flash(f"Powiadomienie ({mapped}) już wysłane {existing_log.sent_at.strftime('%Y-%m-%d %H:%M')}.", "warning")
                return redirect(url_for('case_detail', case_number=case_number))
            email_success = False
            email_errors = []
            emails = [email.strip() for email in inv.client_email.split(',') if email.strip()]
            for email in emails:
                try:
                    # MULTI-TENANCY: Używamy send_email_for_account z dedykowanym SMTP
                    if send_email_for_account(account, email, subject, body_html, html=True):
                        email_success = True
                    else:
                        email_errors.append(f"Nieudana wysyłka do {email}")
                except Exception as e:
                    email_errors.append(f"{email}: {str(e)}")
                    log.error(f"Error sending manual email to {email}: {e}", exc_info=True)
            if not email_success:
                error_msg = "; ".join(email_errors) if email_errors else "Nieznany błąd."
                flash(f"Błąd wysyłki: {error_msg}", "danger")
                return redirect(url_for('case_detail', case_number=case_number))
            inv.debt_status = mapped
            new_log = NotificationLog(
                account_id=account_id,
                client_id=inv.client_id,
                invoice_number=inv.invoice_number,
                email_to=inv.client_email,
                subject=subject,
                body=body_html,
                stage=mapped,
                mode="Manualne",
                sent_at=datetime.utcnow()
            )
            db.session.add(inv)
            db.session.add(new_log)
            db.session.commit()

            def stage_to_number(text):
                mapping = {
                    "Przypomnienie o zbliżającym się terminie płatności": 1,
                    "Powiadomienie o upływie terminu płatności": 2,
                    "Wezwanie do zapłaty": 3,
                    "Powiadomienie o zamiarze skierowania sprawy do windykatora zewnętrznego i publikacji na giełdzie wierzytelności": 4,
                    "Przekazanie sprawy do windykatora zewnętrznego": 5
                }
                stage_key = str(text).split(" (")[0]
                return mapping.get(stage_key, 0)

            if stage_to_number(mapped) >= 5 and case_obj.status == 'active':
                case_obj.status = "closed_nieoplacone"
                db.session.add(case_obj)
                db.session.commit()
                flash("Sprawa zamknięta (nieopłacona) po wysłaniu etapu 5.", "info")
            flash("Powiadomienie wysłane.", "success")
        except Exception as e:
            log.error(f"Error in send_manual for {case_number}: {e}", exc_info=True)
            flash(f"Nieoczekiwany błąd wysyłki: {str(e)}", "danger")
            db.session.rollback()
        target_case_num = case_number if 'case_number' in locals() else (inv.invoice_number if inv else '')
        if target_case_num:
            return redirect(url_for('case_detail', case_number=target_case_num))
        else:
            return redirect(url_for('active_cases'))

    def background_sync(app_context, account_id):
        """
        Funkcja synchronizacji w tle dla konkretnego konta.

        Args:
            app_context: Flask application context
            account_id (int): ID profilu do synchronizacji
        """
        with app_context:
            try:
                log.info(f"[background_sync] Start synchronizacji w tle dla account_id={account_id}...")
                start_time = datetime.utcnow()
                # MULTI-TENANCY: Przekaż account_id do run_full_sync
                processed = run_full_sync(account_id)
                duration = (datetime.utcnow() - start_time).total_seconds()
                log.info(f"[background_sync] Koniec synchronizacji w tle dla account_id={account_id}. Czas: {duration:.2f}s. Przetworzono/zmieniono: {processed}.")
            except Exception as e:
                log.error(f"Krytyczny błąd w wątku background_sync dla account_id={account_id}: {e}", exc_info=True)

    @app.route('/manual_sync', methods=['GET'])
    def manual_sync():
        if not session.get('logged_in'):
            flash("Musisz być zalogowany, aby uruchomić synchronizację.", "danger")
            return redirect(url_for('login'))

        # MULTI-TENANCY: Pobierz account_id z sesji
        account_id = session.get('current_account_id')
        if not account_id:
            flash("Wybierz profil przed synchronizacją.", "warning")
            return redirect(url_for('select_account'))

        account_name = session.get('current_account_name', f'ID:{account_id}')
        log.info(f"Żądanie ręcznej synchronizacji dla konta '{account_name}' (ID: {account_id}).")

        # Uruchom synchronizację tylko dla wybranego konta
        thread = threading.Thread(target=background_sync, args=(app.app_context(), account_id))
        thread.start()
        flash(f"Synchronizacja w tle uruchomiona dla profilu '{account_name}'. Wyniki pojawią się w statusie synchronizacji.", "info")
        return redirect(url_for('active_cases'))

    @app.route('/cron/run_sync')
    def cron_run_sync():
        is_cron_request = request.headers.get('X-Appengine-Cron') == 'true'
        if not is_cron_request:
            log.warning("Nieautoryzowana próba wywołania /cron/run_sync (nie z Cron).")
            return jsonify({"status": "ignored", "message": "Request not from App Engine Cron"}), 200

        log.info("Otrzymano żądanie z App Engine Cron: /cron/run_sync.")

        # MULTI-TENANCY: Synchronizuj wszystkie aktywne konta
        active_accounts = Account.query.filter_by(is_active=True).all()

        if not active_accounts:
            log.warning("Brak aktywnych kont do synchronizacji.")
            return jsonify({"status": "no_accounts", "message": "No active accounts to sync"}), 200

        log.info(f"Uruchamiam synchronizację dla {len(active_accounts)} aktywnych kont...")

        # Uruchom synchronizację dla każdego aktywnego konta w osobnym wątku
        for account in active_accounts:
            log.info(f"[cron] Uruchamiam sync dla konta: {account.name} (ID: {account.id})")
            thread = threading.Thread(target=background_sync, args=(app.app_context(), account.id))
            thread.start()

        log.info(f"Wątki background_sync zostały uruchomione dla {len(active_accounts)} kont przez Cron.")
        return jsonify({
            "status": "accepted",
            "message": f"Sync jobs started for {len(active_accounts)} accounts",
            "accounts": [{"id": acc.id, "name": acc.name} for acc in active_accounts]
        }), 202

    @app.route('/sync_status')
    def sync_status():
        try:
            # MULTI-TENANCY: Pobierz account_id z sesji
            account_id = session.get('current_account_id')
            if not account_id:
                flash("Wybierz profil.", "warning")
                return redirect(url_for('select_account'))

            # MULTI-TENANCY: Filtruj statusy synchronizacji po account_id (jeśli kolumna istnieje)
            if hasattr(SyncStatus, 'account_id'):
                statuses = SyncStatus.query.filter_by(account_id=account_id).order_by(SyncStatus.timestamp.desc()).limit(20).all()
            else:
                # Fallback: brak kolumny account_id - pokaż wszystkie (backward compatibility)
                statuses = SyncStatus.query.order_by(SyncStatus.timestamp.desc()).limit(20).all()
                flash("UWAGA: Statusy synchronizacji nie są jeszcze per-profil. Wyświetlam wszystkie.", "warning")

            return render_template('sync_status.html', statuses=statuses)
        except Exception as e:
            log.error(f"Błąd ładowania statusu synchronizacji: {e}", exc_info=True)
            flash("Błąd ładowania historii synchronizacji.", "danger")
            return render_template('sync_status.html', statuses=[])

    @app.route('/shipping_settings', methods=['GET', 'POST'], endpoint='shipping_settings_view')
    def shipping_settings_view():
        try:
            # Sprawdź czy wybrany profil
            account_id = session.get('current_account_id')
            if not account_id:
                flash("Wybierz profil.", "warning")
                return redirect(url_for('select_account'))

            NotificationSettings.initialize_default_settings(account_id)
            current_settings = NotificationSettings.get_all_settings(account_id)
        except Exception as e:
            log.error(f"Błąd NotificationSettings: {e}. Migracje?", exc_info=True)
            flash("Błąd ustawień. Administrator.", "danger")
            current_settings = {}
        if request.method == 'POST':
            try:
                new_settings = {}
                if not current_settings:
                    flash("Błąd ładowania ustawień.", "danger")
                else:
                    for key in current_settings.keys():
                        try:
                            new_settings[key] = int(request.form.get(key, current_settings[key]))
                        except (ValueError, TypeError):
                            flash(f"Zła wartość dla '{key}'.", "warning")
                            new_settings[key] = current_settings.get(key)
                    if new_settings:
                        NotificationSettings.update_settings(account_id, new_settings)
                        flash("Ustawienia zapisane.", "success")
                    else:
                        flash("Brak zmian.", "info")
            except Exception as e:
                log.error(f"Błąd zapisu ustawień: {e}", exc_info=True)
                flash(f"Błąd zapisu: {e}", "danger")
                db.session.rollback()
            return redirect(url_for('shipping_settings_view'))
        return render_template('shipping_settings.html', settings=current_settings)

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            admin_user = os.environ.get('ADMIN_USERNAME', 'admin')
            admin_pass = os.environ.get('ADMIN_PASSWORD', 'admin')
            if username == admin_user and password == admin_pass:
                session['logged_in'] = True
                flash("Zalogowano.", "success")
                return redirect(url_for('select_account'))
            else:
                flash("Złe dane.", "danger")
        return render_template('login.html')

    @app.route('/select_account')
    def select_account():
        """Wybór profilu po zalogowaniu"""
        if not session.get('logged_in'):
            return redirect(url_for('login'))

        accounts = Account.query.filter_by(is_active=True).order_by(Account.name).all()

        # Jeśli tylko jedno konto - automatycznie wybierz
        if len(accounts) == 1:
            session['current_account_id'] = accounts[0].id
            session['current_account_name'] = accounts[0].name
            flash(f'Automatycznie wybrano profil: {accounts[0].name}', 'info')
            return redirect(url_for('active_cases'))

        return render_template('select_account.html', accounts=accounts)

    @app.route('/switch_account/<int:account_id>')
    def switch_account(account_id):
        """Przełączanie między profilami"""
        if not session.get('logged_in'):
            return redirect(url_for('login'))

        account = Account.query.filter_by(id=account_id, is_active=True).first()
        if not account:
            flash("Nieprawidłowe konto.", "danger")
            return redirect(url_for('select_account'))

        session['current_account_id'] = account.id
        session['current_account_name'] = account.name
        flash(f'Przełączono na profil: {account.name}', 'success')
        return redirect(url_for('active_cases'))

    @app.route('/reopen_case/<case_number>')
    def reopen_case(case_number):
        if not session.get('logged_in'):
            flash("Zaloguj się.", "danger")
            return redirect(url_for('login'))

        # MULTI-TENANCY: Sprawdź czy wybrany profil
        account_id = session.get('current_account_id')
        if not account_id:
            flash("Wybierz profil.", "warning")
            return redirect(url_for('select_account'))

        try:
            # MULTI-TENANCY: Filtruj po account_id
            case = Case.query.filter_by(case_number=case_number, account_id=account_id).first_or_404()
            if case.status != "active":
                old_status = case.status
                case.status = "active"
                db.session.add(case)
                db.session.commit()
                flash(f'Sprawa {case_number} przywrócona (była: {old_status}).', 'success')
            else:
                flash(f'Sprawa {case_number} jest już aktywna.', 'warning')
        except Exception as e:
            log.error(f"Błąd przywracania sprawy {case_number}: {e}", exc_info=True)
            flash("Błąd przywracania sprawy.", "danger")
            db.session.rollback()
        return redirect(url_for('case_detail', case_number=case_number))

    @app.route('/logout')
    def logout():
        session.pop('logged_in', None)
        flash("Wylogowano.", "success")
        return redirect(url_for('login'))

    is_gunicorn_worker = 'GUNICORN_PID' in os.environ
    if not app.debug or is_gunicorn_worker or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        log.info(f"Warunki startu schedulera: debug={app.debug}, gunicorn_worker={is_gunicorn_worker}, WERKZEUG_RUN_MAIN={os.environ.get('WERKZEUG_RUN_MAIN')}")
        with app.app_context():
            try:
                log.info("Start schedulera...")
                # NotificationSettings są inicjalizowane per-account w /shipping_settings
                if 'start_scheduler' in globals() and callable(start_scheduler):
                    start_scheduler(app)
                    log.info("Scheduler zainicjalizowany.")
                else:
                    log.warning("start_scheduler nie znaleziony lub niewywoływalny.")
            except Exception as e:
                log.error(f"Błąd startu schedulera: {e}", exc_info=True)

    log.info("Instancja aplikacji Flask została utworzona.")
    return app


if __name__ == "__main__":
    log.info("Uruchamianie aplikacji Flask w trybie __main__ (deweloperskim)...")
    application = create_app()
    if application:
        port = int(os.environ.get("PORT", 8080))
        log.info(f"Serwer Flask startuje na http://0.0.0.0:{port}")
        application.run(host="0.0.0.0", port=port, debug=True, use_reloader=False)
    else:
        log.critical("Nie udało się stworzyć instancji aplikacji Flask.")

# --- KONIEC PLIKU: InvoiceTracker/app.py ---
