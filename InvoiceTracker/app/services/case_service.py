"""
Serwis spraw windykacyjnych.
Logika pobierania, przetwarzania i listowania spraw.
"""
import logging
from datetime import date

from sqlalchemy.orm import joinedload

from ..extensions import db
from ..models import Case, Invoice, NotificationLog
from ..constants import STAGE_MAPPING_PROGRESS
from .finance_service import grosz_to_pln, calculate_left_to_pay

log = logging.getLogger(__name__)


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


# TODO: Move filtering to SQL layer (Etap 2 - Bezpieczenstwo/Wydajnosc)
def _filter_cases(cases_list, search_query):
    """
    Filtruje liste spraw po zapytaniu wyszukiwania.

    Args:
        cases_list: Lista slownikow spraw
        search_query: Zapytanie wyszukiwania (lowercase)

    Returns:
        list: Przefiltrowana lista spraw
    """
    if not search_query:
        return cases_list

    return [
        c for c in cases_list
        if search_query in (c.get('client_id') or '').lower()
        or search_query in (str(c.get('client_nip') or '')).lower()
        or search_query in (c.get('client_company_name') or '').lower()
        or search_query in (c.get('case_number') or '').lower()
        or search_query in (c.get('client_email') or '').lower()
    ]


# TODO: Move filtering to SQL layer (Etap 2 - Bezpieczenstwo/Wydajnosc)
def _sort_cases(cases_list, sort_by, sort_order):
    """
    Sortuje liste spraw po podanej kolumnie.

    Args:
        cases_list: Lista slownikow spraw
        sort_by: Nazwa kolumny do sortowania
        sort_order: "asc" lub "desc"

    Returns:
        list: Posortowana lista spraw
    """
    if not cases_list:
        return cases_list

    try:
        key_func = lambda x: x.get(sort_by, 0)

        if sort_by == 'days_diff':
            key_func = lambda x: (
                x.get(sort_by, -float('inf'))
                if x.get(sort_by) is not None
                else -float('inf')
            )
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
        log.error(f"Sortowanie error: {e}", exc_info=True)

    return cases_list


def _paginate(items, page, per_page):
    """
    Paginuje liste elementow.

    Args:
        items: Lista elementow
        page: Numer strony (1-based)
        per_page: Ilosc na strone

    Returns:
        tuple: (paginated_items, total_count, total_pages)
    """
    total_count = len(items)
    total_pages = (total_count + per_page - 1) // per_page if per_page > 0 else 1
    start_idx = (page - 1) * per_page
    end_idx = min(start_idx + per_page, total_count)
    paginated_items = items[start_idx:end_idx]
    return paginated_items, total_count, total_pages


# =============================================================================
# GLOWNE FUNKCJE SERWISU
# =============================================================================

