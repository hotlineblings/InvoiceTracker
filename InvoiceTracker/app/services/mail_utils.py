# mail_utils.py
from datetime import timedelta
from .mail_templates import MAIL_TEMPLATES


def generate_email(stage, invoice, account):
    """
    Funkcja generujaca temat i tresc e-maila (HTML) dla danego etapu 'stage', faktury 'invoice' i konta 'account'.

    Args:
        stage: Nazwa etapu (np. "Przypomnienie o zblizajacym sie terminie platnosci")
        invoice: Obiekt Invoice
        account: Obiekt Account (do przyszlego uzycia dla danych firmowych per konto)

    Returns:
        tuple: (subject, body_html)
    """
    stage_keys_map = {
        "Przypomnienie o zbliżającym się terminie płatności": "stage_1",
        "Powiadomienie o upływie terminu płatności": "stage_2",
        "Wezwanie do zapłaty": "stage_3",
        "Powiadomienie o zamiarze skierowania sprawy do windykatora zewnętrznego i publikacji na giełdzie wierzytelności": "stage_4",
        "Przekazanie sprawy do windykatora zewnętrznego": "stage_5",
    }

    # Jesli dostajemy np. "stage_2" to bierzemy od razu key=stage_2,
    # w innym przypadku mapujemy pelny tekst etapu na "stage_1"... "stage_5"
    template_key = stage if stage.startswith("stage_") else stage_keys_map.get(stage, None)

    if not template_key:
        return ("", "")

    template = MAIL_TEMPLATES.get(template_key)
    if not template:
        return ("", "")

    due_date_str = invoice.payment_due_date.strftime("%Y-%m-%d") if invoice.payment_due_date else "Brak"
    debt_amount = f"{invoice.gross_price / 100:.2f}"

    street_address = invoice.client_address or ""
    # Domyslne wartosci w razie braku
    client_city = getattr(invoice, 'client_city', "") or ""
    client_zip = getattr(invoice, 'client_zip', "") or ""

    subject = template["subject"].format(case_number=invoice.invoice_number)

    if invoice.payment_due_date:
        stage_3_date = (invoice.payment_due_date + timedelta(days=7)).strftime("%Y-%m-%d")
        stage_4_date = (invoice.payment_due_date + timedelta(days=14)).strftime("%Y-%m-%d")
        stage_5_date = (invoice.payment_due_date + timedelta(days=21)).strftime("%Y-%m-%d")
    else:
        stage_3_date = stage_4_date = stage_5_date = "Brak"

    # Dane wierzyciela z Account (dynamiczne per profil)
    creditor_name = account.company_full_name or "FIRMA"
    creditor_phone = account.company_phone or "XXX XXX XXX"
    creditor_email = account.company_email_contact or account.email_from
    creditor_bank = account.company_bank_account or "BRAK RACHUNKU"

    body_html = template["body_html"].format(
        # Dane klienta (dluznika) z faktury
        company_name=invoice.client_company_name or "",
        due_date=due_date_str,
        case_number=invoice.invoice_number,
        street_address=street_address,
        postal_code=client_zip,
        city=client_city,
        nip=invoice.client_nip or "",
        debt_amount=debt_amount,
        stage_3_date=stage_3_date,
        stage_4_date=stage_4_date,
        stage_5_date=stage_5_date,
        # Dane wierzyciela z Account
        creditor_name=creditor_name,
        creditor_phone=creditor_phone,
        creditor_email=creditor_email,
        creditor_bank_account=creditor_bank
    )
    return subject, body_html
