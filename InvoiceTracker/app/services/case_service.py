"""
Serwis spraw windykacyjnych.
Logika pobierania, przetwarzania i listowania spraw.

SQL Performance Optimization:
- Filtering (search) wykonywane na poziomie SQL (ILIKE)
- Sortowanie wykonywane na poziomie SQL (ORDER BY)
- Paginacja wykonywane na poziomie SQL (.paginate())
- NotificationLogs pobierane TYLKO dla wyswietlanej strony
- Wyjatek: sortowanie po progress_percent - wykonywane w pamieci
"""
import logging
from datetime import date

from sqlalchemy import func, or_

from ..extensions import db
from ..models import Case, Invoice, NotificationLog
from ..constants import STAGE_MAPPING_PROGRESS
from .finance_service import grosz_to_pln, calculate_left_to_pay

log = logging.getLogger(__name__)


# =============================================================================
# MAPOWANIE SORTOWANIA SQL
# =============================================================================

# Mapowanie nazw kolumn UI na kolumny SQLAlchemy
SORT_COLUMN_MAP_ACTIVE = {
    'case_number': Case.case_number,
    'client_id': Case.client_id,
    'client_company_name': Case.client_company_name,
    'client_nip': Invoice.client_nip,
    'client_email': Invoice.client_email,
    'total_debt': Invoice.left_to_pay,
    'days_diff': Invoice.payment_due_date,
}


# =============================================================================
# HELPERY WEWNETRZNE
# =============================================================================

def _stage_from_log_text(text):
    """
    Wyciaga numer etapu z tekstu logu powiadomienia.

    Args:
        text: Tekst stage z NotificationLog (np. "Wezwanie do zaplaty (Manualne)")

    Returns:
        int: Numer etapu (1-5) lub 0 jesli nie rozpoznano
    """
    stage_key = str(text).split(" (")[0]
    return STAGE_MAPPING_PROGRESS.get(stage_key, 0)


def _calculate_max_stage(logs):
    """
    Oblicza maksymalny etap z listy logow powiadomien.

    Args:
        logs: Lista obiektow NotificationLog

    Returns:
        int: Maksymalny numer etapu (0-5)
    """
    max_stage = 0
    for lg in logs:
        st = _stage_from_log_text(lg.stage)
        max_stage = max(max_stage, st)
    return max_stage


def _calculate_progress_percent(max_stage):
    """
    Konwertuje numer etapu na procent postepu.

    Args:
        max_stage: Numer etapu (0-5)

    Returns:
        int: Procent postepu (0-100)
    """
    return int((max_stage / 5) * 100)


def _group_logs_by_invoice(logs):
    """
    Grupuje logi powiadomien po numerze faktury.

    Args:
        logs: Lista obiektow NotificationLog

    Returns:
        dict: {invoice_number: [NotificationLog, ...]}
    """
    logs_by_invoice = {}
    for log_entry in logs:
        if log_entry.invoice_number not in logs_by_invoice:
            logs_by_invoice[log_entry.invoice_number] = []
        logs_by_invoice[log_entry.invoice_number].append(log_entry)
    return logs_by_invoice


def _build_active_case_item(case_obj, invoice, logs_for_invoice):
    """
    Buduje slownik reprezentujacy aktywna sprawe do wyswietlenia.

    Args:
        case_obj: Obiekt Case
        invoice: Obiekt Invoice
        logs_for_invoice: Lista NotificationLog dla tej faktury

    Returns:
        dict: Dane sprawy gotowe do szablonu
    """
    left = calculate_left_to_pay(invoice.gross_price, invoice.paid_price)
    if invoice.left_to_pay is not None:
        left = invoice.left_to_pay

    day_diff = None
    if invoice.payment_due_date:
        day_diff = (date.today() - invoice.payment_due_date).days

    max_stage = _calculate_max_stage(logs_for_invoice)
    progress_val = _calculate_progress_percent(max_stage)

    return {
        'case_number': case_obj.case_number,
        'client_id': case_obj.client_id,
        'client_company_name': case_obj.client_company_name,
        'client_nip': invoice.client_nip,
        'client_email': invoice.client_email if invoice.client_email else "Brak",
        'total_debt': grosz_to_pln(left),
        'days_diff': day_diff,
        'progress_percent': progress_val,
        'status': case_obj.status
    }


