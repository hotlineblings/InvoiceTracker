# update_db.py - Database synchronization service
"""
Serwis synchronizacji bazy danych z dostawcami faktur.
Używa warstwy abstrakcji providerów (InvoiceProvider) dla multi-provider support.
"""
import sys
from datetime import datetime, date, timedelta
import logging
import traceback

from ..extensions import db
from ..models import Invoice, Case, SyncStatus, NotificationSettings, NotificationLog, Account, AccountScheduleSettings
from ..tenant_context import tenant_context, sudo
from ..providers import get_provider

log = logging.getLogger(__name__)
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')


def sync_new_invoices(account_id, start_offset=0, limit=100):
    """
    Pobiera nowe faktury z inFaktu (termin platnosci za X dni), tworzy Invoice i Case.
    Uzywa tylko faktur 'sent'/'printed'.
    Dane klienta (email, NIP, adres, nazwa firmy) sa **zawsze** pobierane przez /clients/{id}.json.

    Args:
        account_id (int): ID profilu/konta dla ktorego synchronizowac dane
        start_offset (int): Offset dla paginacji API
        limit (int): Limit wynikow per strona

    Zwraca krotke: (processed_count, new_cases_count, api_calls, duration).
    """
    # Account nie ma account_id - używamy sudo()
    with sudo():
        account = Account.query.get(account_id)
    if not account:
        log.error(f"[sync_new_invoices] Nie znaleziono konta o ID: {account_id}")
        return 0, 0, 0, 0.0

    if not account.is_active:
        log.warning(f"[sync_new_invoices] Konto '{account.name}' (ID: {account_id}) jest nieaktywne. Pomijam synchronizacje.")
        return 0, 0, 0, 0.0

    provider = get_provider(account)
    processed_count = 0
    new_cases_count = 0
    api_calls_listing = 0
    api_calls_clients = 0
    today = date.today()

    settings = AccountScheduleSettings.get_for_account(account_id)
    days_ahead = settings.invoice_fetch_days_before
    new_case_due_date = today + timedelta(days=days_ahead)
    new_case_due_date_str = new_case_due_date.strftime("%Y-%m-%d")
    offset = start_offset
    start_time = datetime.utcnow()

    log.info(f"[sync_new_invoices] Start dla konta '{account.name}' (ID: {account_id}): szukanie faktur ('sent'/'printed') z terminem {new_case_due_date_str} [{days_ahead} dni przed terminem]. Offset={offset}.")

    while True:
        # Używamy znormalizowanych query_params - provider mapuje je na format API
        batch_invoices = provider.fetch_invoices(
            query_params={"payment_date_eq": new_case_due_date_str},
            offset=offset,
            limit=limit
        )
        api_calls_listing += 1

        if not batch_invoices:
            log.info(f"[sync_new_invoices] Brak faktur lub blad API (offset={offset}). Przerywam petle.")
            break

        batch_invoices_filtered = [inv for inv in batch_invoices if inv.get('status') in ('sent', 'printed')]

        log.info(f"[sync_new_invoices] API zwrocilo {len(batch_invoices)} faktur, po filtracji statusu: {len(batch_invoices_filtered)} (offset={offset}).")
        if not batch_invoices_filtered:
            if not batch_invoices or len(batch_invoices) < limit:
                log.info(f"[sync_new_invoices] Brak wiecej pasujacych faktur lub koniec danych z API.")
                break
            else:
                offset += limit
                continue

        for inv_data in batch_invoices_filtered:
            # Używamy znormalizowanych pól z providera
            invoice_id = inv_data.get('external_id')
            invoice_num_api = inv_data.get('number', f'ID_{invoice_id}')

            try:
                existing_invoice = db.session.query(Invoice).outerjoin(Case, Invoice.case_id == Case.id).filter(
                    Invoice.id == invoice_id,
                    db.or_(
                        Case.account_id == account_id,
                        Invoice.case_id == None
                    )
                ).first()

                if existing_invoice is not None:
                    log.info(f"[sync_new_invoices] Faktura {invoice_num_api} (ID: {invoice_id}) juz istnieje w DB - pomijam.")
                    continue
            except Exception as e_check:
                log.error(f"[sync_new_invoices] Blad sprawdzania istnienia faktury {invoice_num_api}: {e_check}", exc_info=True)
                continue

            # Provider już zwraca obiekty date - nie potrzebujemy parsowania
            invoice_date = inv_data.get('invoice_date')
            payment_due = inv_data.get('payment_due_date')

            new_inv = Invoice(
                id=invoice_id,
                account_id=account_id,  # MULTI-TENANCY: bezpośredni tenant reference
                invoice_number=invoice_num_api,
                invoice_date=invoice_date,
                payment_due_date=payment_due,
                gross_price=inv_data.get('gross_price', 0),
                status=inv_data.get('status', ''),
                paid_price=inv_data.get('paid_price', 0),
                client_id=inv_data.get('client_id', ''),
                client_nip=None,
                client_company_name=None,
                client_email=None,
                client_address=None,
                currency=inv_data.get('currency', 'PLN'),
                payment_method=inv_data.get('payment_method')
            )
            paid = new_inv.paid_price or 0
            new_inv.left_to_pay = (new_inv.gross_price or 0) - paid

            # Pobieranie danych klienta przez provider
            client_id_str = new_inv.client_id
            if client_id_str:
                log.debug(f"[sync_new_invoices] Proba pobrania detali dla client_id: {client_id_str} (Faktura: {invoice_num_api})")
                client_data = provider.get_client_details(client_id_str)
                api_calls_clients += 1

                if client_data:
                    log.info(f"[sync_new_invoices] Sukces! Pobrano dane dla client_id: {client_id_str}.")

                    # Dane podstawowe ze znormalizowanego słownika
                    new_inv.client_email = client_data.get('email')
                    new_inv.client_nip = client_data.get('nip')

                    # Nazwa firmy lub imię+nazwisko
                    company_name = client_data.get('company_name')
                    if not company_name:
                        first = client_data.get('first_name', '')
                        last = client_data.get('last_name', '')
                        company_name = f"{first} {last}".strip()
                    new_inv.client_company_name = company_name if company_name else None

                    # Budowanie pełnego adresu z rozbytych pól (NormalizedClient)
                    parts = []
                    post_code = client_data.get('postal_code')
                    street = client_data.get('street')
                    street_no = client_data.get('street_number')
                    flat_no = client_data.get('flat_number')
                    city = client_data.get('city')

                    if post_code:
                        parts.append(post_code)
                    if street:
                        s = street
                        if street_no:
                            s += f" {street_no}"
                        if flat_no:
                            s += f"/{flat_no}"
                        parts.append(s)
                    if city:
                        parts.append(city)

                    new_inv.client_address = ", ".join(filter(None, parts))
                else:
                    log.warning(f"[sync_new_invoices] Nie udalo sie pobrac danych dla client_id: {client_id_str} (Faktura: {invoice_num_api}).")
            else:
                log.warning(f"[sync_new_invoices] Brak client_id dla faktury {invoice_num_api}.")

            try:
                db.session.add(new_inv)
                db.session.commit()

                if new_inv.left_to_pay > 0 and new_inv.status in ('sent', 'printed'):
                    existing_case = db.session.query(Case.id).filter_by(case_number=new_inv.invoice_number, account_id=account_id).scalar()
                    if not existing_case:
                        new_case = Case(
                            case_number=new_inv.invoice_number,
                            account_id=account_id,
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
                        log.info(f"[sync_new_invoices] Utworzono nowa sprawe (ID: {new_case.id}) dla konta '{account.name}'")
                    else:
                        log.warning(f"[sync_new_invoices] Sprawa dla faktury {new_inv.invoice_number} juz istnieje.")
                        if new_inv.case_id is None:
                            case_obj = Case.query.filter_by(case_number=new_inv.invoice_number, account_id=account_id).first()
                            if case_obj:
                                new_inv.case_id = case_obj.id
                                db.session.add(new_inv)
                                db.session.commit()

                processed_count += 1

            except Exception as e_db:
                the_traceback = traceback.format_exc()
                log.error(f"[sync_new_invoices] Blad zapisu do DB dla faktury {invoice_num_api}: {e_db}\n{the_traceback}")
                db.session.rollback()

        if len(batch_invoices) == limit:
            offset += limit
        else:
            break

    duration = (datetime.utcnow() - start_time).total_seconds()
    total_api_calls = api_calls_listing + api_calls_clients

    log.info(f"[sync_new_invoices] Zakonczono dla konta '{account.name}' (ID: {account_id}). Przetworzono: {processed_count}, Nowe sprawy: {new_cases_count}, API calls: {total_api_calls}, Czas: {duration:.2f}s.")

    return processed_count, new_cases_count, total_api_calls, duration


def update_existing_cases(account_id, start_offset=0, limit=100):
    """
    Aktualizuje dane platnosci dla faktur powiazanych z aktywnymi sprawami.
    Nie aktualizuje danych klienta (NIP, email, adres).
    Zamyka sprawy dla oplaconych faktur.

    Args:
        account_id (int): ID profilu/konta dla ktorego synchronizowac dane
        start_offset (int): Offset dla paginacji
        limit (int): Limit wynikow per strona

    Zwraca krotke: (processed_updates, active_after_update, closed_cases_count, api_calls, duration).
    """
    # Account nie ma account_id - używamy sudo()
    with sudo():
        account = Account.query.get(account_id)
    if not account:
        log.error(f"[update_existing_cases] Nie znaleziono konta o ID: {account_id}")
        return 0, 0, 0, 0, 0.0

    if not account.is_active:
        log.warning(f"[update_existing_cases] Konto '{account.name}' (ID: {account_id}) jest nieaktywne.")
        return 0, 0, 0, 0, 0.0

    provider = get_provider(account)
    processed_updates = 0
    active_initial_count = 0
    closed_cases_count = 0
    api_calls = 0
    offset = start_offset
    limit_api = 100
    start_time = datetime.utcnow()

    log.info(f"[update_existing_cases] Start dla konta '{account.name}' (ID: {account_id}): aktualizacja statusow platnosci aktywnych spraw...")

    try:
        active_cases_data = db.session.query(Case.id, Case.case_number).filter(
            Case.status == 'active',
            Case.account_id == account_id
        ).all()
        active_invoice_numbers = {case_data.case_number for case_data in active_cases_data}
        active_initial_count = len(active_invoice_numbers)

        if not active_invoice_numbers:
            log.info(f"[update_existing_cases] Brak aktywnych spraw dla konta '{account.name}'.")
            duration = (datetime.utcnow() - start_time).total_seconds()
            return 0, 0, 0, 0, duration

        log.info(f"[update_existing_cases] Znaleziono {active_initial_count} aktywnych spraw.")
        remaining_active_numbers = active_invoice_numbers.copy()

    except Exception as e_query:
        log.error(f"[update_existing_cases] Blad podczas pobierania aktywnych spraw: {e_query}", exc_info=True)
        duration = (datetime.utcnow() - start_time).total_seconds()
        return 0, 0, 0, api_calls, duration

    today = date.today()
    start_date_str = (today - timedelta(days=35)).strftime('%Y-%m-%d')
    end_date_str = (today + timedelta(days=3)).strftime('%Y-%m-%d')
    log.info(f"[update_existing_cases] Skanowanie API dla faktur z terminem platnosci: {start_date_str} - {end_date_str}")

    while True:
        # Używamy znormalizowanych query_params - provider mapuje je na format API
        batch_invoices_api = provider.fetch_invoices(
            query_params={
                "payment_date_gteq": start_date_str,
                "payment_date_lteq": end_date_str
            },
            offset=offset,
            limit=limit_api
        )
        api_calls += 1

        if not batch_invoices_api:
            if offset == 0:
                log.info(f"[update_existing_cases] Brak faktur w podanym zakresie dat.")
            break

        log.info(f"[update_existing_cases] API zwrocilo {len(batch_invoices_api)} faktur (offset={offset}).")

        # Używamy znormalizowanego pola 'number' z providera
        invoice_numbers_in_batch = {inv.get('number') for inv in batch_invoices_api if inv.get('number')}
        numbers_to_process = active_invoice_numbers.intersection(invoice_numbers_in_batch)

        if numbers_to_process:
            log.debug(f"[update_existing_cases] Znaleziono {len(numbers_to_process)} pasujacych aktywnych spraw.")
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
                        if local_inv.status != new_status:
                            local_inv.status = new_status
                            data_changed = True

                        new_paid = inv_data_api.get('paid_price', local_inv.paid_price)
                        if local_inv.paid_price != new_paid:
                            local_inv.paid_price = new_paid
                            data_changed = True

                        new_gross = inv_data_api.get('gross_price', local_inv.gross_price)
                        if data_changed or local_inv.left_to_pay is None:
                            current_left = (new_gross or 0) - (new_paid or 0)
                            if local_inv.left_to_pay != current_left:
                                local_inv.left_to_pay = current_left
                                data_changed = True

                        # Provider już zwraca obiekty date - nie potrzebujemy parsowania
                        new_due_date = inv_data_api.get('payment_due_date')
                        if local_inv.payment_due_date != new_due_date:
                            local_inv.payment_due_date = new_due_date
                            data_changed = True

                        new_invoice_date = inv_data_api.get('invoice_date')
                        if local_inv.invoice_date != new_invoice_date:
                            local_inv.invoice_date = new_invoice_date
                            data_changed = True

                        new_paid_date = inv_data_api.get('paid_date')
                        if local_inv.left_to_pay <= 0 and not new_paid_date and not local_inv.paid_date:
                            new_paid_date = date.today()

                        if local_inv.paid_date != new_paid_date:
                            local_inv.paid_date = new_paid_date
                            data_changed = True

                        if data_changed:
                            processed_updates += 1
                            log.debug(f"[update_existing_cases] Aktualizacja danych platnosci dla {invoice_num_api}.")
                            db.session.add(local_inv)

                        if local_inv.left_to_pay <= 0 or local_inv.status == 'paid':
                            if case_obj.status == 'active':
                                case_obj.status = "closed_oplacone"
                                closed_cases_count += 1
                                db.session.add(case_obj)
                                log.info(f"[update_existing_cases] Zamknieto sprawe {invoice_num_api} jako oplacona.")
                        else:
                            if case_obj.status != 'active':
                                log.warning(f"[update_existing_cases] Sprawa {invoice_num_api} byla {case_obj.status}, ale faktura nieoplacona. Ustawiam na 'active'.")
                                case_obj.status = 'active'
                                db.session.add(case_obj)

                        db.session.commit()

                    except Exception as e_proc:
                        the_traceback = traceback.format_exc()
                        log.error(f"[update_existing_cases] Blad przetwarzania aktualizacji {invoice_num_api}: {e_proc}\n{the_traceback}")
                        db.session.rollback()

                    remaining_active_numbers.discard(invoice_num_api)

        if len(batch_invoices_api) == limit_api:
            offset += limit_api
        else:
            break

    duration = (datetime.utcnow() - start_time).total_seconds()
    active_after_update = active_initial_count - closed_cases_count

    if remaining_active_numbers:
        log.warning(f"[update_existing_cases] {len(remaining_active_numbers)} aktywnych spraw nie znaleziono w API.")

    log.info(f"[update_existing_cases] Zakonczono dla konta '{account.name}'. Zmodyfikowano: {processed_updates} faktur. Sprawy aktywne: {active_after_update}. Zamkniete: {closed_cases_count}. Czas: {duration:.2f}s. API calls: {api_calls}")

    return processed_updates, active_after_update, closed_cases_count, api_calls, duration


def run_full_sync(account_id):
    """
    Uruchamia pelna synchronizacje: nowe faktury + aktualizacja istniejacych.
    Zapisuje zbiorczy wynik w SyncStatus.

    Args:
        account_id (int): ID profilu/konta dla ktorego synchronizowac dane

    Returns:
        int: Liczba przetworzonych/zmienionych rekordow
    """
    # Account nie ma account_id - używamy sudo()
    with sudo():
        account = Account.query.get(account_id)
    if not account:
        log.error(f"[run_full_sync] Nie znaleziono konta o ID: {account_id}")
        return 0

    if not account.is_active:
        log.warning(f"[run_full_sync] Konto '{account.name}' (ID: {account_id}) jest nieaktywne.")
        return 0

    log.info(f"[run_full_sync] Start pelnej synchronizacji dla konta '{account.name}' (ID: {account_id})...")
    start_time = datetime.utcnow()
    total_processed_new, total_new_cases, total_api_new, new_duration = 0, 0, 0, 0.0
    total_processed_updates, total_active_after, total_closed_update, total_api_update, update_duration = 0, 0, 0, 0, 0.0

    try:
        total_processed_new, total_new_cases, total_api_new, new_duration = sync_new_invoices(account_id)
    except Exception as e_new:
        log.critical(f"[run_full_sync] Krytyczny blad w sync_new_invoices dla konta '{account.name}': {e_new}", exc_info=True)

    try:
        total_processed_updates, total_active_after, total_closed_update, total_api_update, update_duration = update_existing_cases(account_id)
    except Exception as e_update:
        log.critical(f"[run_full_sync] Krytyczny blad w update_existing_cases dla konta '{account.name}': {e_update}", exc_info=True)

    total_processed_records = total_processed_new + total_processed_updates
    total_api_calls = total_api_new + total_api_update
    duration = (datetime.utcnow() - start_time).total_seconds()

    try:
        sync_record = SyncStatus(
            account_id=account_id,
            sync_type="full",
            processed=total_processed_records,
            duration=duration,
            new_cases=total_new_cases,
            updated_cases=total_active_after,
            closed_cases=total_closed_update,
            api_calls=total_api_calls,
            new_invoices_processed=total_processed_new,
            updated_invoices_processed=total_processed_updates,
            new_sync_duration=new_duration,
            update_sync_duration=update_duration
        )
        db.session.add(sync_record)
        db.session.commit()
        log.info(f"[run_full_sync] Zapisano status synchronizacji (1 rekord 'full')")
    except Exception as db_err:
        log.error(f"[run_full_sync] Blad zapisu statusu pelnej synchronizacji: {db_err}", exc_info=True)
        db.session.rollback()

    log.info(f"[run_full_sync] Zakonczono pelna synchronizacje dla konta '{account.name}' (ID: {account_id}) w {duration:.2f}s.")
    log.info(f"  Nowe: {total_processed_new} faktur, {total_new_cases} spraw (API: {total_api_new}, czas: {new_duration:.2f}s)")
    log.info(f"  Aktualizacje: {total_processed_updates} faktur, {total_active_after} aktywnych, {total_closed_update} zamknietych (API: {total_api_update}, czas: {update_duration:.2f}s)")
    log.info(f"  Lacznie: {total_processed_records}. API: {total_api_calls}")

    return total_processed_records
