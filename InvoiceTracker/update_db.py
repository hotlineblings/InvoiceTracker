# --- POCZĄTEK PLIKU: InvoiceTracker/update_db.py (WERSJA POPRAWIONA - bez zmian w stosunku do poprzedniej) ---
import sys
from datetime import datetime, date, timedelta
# Upewnij się, że importy są poprawne dla Twojej struktury projektu
try:
    from .models import db, Invoice, Case, SyncStatus, NotificationSettings, NotificationLog, Account, AccountScheduleSettings
    from .src.api.api_client import InFaktAPIClient # Zakładając, że api_client jest w podfolderze src
except ImportError:
    try:
       from models import db, Invoice, Case, SyncStatus, NotificationSettings, NotificationLog, Account, AccountScheduleSettings
       from src.api.api_client import InFaktAPIClient
    except ImportError:
       print("Krytyczny błąd importu w update_db.py. Sprawdź ścieżki.")
       raise

from dotenv import load_dotenv
import logging
import traceback # Do logowania pełnego śladu błędu

load_dotenv()
log = logging.getLogger(__name__)
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')


def sync_new_invoices(account_id, start_offset=0, limit=100):
    """
    Pobiera nowe faktury z inFaktu (termin płatności za X dni), tworzy Invoice i Case.
    Używa tylko faktur 'sent'/'printed'.
    Dane klienta (email, NIP, adres, nazwa firmy) są **zawsze** pobierane przez /clients/{id}.json.

    Args:
        account_id (int): ID profilu/konta dla którego synchronizować dane
        start_offset (int): Offset dla paginacji API
        limit (int): Limit wyników per strona

    Zwraca krotkę: (processed_count, new_cases_count, api_calls).
    """
    # Pobierz konto aby użyć dedykowanego API key
    account = Account.query.get(account_id)
    if not account:
        log.error(f"[sync_new_invoices] Nie znaleziono konta o ID: {account_id}")
        return 0, 0, 0, 0.0  # FIX: Zwracaj 4 wartości!

    if not account.is_active:
        log.warning(f"[sync_new_invoices] Konto '{account.name}' (ID: {account_id}) jest nieaktywne. Pomijam synchronizację.")
        return 0, 0, 0, 0.0  # FIX: Zwracaj 4 wartości!

    # Użyj API key dedykowanego dla tego konta
    client = InFaktAPIClient(api_key=account.infakt_api_key)
    processed_count = 0
    new_cases_count = 0
    api_calls_listing = 0
    api_calls_clients = 0
    today = date.today()

    # Pobierz ustawienia harmonogramu dla tego konta
    settings = AccountScheduleSettings.get_for_account(account_id)
    days_ahead = settings.invoice_fetch_days_before
    new_case_due_date = today + timedelta(days=days_ahead)
    new_case_due_date_str = new_case_due_date.strftime("%Y-%m-%d")
    offset = start_offset
    start_time = datetime.utcnow()

    log.info(f"[sync_new_invoices] Start dla konta '{account.name}' (ID: {account_id}): szukanie faktur ('sent'/'printed') z terminem {new_case_due_date_str} [{days_ahead} dni przed terminem zgodnie z ustawieniami]. Offset={offset}.")

    while True:
        query_params = {"q[payment_date_eq]": new_case_due_date_str}
        fields = [
            "id", "uuid", "number", "invoice_date", "gross_price", "status", "client_id",
            "payment_date", "paid_price", "payment_method", "currency"
        ]
        batch_invoices = client.list_invoices(
            offset=offset,
            limit=limit,
            fields=fields,
            order="invoice_date desc",
            query_params=query_params
        )
        api_calls_listing += 1

        if batch_invoices is None:
            log.error(f"[sync_new_invoices] Błąd podczas pobierania listy faktur (offset={offset}). Przerywam pętlę.")
            break

        batch_invoices_filtered = [inv for inv in batch_invoices if inv.get('status') in ('sent', 'printed')]

        log.info(f"[sync_new_invoices] API zwróciło {len(batch_invoices)} faktur, po filtracji statusu: {len(batch_invoices_filtered)} (offset={offset}).")
        if not batch_invoices_filtered:
             if not batch_invoices or len(batch_invoices) < limit:
                log.info(f"[sync_new_invoices] Brak więcej pasujących faktur lub koniec danych z API.")
                break
             else:
                offset += limit
                continue

        for inv_data in batch_invoices_filtered:
            invoice_id = inv_data.get('id')
            invoice_num_api = inv_data.get('number', f'ID_{invoice_id}')

            try:
                # MULTI-TENANCY: Sprawdź czy faktura istnieje ORAZ należy do tego konta
                # (Invoice nie ma account_id, więc sprawdzamy przez JOIN z Case)
                existing_invoice = db.session.query(Invoice).outerjoin(Case, Invoice.case_id == Case.id).filter(
                    Invoice.id == invoice_id,
                    db.or_(
                        Case.account_id == account_id,  # Faktura z Case należącym do tego konta
                        Invoice.case_id == None  # LUB faktura bez Case (orphaned)
                    )
                ).first()

                if existing_invoice is not None:
                    log.info(f"[sync_new_invoices] ⏩ Faktura {invoice_num_api} (ID: {invoice_id}) już istnieje w DB dla tego konta - pomijam.")
                    continue
            except Exception as e_check:
                log.error(f"[sync_new_invoices] Błąd sprawdzania istnienia faktury {invoice_num_api}: {e_check}", exc_info=True)
                continue

            invoice_date = None
            payment_due = None
            try:
                d_str = inv_data.get('invoice_date')
                if d_str: invoice_date = datetime.strptime(d_str, '%Y-%m-%d').date()
                pd_str = inv_data.get('payment_date')
                if pd_str: payment_due = datetime.strptime(pd_str, '%Y-%m-%d').date()
            except (ValueError, TypeError) as e_date:
                log.warning(f"[sync_new_invoices] Błąd konwersji daty dla {invoice_num_api}: {e_date}")

            new_inv = Invoice(
                id=invoice_id,
                invoice_number=invoice_num_api,
                invoice_date=invoice_date,
                payment_due_date=payment_due,
                gross_price=inv_data.get('gross_price', 0),
                status=inv_data.get('status', ''),
                paid_price=inv_data.get('paid_price', 0),
                client_id=str(inv_data.get('client_id', '')),
                client_nip=None,
                client_company_name=None,
                client_email=None,
                client_address=None,
                currency=inv_data.get('currency', 'PLN'),
                payment_method=inv_data.get('payment_method')
            )
            paid = new_inv.paid_price or 0
            new_inv.left_to_pay = (new_inv.gross_price or 0) - paid

            # --- Pobieranie Danych Klienta ---
            client_id_str = new_inv.client_id
            client_data_fetched = None
            if client_id_str:
                log.debug(f"[sync_new_invoices] Próba pobrania detali dla client_id: {client_id_str} (Faktura: {invoice_num_api})")
                client_data_fetched = client.get_client_details(client_id_str) # Wywołanie poprawionej funkcji
                api_calls_clients += 1
                if client_data_fetched:
                    log.info(f"[sync_new_invoices] Sukces! Pobrano dane dla client_id: {client_id_str}.")
                    new_inv.client_email = client_data_fetched.get('email')
                    new_inv.client_nip = client_data_fetched.get('nip')
                    company_name = client_data_fetched.get('company_name')
                    if not company_name:
                        first = client_data_fetched.get('first_name', '')
                        last = client_data_fetched.get('last_name', '')
                        company_name = f"{first} {last}".strip()
                    new_inv.client_company_name = company_name if company_name else None

                    parts = []
                    post_code = client_data_fetched.get('postal_code')
                    street = client_data_fetched.get('street')
                    street_no = client_data_fetched.get('street_number')
                    flat_no = client_data_fetched.get('flat_number')
                    city = client_data_fetched.get('city')
                    if post_code: parts.append(post_code)
                    if street:
                        s = street
                        if street_no: s += f" {street_no}"
                        if flat_no: s += f"/{flat_no}"
                        parts.append(s)
                    if city: parts.append(city)
                    new_inv.client_address = ", ".join(filter(None, parts))
                    log.debug(f"[sync_new_invoices] Zaktualizowano dane w new_inv dla {invoice_num_api}: Email={new_inv.client_email}, NIP={new_inv.client_nip}, Name={new_inv.client_company_name}, Adres={new_inv.client_address}")
                else:
                    log.warning(f"[sync_new_invoices] Nie udało się pobrać danych dla client_id: {client_id_str} (Faktura: {invoice_num_api}). Invoice zostanie zapisany bez tych detali.")
            else:
                 log.warning(f"[sync_new_invoices] Brak client_id dla faktury {invoice_num_api}. Nie można pobrać szczegółów klienta.")
            # --- Koniec Pobierania Danych Klienta ---

            try:
                db.session.add(new_inv)
                db.session.commit()

                if new_inv.left_to_pay > 0 and new_inv.status in ('sent', 'printed'):
                    existing_case = db.session.query(Case.id).filter_by(case_number=new_inv.invoice_number, account_id=account_id).scalar()
                    if not existing_case:
                        new_case = Case(
                            case_number=new_inv.invoice_number,
                            account_id=account_id,  # MULTI-TENANCY: przypisz do konta
                            client_id=new_inv.client_id,
                            client_nip=new_inv.client_nip,
                            client_company_name=new_inv.client_company_name,
                            status="active"
                        )
                        db.session.add(new_case)
                        db.session.flush()

                        new_inv.case_id = new_case.id
                        db.session.add(new_inv)
                        db.session.commit()
                        new_cases_count += 1
                        log.info(f"[sync_new_invoices] Utworzono nową sprawę (ID: {new_case.id}) dla konta '{account.name}' (ID: {account_id}) i powiązano z fakturą {new_inv.invoice_number}")
                    else:
                        log.warning(f"[sync_new_invoices] Sprawa dla faktury {new_inv.invoice_number} już istnieje. Sprawdzam powiązanie.")
                        if new_inv.case_id is None:
                            case_obj = Case.query.filter_by(case_number=new_inv.invoice_number, account_id=account_id).first()
                            if case_obj:
                                new_inv.case_id = case_obj.id
                                db.session.add(new_inv)
                                db.session.commit()
                                log.info(f"[sync_new_invoices] Powiązano fakturę {new_inv.invoice_number} z istniejącą sprawą ID: {case_obj.id}")
                            else:
                                log.error(f"[sync_new_invoices] Niespójność: Sprawa dla {new_inv.invoice_number} istnieje wg query(Case.id) ale nie wg query(Case).")

                processed_count += 1

            except Exception as e_db:
                the_traceback = traceback.format_exc()
                log.error(f"[sync_new_invoices] Błąd zapisu do DB dla faktury {invoice_num_api}: {e_db}\n{the_traceback}")
                db.session.rollback()

        if len(batch_invoices) == limit:
            offset += limit
        else:
            break

    duration = (datetime.utcnow() - start_time).total_seconds()
    total_api_calls = api_calls_listing + api_calls_clients

    log.info(f"[sync_new_invoices] Zakończono dla konta '{account.name}' (ID: {account_id}). Przetworzono: {processed_count}, Nowe sprawy: {new_cases_count}, API calls (List/Client): {api_calls_listing}/{api_calls_clients}, Czas: {duration:.2f}s.")

    # ZWRÓCENIE: processed_count, new_cases_count, total_api_calls, duration
    return processed_count, new_cases_count, total_api_calls, duration