def _build_completed_case_item(case_obj, invoice, logs_for_invoice):
    """
    Buduje slownik reprezentujacy zakonczona sprawe do wyswietlenia.

    Args:
        case_obj: Obiekt Case
        invoice: Obiekt Invoice
        logs_for_invoice: Lista NotificationLog dla tej faktury

    Returns:
        dict: Dane sprawy gotowe do szablonu
    """
    left = calculate_left_to_pay(invoice.gross_price, invoice.paid_price)
    if invoice.left_to_pay is not None:
        left = invoice.left_to_pay

    day_diff = None
    if invoice.payment_due_date:
        day_diff = (date.today() - invoice.payment_due_date).days

    max_stage = _calculate_max_stage(logs_for_invoice)
    progress_val = _calculate_progress_percent(max_stage)

    payment_info = {
        'paid_date': invoice.paid_date.strftime('%Y-%m-%d') if invoice.paid_date else None,
        'paid_amount': grosz_to_pln(invoice.paid_price),
        'total_amount': grosz_to_pln(invoice.gross_price),
        'payment_method': invoice.payment_method or "N/A"
    }

    return {
        'case_number': case_obj.case_number,
        'client_id': case_obj.client_id,
        'client_company_name': case_obj.client_company_name,
        'client_nip': invoice.client_nip,
        'client_email': invoice.client_email if invoice.client_email else "Brak",
        'total_debt': grosz_to_pln(left),
        'days_diff': day_diff,
        'progress_percent': progress_val,
        'status': case_obj.status,
        'payment_info': payment_info,
        'invoice_date': invoice.invoice_date.strftime('%Y-%m-%d') if invoice.invoice_date else None,
        'payment_due_date': invoice.payment_due_date.strftime('%Y-%m-%d') if invoice.payment_due_date else None
    }


def _build_client_case_item(case_obj, invoice, account_id):
    """
    Buduje slownik reprezentujacy sprawe klienta.

    Args:
        case_obj: Obiekt Case
        invoice: Obiekt Invoice
        account_id: ID konta

    Returns:
        dict lub None: Dane sprawy gotowe do szablonu
    """
    if not invoice:
        return None

    left = calculate_left_to_pay(invoice.gross_price, invoice.paid_price)
    if invoice.left_to_pay is not None:
        left = invoice.left_to_pay

    day_diff = None
    if invoice.payment_due_date:
        day_diff = (date.today() - invoice.payment_due_date).days

    try:
        logs = NotificationLog.query.filter_by(
            invoice_number=invoice.invoice_number,
            account_id=account_id
        ).all()
    except Exception:
        logs = []

    max_stage = _calculate_max_stage(logs)
    progress_val = _calculate_progress_percent(max_stage)
    effective_email = invoice.get_effective_email() if invoice else "Brak"

    return {
        'case_number': case_obj.case_number,
        'client_id': case_obj.client_id,
        'client_company_name': case_obj.client_company_name,
        'client_nip': invoice.client_nip,
        'client_email': effective_email,
        'invoice_id': invoice.id,
        'override_email': invoice.override_email,
        'api_email': invoice.client_email,
        'total_debt': grosz_to_pln(left),
        'days_diff': day_diff,
        'progress_percent': progress_val,
        'status': case_obj.status
    }


# =============================================================================
# GLOWNE FUNKCJE SERWISU
# =============================================================================