def get_active_cases_for_account(account_id, search_query="", sort_by="case_number",
                                  sort_order="asc", page=1, per_page=100):
    """
    Pobiera liste aktywnych spraw dla konta.

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
    # Pobierz Case z Invoice w jednym zapytaniu (JOIN)
    cases_with_invoices = (
        Case.query
        .options(joinedload(Case.invoice))
        .filter_by(status="active", account_id=account_id)
        .all()
    )

    log.info(f"[case_service] Pobrano {len(cases_with_invoices)} spraw aktywnych")

    # Zbierz invoice_numbers
    invoice_numbers = [
        case.invoice.invoice_number
        for case in cases_with_invoices
        if case.invoice
    ]

    # Pobierz wszystkie NotificationLog w jednym zapytaniu
    all_logs = []
    if invoice_numbers:
        all_logs = NotificationLog.query.filter(
            NotificationLog.invoice_number.in_(invoice_numbers),
            NotificationLog.account_id == account_id
        ).all()

    # Grupuj logi po invoice_number
    logs_by_invoice = _group_logs_by_invoice(all_logs)

    log.info(f"[case_service] Pobrano {len(all_logs)} logow powiadomien")

    # Przetwarzanie danych
    cases_list = []
    total_debt_all_cents = 0

    for case_obj in cases_with_invoices:
        inv = case_obj.invoice
        if not inv:
            continue

        logs_for_invoice = logs_by_invoice.get(inv.invoice_number, [])
        case_item = _build_active_case_item(case_obj, inv, logs_for_invoice)
        cases_list.append(case_item)

        # Sumowanie dlugu (konwertujemy z powrotem do groszy dla precyzji)
        left = calculate_left_to_pay(inv.gross_price, inv.paid_price)
        if inv.left_to_pay is not None:
            left = inv.left_to_pay
        total_debt_all_cents += left if left else 0

    # Filtrowanie
    cases_list = _filter_cases(cases_list, search_query)

    # Sortowanie
    cases_list = _sort_cases(cases_list, sort_by, sort_order)

    # Paginacja
    paginated_cases, total_count, total_pages = _paginate(cases_list, page, per_page)

    return {
        'cases': paginated_cases,
        'search_query': search_query,
        'sort_by': sort_by,
        'sort_order': sort_order,
        'total_debt_all': grosz_to_pln(total_debt_all_cents),
        'active_count': total_count,
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages,
        'total_count': total_count
    }


def get_completed_cases_for_account(account_id, search_query="", sort_by="case_number",
                                     sort_order="asc", page=1, per_page=100, show_unpaid=False):
    """
    Pobiera liste zakonczonych spraw dla konta.

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
    # Pobierz Case z Invoice w jednym zapytaniu
    cases_with_invoices = (
        Case.query
        .options(joinedload(Case.invoice))
        .filter(Case.status != "active")
        .filter_by(account_id=account_id)
        .order_by(Case.updated_at.desc())
        .all()
    )

    log.info(f"[case_service] Pobrano {len(cases_with_invoices)} spraw zakonczonych")

    # Zbierz invoice_numbers
    invoice_numbers = [
        case.invoice.invoice_number
        for case in cases_with_invoices
        if case.invoice
    ]

    # Pobierz logi
    all_logs = []
    if invoice_numbers:
        all_logs = NotificationLog.query.filter(
            NotificationLog.invoice_number.in_(invoice_numbers),
            NotificationLog.account_id == account_id
        ).all()

    logs_by_invoice = _group_logs_by_invoice(all_logs)

    # Przetwarzanie danych
    cases_list = []
    stage_counts = {i: 0 for i in range(1, 6)}

    for case_obj in cases_with_invoices:
        inv = case_obj.invoice
        if not inv:
            continue

        logs_for_invoice = logs_by_invoice.get(inv.invoice_number, [])
        case_item = _build_completed_case_item(case_obj, inv, logs_for_invoice)
        cases_list.append(case_item)

        # Zliczanie etapow
        max_stage = _calculate_max_stage(logs_for_invoice)
        stage_num = max(1, min(int(max_stage), 5))
        if stage_num > 0:
            stage_counts[stage_num] += 1

    # Filtrowanie
    cases_list = _filter_cases(cases_list, search_query)

    # Filtr nieoplaconych
    if show_unpaid:
        cases_list = [c for c in cases_list if c.get('status') == 'closed_nieoplacone']

    # Sortowanie
    cases_list = _sort_cases(cases_list, sort_by, sort_order)

    # Paginacja
    paginated_cases, total_count, total_pages = _paginate(cases_list, page, per_page)

    return {
        'cases': paginated_cases,
        'search_query': search_query,
        'sort_by': sort_by,
        'sort_order': sort_order,
        'completed_count': total_count,
        'stage_counts': stage_counts,
        'page': page,
        'per_page': per_page,
        'total_pages': total_pages,
        'total_count': total_count,
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

    inv = (
        Invoice.query.filter_by(case_id=case_obj.id).first()
        or Invoice.query.filter_by(invoice_number=case_number).first_or_404()
    )

    # Dowiaz fakture do sprawy jesli brak
    if inv and not inv.case_id:
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