# --- update_existing_cases i run_full_sync bez zmian w stosunku do poprzedniej odpowiedzi ---

def update_existing_cases(account_id, start_offset=0, limit=100):
    """
    Aktualizuje dane płatności dla faktur powiązanych z aktywnymi sprawami.
    Nie aktualizuje danych klienta (NIP, email, adres).
    Zamyka sprawy dla opłaconych faktur.

    Args:
        account_id (int): ID profilu/konta dla którego synchronizować dane
        start_offset (int): Offset dla paginacji
        limit (int): Limit wyników per strona

    Zwraca krotkę: (processed_updates, active_after_update, closed_cases_count, api_calls).
    """
    # Pobierz konto aby użyć dedykowanego API key
    account = Account.query.get(account_id)
    if not account:
        log.error(f"[update_existing_cases] Nie znaleziono konta o ID: {account_id}")
        return 0, 0, 0, 0

    if not account.is_active:
        log.warning(f"[update_existing_cases] Konto '{account.name}' (ID: {account_id}) jest nieaktywne. Pomijam synchronizację.")
        return 0, 0, 0, 0

    # Użyj API key dedykowanego dla tego konta
    client = InFaktAPIClient(api_key=account.infakt_api_key)
    processed_updates = 0 # Liczba faktur, które faktycznie zmodyfikowano
    active_initial_count = 0 # Liczba aktywnych spraw na początku
    closed_cases_count = 0 # Liczba spraw zamkniętych w tej funkcji
    api_calls = 0
    offset = start_offset
    limit_api = 100
    start_time = datetime.utcnow()

    log.info(f"[update_existing_cases] Start dla konta '{account.name}' (ID: {account_id}): aktualizacja statusów płatności aktywnych spraw...")

    try:
        # MULTI-TENANCY: Filtruj Case tylko dla danego konta
        active_cases_data = db.session.query(Case.id, Case.case_number).filter(
            Case.status == 'active',
            Case.account_id == account_id
        ).all()
        active_invoice_numbers = {case_data.case_number for case_data in active_cases_data}
        active_initial_count = len(active_invoice_numbers)

        if not active_invoice_numbers:
            log.info(f"[update_existing_cases] Brak aktywnych spraw dla konta '{account.name}' (ID: {account_id}).")
            duration = (datetime.utcnow() - start_time).total_seconds()
            # ZWRÓCENIE: processed_updates, active_after, closed_cases, api_calls, duration
            return 0, 0, 0, 0, duration

        log.info(f"[update_existing_cases] Znaleziono {active_initial_count} aktywnych spraw dla konta '{account.name}' (ID: {account_id}).")
        remaining_active_numbers = active_invoice_numbers.copy()

    except Exception as e_query:
        log.error(f"[update_existing_cases] Błąd podczas pobierania aktywnych spraw: {e_query}", exc_info=True)
        duration = (datetime.utcnow() - start_time).total_seconds()
        # ZWRÓCENIE: processed_updates, active_after, closed_cases, api_calls, duration
        return 0, 0, 0, api_calls, duration

    today = date.today()
    start_date_str = (today - timedelta(days=35)).strftime('%Y-%m-%d')
    end_date_str = (today + timedelta(days=3)).strftime('%Y-%m-%d')
    log.info(f"[update_existing_cases] Skanowanie API dla faktur z terminem płatności: {start_date_str} - {end_date_str}")

    while True:
        query_params={
             "q[payment_date_gteq]": start_date_str,
             "q[payment_date_lteq]": end_date_str
        }
        fields = ["id", "number", "invoice_date", "payment_date", "gross_price", "status", "paid_price", "paid_date"]

        batch_invoices_api = client.list_invoices(
            offset=offset,
            limit=limit_api,
            fields=fields,
            order="invoice_date desc",
            query_params=query_params
        )
        api_calls += 1

        if batch_invoices_api is None:
             log.error(f"[update_existing_cases] Błąd podczas pobierania listy faktur (offset={offset}). Przerywam pętlę.")
             break

        log.info(f"[update_existing_cases] API zwróciło {len(batch_invoices_api)} faktur (offset={offset}).")
        if not batch_invoices_api:
            if offset == 0:
                 log.info(f"[update_existing_cases] Brak faktur w podanym zakresie dat.")
            break

        invoice_numbers_in_batch = {inv.get('number') for inv in batch_invoices_api if inv.get('number')}
        numbers_to_process = active_invoice_numbers.intersection(invoice_numbers_in_batch)

        if numbers_to_process:
            log.debug(f"[update_existing_cases] Znaleziono {len(numbers_to_process)} pasujących aktywnych spraw w tej partii API.")
            local_data = db.session.query(Invoice, Case)\
                           .join(Case, Invoice.case_id == Case.id)\
                           .filter(Invoice.invoice_number.in_(numbers_to_process))\
                           .filter(Case.status == 'active')\
                           .all()

            local_invoices_map = {inv.invoice_number: inv for inv, case in local_data}
            local_cases_map = {case.case_number: case for inv, case in local_data}

            for inv_data_api in batch_invoices_api:
                invoice_num_api = inv_data_api.get('number')
                if invoice_num_api in local_invoices_map:
                    local_inv = local_invoices_map[invoice_num_api]
                    case_obj = local_cases_map[invoice_num_api]

                    if case_obj.status != 'active':
                        remaining_active_numbers.discard(invoice_num_api)
                        continue

                    try:
                        data_changed = False
                        new_status = inv_data_api.get('status', local_inv.status)
                        if local_inv.status != new_status: local_inv.status = new_status; data_changed = True

                        new_paid = inv_data_api.get('paid_price', local_inv.paid_price)
                        if local_inv.paid_price != new_paid: local_inv.paid_price = new_paid; data_changed = True

                        new_gross = inv_data_api.get('gross_price', local_inv.gross_price)
                        if data_changed or local_inv.left_to_pay is None:
                             current_left = (new_gross or 0) - (new_paid or 0)
                             if local_inv.left_to_pay != current_left: local_inv.left_to_pay = current_left; data_changed = True

                        try:
                             pd_str = inv_data_api.get('payment_date')
                             new_due_date = datetime.strptime(pd_str, '%Y-%m-%d').date() if pd_str else None
                             if local_inv.payment_due_date != new_due_date: local_inv.payment_due_date = new_due_date; data_changed = True

                             id_str = inv_data_api.get('invoice_date')
                             new_invoice_date = datetime.strptime(id_str, '%Y-%m-%d').date() if id_str else None
                             if local_inv.invoice_date != new_invoice_date: local_inv.invoice_date = new_invoice_date; data_changed = True

                             paid_date_str = inv_data_api.get('paid_date')
                             new_paid_date = datetime.strptime(paid_date_str, '%Y-%m-%d').date() if paid_date_str else None
                             if local_inv.left_to_pay <= 0 and not new_paid_date and not local_inv.paid_date:
                                 new_paid_date = date.today()

                             if local_inv.paid_date != new_paid_date: local_inv.paid_date = new_paid_date; data_changed = True
                        except (ValueError, TypeError) as e_date:
                             log.warning(f"[update_existing_cases] Błąd konwersji daty dla {invoice_num_api}: {e_date}")

                        if data_changed:
                            processed_updates += 1
                            log.debug(f"[update_existing_cases] Aktualizacja danych płatności dla {invoice_num_api}.")
                            db.session.add(local_inv)

                        if local_inv.left_to_pay <= 0 or local_inv.status == 'paid':
                            if case_obj.status == 'active':
                                case_obj.status = "closed_oplacone"
                                closed_cases_count += 1
                                db.session.add(case_obj)
                                log.info(f"[update_existing_cases] Zamknięto sprawę {invoice_num_api} jako opłaconą.")
                        else:
                            if case_obj.status != 'active':
                                log.warning(f"[update_existing_cases] Sprawa {invoice_num_api} była {case_obj.status}, ale faktura nieopłacona. Ustawiam na 'active'.")
                                case_obj.status = 'active'
                                db.session.add(case_obj)

                        db.session.commit()

                    except Exception as e_proc:
                         the_traceback = traceback.format_exc()
                         log.error(f"[update_existing_cases] Błąd przetwarzania aktualizacji {invoice_num_api}: {e_proc}\n{the_traceback}")
                         db.session.rollback()

                    remaining_active_numbers.discard(invoice_num_api)

        if len(batch_invoices_api) == limit_api:
            offset += limit_api
        else:
            break

    duration = (datetime.utcnow() - start_time).total_seconds()
    active_after_update = active_initial_count - closed_cases_count

    if remaining_active_numbers:
        log.warning(f"[update_existing_cases] {len(remaining_active_numbers)} aktywnych spraw nie znaleziono w API dla konta '{account.name}' (ID: {account_id}). Pozostają aktywne.")

    log.info(f"[update_existing_cases] Zakończono dla konta '{account.name}' (ID: {account_id}). Zmodyfikowano: {processed_updates} faktur. Sprawy pozostały aktywne: {active_after_update}. Zamknięto: {closed_cases_count}. Czas: {duration:.2f}s. API calls: {api_calls}")

    # ZWRÓCENIE: processed_updates, active_after, closed_cases, api_calls, duration
    return processed_updates, active_after_update, closed_cases_count, api_calls, duration