def get_active_cases_for_account(account_id, search_query="", sort_by="case_number",
                                  sort_order="asc", page=1, per_page=100):
    """
    Pobiera liste aktywnych spraw dla konta.

    SQL Performance Optimization:
    - Stats (total_debt, active_count) - osobne zapytanie agregujace dla WSZYSTKICH aktywnych
    - Search - SQL ILIKE na wielu kolumnach
    - Sort - SQL ORDER BY (wyjatek: progress_percent w pamieci)
    - Pagination - SQL .paginate()
    - NotificationLogs - pobierane TYLKO dla wyswietlanej strony

    Args:
        account_id: ID konta
        search_query: Zapytanie wyszukiwania (juz w lowercase)
        sort_by: Kolumna sortowania
        sort_order: "asc" lub "desc"
        page: Numer strony
        per_page: Ilosc na strone

    Returns:
        dict: Dane gotowe do render_template
    """
    # =========================================================================
    # KROK 1: Stats dla WSZYSTKICH aktywnych spraw (bez filtra search)
    # =========================================================================
    stats_query = (
        db.session.query(
            func.count(Case.id).label('total_count'),
            func.coalesce(func.sum(Invoice.left_to_pay), 0).label('total_debt')
        )
        .join(Invoice, Case.id == Invoice.case_id)
        .filter(Case.account_id == account_id, Case.status == 'active')
    )
    stats = stats_query.first()
    all_active_count = stats.total_count or 0
    total_debt_cents = stats.total_debt or 0

    log.info(f"[case_service] Stats: {all_active_count} aktywnych, {total_debt_cents} gr dlugu")

    # =========================================================================
    # KROK 2: Bazowe zapytanie z JOIN
    # =========================================================================
    query = (
        db.session.query(Case, Invoice)
        .join(Invoice, Case.id == Invoice.case_id)
        .filter(Case.account_id == account_id, Case.status == 'active')
    )

    # =========================================================================
    # KROK 3: Filtr wyszukiwania (SQL ILIKE)
    # =========================================================================
    if search_query:
        search_pattern = f"%{search_query}%"
        query = query.filter(
            or_(
                Case.case_number.ilike(search_pattern),
                Case.client_company_name.ilike(search_pattern),
                Case.client_id.ilike(search_pattern),
                Invoice.client_nip.ilike(search_pattern),
                Invoice.client_email.ilike(search_pattern),
            )
        )

    # =========================================================================
    # KROK 4: Sortowanie (SQL ORDER BY)
    # =========================================================================
    sort_in_memory = (sort_by == 'progress_percent')

    if not sort_in_memory and sort_by in SORT_COLUMN_MAP_ACTIVE:
        column = SORT_COLUMN_MAP_ACTIVE[sort_by]
        if sort_order == 'desc':
            query = query.order_by(column.desc().nullslast())
        else:
            query = query.order_by(column.asc().nullsfirst())
    else:
        # Default sort (takze dla progress_percent przed pobraniem)
        query = query.order_by(Case.case_number.asc())

    # =========================================================================
    # KROK 5: Paginacja
    # =========================================================================
    if sort_in_memory:
        # progress_percent wymaga pobrania wszystkich i sortowania w pamieci
        all_results = query.all()
        filtered_count = len(all_results)
        total_pages = (filtered_count + per_page - 1) // per_page if per_page > 0 else 1

        # Pobierz logi dla WSZYSTKICH przefiltrowanych
        all_invoice_numbers = [inv.invoice_number for _, inv in all_results if inv]
        all_logs = []
        if all_invoice_numbers:
            all_logs = NotificationLog.query.filter(
                NotificationLog.invoice_number.in_(all_invoice_numbers),
                NotificationLog.account_id == account_id
            ).all()
        logs_by_invoice = _group_logs_by_invoice(all_logs)

        # Buduj WSZYSTKIE case_items
        all_cases = []
        for case_obj, inv in all_results:
            if not inv:
                continue
            logs_for_invoice = logs_by_invoice.get(inv.invoice_number, [])
            case_item = _build_active_case_item(case_obj, inv, logs_for_invoice)
            all_cases.append(case_item)

        # Sortuj w pamieci po progress_percent
        all_cases.sort(
            key=lambda x: x.get('progress_percent', 0),
            reverse=(sort_order == 'desc')
        )

        # Paginuj w pamieci
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        cases_list = all_cases[start_idx:end_idx]

        log.info(f"[case_service] Sort in-memory (progress): {filtered_count} spraw")

    else:
        # Standardowa sciezka - SQL pagination
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        page_results = pagination.items
        filtered_count = pagination.total
        total_pages = pagination.pages

        # =====================================================================
        # KROK 6: Pobierz NotificationLogs TYLKO dla wyswietlanej strony
        # =====================================================================
        invoice_numbers = [inv.invoice_number for _, inv in page_results if inv]
        logs_for_page = []
        if invoice_numbers:
            logs_for_page = NotificationLog.query.filter(
                NotificationLog.invoice_number.in_(invoice_numbers),
                NotificationLog.account_id == account_id
            ).all()
        logs_by_invoice = _group_logs_by_invoice(logs_for_page)

        # =====================================================================
        # KROK 7: Buduj case_items tylko dla strony
        # =====================================================================
        cases_list = []
        for case_obj, inv in page_results:
            if not inv:
                continue
            logs_for_invoice = logs_by_invoice.get(inv.invoice_number, [])
            case_item = _build_active_case_item(case_obj, inv, logs_for_invoice)
            cases_list.append(case_item)

        log.info(f"[case_service] SQL pagination: strona {page}/{total_pages}, {len(cases_list)} spraw")

    return {
        'cases': cases_list,
        'search_query': search_query,
        'sort_by': sort_by,
        'sort_order': sort_order,
        'total_debt_all': grosz_to_pln(total_debt_cents),
        'active_count': all_active_count,  # Zawsze ALL active (nie filtered)
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages,
        'total_count': filtered_count  # Filtered count (dla paginacji)
    }


def get_completed_cases_for_account(account_id, search_query="", sort_by="case_number",
                                     sort_order="asc", page=1, per_page=100, show_unpaid=False):
    """
    Pobiera liste zakonczonych spraw dla konta.

    SQL Performance Optimization:
    - Search - SQL ILIKE na wielu kolumnach
    - Sort - SQL ORDER BY (wyjatek: progress_percent w pamieci)
    - Pagination - SQL .paginate()
    - NotificationLogs - pobierane TYLKO dla wyswietlanej strony
    - stage_counts - obliczane dla calej strony (kompromis wydajnosciowy)

    Args:
        account_id: ID konta
        search_query: Zapytanie wyszukiwania (juz w lowercase)
        sort_by: Kolumna sortowania
        sort_order: "asc" lub "desc"
        page: Numer strony
        per_page: Ilosc na strone
        show_unpaid: Czy pokazywac tylko nieoplacone

    Returns:
        dict: Dane gotowe do render_template
    """
    # =========================================================================
    # KROK 1: Bazowe zapytanie z JOIN
    # =========================================================================
    query = (
        db.session.query(Case, Invoice)
        .join(Invoice, Case.id == Invoice.case_id)
        .filter(Case.account_id == account_id, Case.status != 'active')
    )

    # Filtr show_unpaid
    if show_unpaid:
        query = query.filter(Case.status == 'closed_nieoplacone')

    # =========================================================================
    # KROK 2: Filtr wyszukiwania (SQL ILIKE)
    # =========================================================================
    if search_query:
        search_pattern = f"%{search_query}%"
        query = query.filter(
            or_(
                Case.case_number.ilike(search_pattern),
                Case.client_company_name.ilike(search_pattern),
                Case.client_id.ilike(search_pattern),
                Invoice.client_nip.ilike(search_pattern),
                Invoice.client_email.ilike(search_pattern),
            )
        )

    # =========================================================================
    # KROK 3: Sortowanie (SQL ORDER BY)
    # =========================================================================
    sort_in_memory = (sort_by == 'progress_percent')

    if not sort_in_memory and sort_by in SORT_COLUMN_MAP_ACTIVE:
        column = SORT_COLUMN_MAP_ACTIVE[sort_by]
        if sort_order == 'desc':
            query = query.order_by(column.desc().nullslast())
        else:
            query = query.order_by(column.asc().nullsfirst())
    else:
        # Default sort - po dacie aktualizacji (najnowsze najpierw)
        query = query.order_by(Case.updated_at.desc())

    # =========================================================================
    # KROK 4: Paginacja
    # =========================================================================
    if sort_in_memory:
        # progress_percent wymaga pobrania wszystkich i sortowania w pamieci
        all_results = query.all()
        filtered_count = len(all_results)
        total_pages = (filtered_count + per_page - 1) // per_page if per_page > 0 else 1

        # Pobierz logi dla WSZYSTKICH przefiltrowanych
        all_invoice_numbers = [inv.invoice_number for _, inv in all_results if inv]
        all_logs = []
        if all_invoice_numbers:
            all_logs = NotificationLog.query.filter(
                NotificationLog.invoice_number.in_(all_invoice_numbers),
                NotificationLog.account_id == account_id
            ).all()
        logs_by_invoice = _group_logs_by_invoice(all_logs)

        # Buduj WSZYSTKIE case_items i zliczaj etapy
        all_cases = []
        stage_counts = {i: 0 for i in range(1, 6)}

        for case_obj, inv in all_results:
            if not inv:
                continue
            logs_for_invoice = logs_by_invoice.get(inv.invoice_number, [])
            case_item = _build_completed_case_item(case_obj, inv, logs_for_invoice)
            all_cases.append(case_item)

            # Zliczanie etapow
            max_stage = _calculate_max_stage(logs_for_invoice)
            stage_num = max(1, min(int(max_stage), 5))
            if stage_num > 0:
                stage_counts[stage_num] += 1

        # Sortuj w pamieci po progress_percent
        all_cases.sort(
            key=lambda x: x.get('progress_percent', 0),
            reverse=(sort_order == 'desc')
        )

        # Paginuj w pamieci
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        cases_list = all_cases[start_idx:end_idx]

        log.info(f"[case_service] Completed sort in-memory (progress): {filtered_count} spraw")

    else:
        # Standardowa sciezka - SQL pagination
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        page_results = pagination.items
        filtered_count = pagination.total
        total_pages = pagination.pages

        # =====================================================================
        # KROK 5: Pobierz NotificationLogs TYLKO dla wyswietlanej strony
        # =====================================================================
        invoice_numbers = [inv.invoice_number for _, inv in page_results if inv]
        logs_for_page = []
        if invoice_numbers:
            logs_for_page = NotificationLog.query.filter(
                NotificationLog.invoice_number.in_(invoice_numbers),
                NotificationLog.account_id == account_id
            ).all()
        logs_by_invoice = _group_logs_by_invoice(logs_for_page)

        # =====================================================================
        # KROK 6: Buduj case_items i zliczaj etapy (tylko dla strony)
        # =====================================================================
        cases_list = []
        stage_counts = {i: 0 for i in range(1, 6)}

        for case_obj, inv in page_results:
            if not inv:
                continue
            logs_for_invoice = logs_by_invoice.get(inv.invoice_number, [])
            case_item = _build_completed_case_item(case_obj, inv, logs_for_invoice)
            cases_list.append(case_item)

            # Zliczanie etapow (dla tej strony)
            max_stage = _calculate_max_stage(logs_for_invoice)
            stage_num = max(1, min(int(max_stage), 5))
            if stage_num > 0:
                stage_counts[stage_num] += 1

        log.info(f"[case_service] Completed SQL pagination: strona {page}/{total_pages}, {len(cases_list)} spraw")

    return {
        'cases': cases_list,
        'search_query': search_query,
        'sort_by': sort_by,
        'sort_order': sort_order,
        'completed_count': filtered_count,
        'stage_counts': stage_counts,
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages,
        'total_count': filtered_count,
        'show_unpaid_filter': show_unpaid
    }