def run_full_sync(account_id):
    """
    Uruchamia pełną synchronizację: nowe faktury + aktualizacja istniejących.
    Zapisuje zbiorczy wynik w SyncStatus.

    Args:
        account_id (int): ID profilu/konta dla którego synchronizować dane

    Returns:
        int: Liczba przetworzonych/zmienionych rekordów
    """
    # Pobierz konto dla logowania
    account = Account.query.get(account_id)
    if not account:
        log.error(f"[run_full_sync] Nie znaleziono konta o ID: {account_id}")
        return 0

    if not account.is_active:
        log.warning(f"[run_full_sync] Konto '{account.name}' (ID: {account_id}) jest nieaktywne. Pomijam synchronizację.")
        return 0

    log.info(f"[run_full_sync] Start pełnej synchronizacji dla konta '{account.name}' (ID: {account_id})...")
    start_time = datetime.utcnow()
    total_processed_new, total_new_cases, total_api_new, new_duration = 0, 0, 0, 0.0
    total_processed_updates, total_active_after, total_closed_update, total_api_update, update_duration = 0, 0, 0, 0, 0.0

    try:
        # MULTI-TENANCY: Przekaż account_id do sync_new_invoices
        # Zwraca: processed_count, new_cases_count, total_api_calls, duration
        total_processed_new, total_new_cases, total_api_new, new_duration = sync_new_invoices(account_id)
    except Exception as e_new:
        log.critical(f"[run_full_sync] Krytyczny błąd w sync_new_invoices dla konta '{account.name}': {e_new}", exc_info=True)

    try:
        # MULTI-TENANCY: Przekaż account_id do update_existing_cases
        # Zwraca: processed_updates, active_after, closed_cases, api_calls, duration
        total_processed_updates, total_active_after, total_closed_update, total_api_update, update_duration = update_existing_cases(account_id)
    except Exception as e_update:
        log.critical(f"[run_full_sync] Krytyczny błąd w update_existing_cases dla konta '{account.name}': {e_update}", exc_info=True)

    total_processed_records = total_processed_new + total_processed_updates
    total_api_calls = total_api_new + total_api_update
    duration = (datetime.utcnow() - start_time).total_seconds()

    try:
        # MULTI-TENANCY: Zapisz JEDEN rekord "full" z pełnym rozbiciem
        sync_record = SyncStatus(
            account_id=account_id,
            sync_type="full",
            processed=total_processed_records,
            duration=duration,
            new_cases=total_new_cases,
            updated_cases=total_active_after,
            closed_cases=total_closed_update,
            api_calls=total_api_calls,
            # NOWE POLA: rozbicie szczegółowe
            new_invoices_processed=total_processed_new,
            updated_invoices_processed=total_processed_updates,
            new_sync_duration=new_duration,
            update_sync_duration=update_duration
        )
        db.session.add(sync_record)
        db.session.commit()
        log.info(f"[run_full_sync] ✅ Zapisano status synchronizacji (1 rekord 'full' z rozbiciem)")
    except Exception as db_err:
        log.error(f"[run_full_sync] Błąd zapisu statusu pełnej synchronizacji: {db_err}", exc_info=True)
        db.session.rollback()

    log.info(f"[run_full_sync] Zakończono pełną synchronizację dla konta '{account.name}' (ID: {account_id}) w {duration:.2f}s.")
    log.info(f"  Nowe: {total_processed_new} faktur przetworzonych, {total_new_cases} spraw utworzonych (API: {total_api_new}, czas: {new_duration:.2f}s)")
    log.info(f"  Aktualizacje: {total_processed_updates} faktur zmodyfikowanych, {total_active_after} spraw aktywnych, {total_closed_update} spraw zamkniętych (API: {total_api_update}, czas: {update_duration:.2f}s)")
    log.info(f"  Łącznie przetworzonych/zmienionych: {total_processed_records}. Łącznie API: {total_api_calls}")

    return total_processed_records


if __name__ == "__main__":
    log.warning("Uruchamianie update_db.py jako skrypt główny (__main__).")
    log.warning("Dla poprawnego działania (dostęp do DB i konfiguracji) użyj komendy 'flask run' lub dedykowanego polecenia CLI.")
    pass

# --- KONIEC PLIKU: InvoiceTracker/update_db.py ---