def get_case_detail(account_id, case_number):
    """
    Pobiera szczegoly sprawy.

    Args:
        account_id: ID konta
        case_number: Numer sprawy

    Returns:
        dict: Dane gotowe do render_template

    Raises:
        404: Jesli sprawa nie zostala znaleziona
    """
    case_obj = Case.query.filter_by(
        case_number=case_number,
        account_id=account_id
    ).first_or_404()

    # Invoice ma teraz bezpośredni account_id - bezpieczne query
    inv = Invoice.query.filter_by(invoice_number=case_number, account_id=account_id).first_or_404()

    # Dowiaz fakture do sprawy jesli brak
    if not inv.case_id:
        inv.case_id = case_obj.id
        db.session.add(inv)
        db.session.commit()
        log.info(f"Dowiazano fakture {inv.invoice_number} do sprawy {case_obj.id}")

    left = calculate_left_to_pay(inv.gross_price, inv.paid_price)
    if inv.left_to_pay is not None:
        left = inv.left_to_pay

    day_diff = None
    if inv.payment_due_date:
        day_diff = (date.today() - inv.payment_due_date).days

    logs = NotificationLog.query.filter_by(
        invoice_number=inv.invoice_number,
        account_id=account_id
    ).order_by(NotificationLog.sent_at.desc()).all()

    modified_logs = []
    max_stage_num = 0
    for lg in logs:
        st = _stage_from_log_text(lg.stage)
        max_stage_num = max(max_stage_num, st)
        modified_logs.append({
            "id": lg.id,
            "sent_at": lg.sent_at,
            "stage": f"{lg.stage} ({lg.mode})",
            "subject": lg.subject,
            "body": lg.body
        })

    progress_val = _calculate_progress_percent(max_stage_num)

    return {
        'case': case_obj,
        'invoice': inv,
        'left_to_pay': left,
        'days_display': day_diff,
        'progress_percent': progress_val,
        'notifications': modified_logs
    }


def get_client_cases(account_id, client_id):
    """
    Pobiera sprawy dla konkretnego klienta.

    Args:
        account_id: ID konta
        client_id: ID klienta

    Returns:
        dict: Dane gotowe do render_template
    """
    current_date = date.today()

    # Pobierz najnowsza fakture dla danych klienta
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
        first_case = Case.query.filter_by(
            client_id=client_id,
            account_id=account_id
        ).first()
        if first_case:
            client_details = {
                'client_company_name': first_case.client_company_name,
                'client_nip': first_case.client_nip
            }

    # Pobierz wszystkie sprawy klienta
    all_cases_for_client = (
        db.session.query(Case, Invoice)
        .outerjoin(Invoice, Case.id == Invoice.case_id)
        .filter(Case.client_id == client_id)
        .filter(Case.account_id == account_id)
        .order_by(Case.status.asc(), Invoice.invoice_date.desc())
        .all()
    )

    active_cases_list = []
    completed_cases_list = []
    total_debt_all_cents = 0

    for case_obj, inv in all_cases_for_client:
        case_item = _build_client_case_item(case_obj, inv, account_id)
        if case_item:
            if case_obj.status == 'active':
                total_debt_all_cents += int(case_item['total_debt'] * 100)
                active_cases_list.append(case_item)
            else:
                completed_cases_list.append(case_item)

    active_count = len(active_cases_list)
    total_debt_all = grosz_to_pln(total_debt_all_cents)

    active_cases_list.sort(key=lambda x: x['case_number'], reverse=True)
    completed_cases_list.sort(key=lambda x: x['case_number'], reverse=True)

    return {
        'active_cases': active_cases_list,
        'completed_cases': completed_cases_list,
        'client_id': client_id,
        'client_details': client_details,
        'total_debt_all': total_debt_all,
        'active_count': active_count,
        'current_date': current_date
    }
