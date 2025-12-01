# mail_templates.py

MAIL_TEMPLATES = {
    "stage_1": {
        "subject": "Przypomnienie o zblizajacym sie terminie platnosci dla {case_number}",
        "body_html": """<p><strong>{company_name},</strong><br><br>
Informujemy, iz z dniem <strong>{due_date}</strong> mija termin zaplaty dla faktury <strong>{case_number}</strong>.
Prosimy o terminowe uregulowanie platnosci wobec <strong>{creditor_name}</strong>.<br><br>
W przypadku kiedy naleznosc zostala oplacona, prosze o zignorowanie ponizszej wiadomosci.</p>

<p><strong>Specyfikacja naleznosci:</strong><br>
<strong>{company_name}</strong><br>
<strong>{street_address}</strong><br>
<strong>{postal_code}</strong>, <strong>{city}</strong>
<strong>NIP: {nip}</strong><br>
Nr sprawy: <strong>{case_number}</strong><br>
Kwota zadluzenia: <strong>{debt_amount} zl</strong><br>
Rachunek do splaty: {creditor_bank_account}</p>

<p><strong>Kontakt do wierzyciela w celu wyjasnienia sprawy:</strong><br>
Telefon: {creditor_phone}<br>
E-mail: {creditor_email}</p>
"""
    },

    "stage_2": {
        "subject": "Przypomnienie o uplywie terminu platnosci dla {case_number}",
        "body_html": """<p><strong>{company_name},</strong><br><br>
Informujemy, iz z dniem <strong>{due_date}</strong> minal termin platnosci dla faktury <strong>{case_number}</strong>.
Prosimy o jak najszybsze uregulowanie naleznosci wobec <strong>{creditor_name}</strong>.<br><br>
W przypadku kiedy naleznosc zostala oplacona, prosze o zignorowanie ponizszej wiadomosci.</p>

<p><strong>Specyfikacja naleznosci:</strong><br>
<strong>{company_name}</strong><br>
<strong>{street_address}</strong><br>
<strong>{postal_code}</strong>, <strong>{city}</strong><br>
<strong>NIP: {nip}</strong><br>
Nr sprawy: <strong>{case_number}</strong><br>
Kwota zadluzenia: <strong>{debt_amount} zl</strong><br>
Rachunek do splaty: {creditor_bank_account}</p>

<p><strong>Kontakt do wierzyciela w celu wyjasnienia sprawy:</strong><br>
Telefon: {creditor_phone}<br>
E-mail: {creditor_email}</p>

<p><strong>Harmonogram dzialan w przypadku braku platnosci:</strong><br>
{stage_3_date} - Ostateczne wezwanie do zaplaty.<br>
{stage_4_date} - Powiadomienie o zamiarze skierowania sprawy do windykatora zewnetrznego i publikacji na gieldzie wierzytelnosci.<br>
{stage_5_date} - Przekazanie sprawy do windykatora zewnetrznego</p>

<p><strong>Pamietaj, aby zapobiec wpisowi na gielde wierzytelnosci nalezy splacic naleznosc.</strong></p>
"""
    },

    "stage_3": {
        "subject": "Wezwanie do zaplaty {case_number}",
        "body_html": """<p><strong>{company_name},</strong><br><br>
Informujemy, ze Panstwa wierzyciel - <strong>{creditor_name}</strong> w dniu <strong>{stage_4_date}</strong>
upubliczni ponizsze dane wraz z wysokoscia zadluzenia w sprawie <strong>{case_number}</strong>.<br><br>
W przypadku kiedy naleznosc zostala oplacona, prosze o zignorowanie ponizszej wiadomosci.</p>

<p><strong>Specyfikacja naleznosci:</strong><br>
<strong>{company_name}</strong><br>
<strong>{street_address}</strong><br>
<strong>{postal_code}</strong>, <strong>{city}</strong><br>
<strong>NIP: {nip}</strong><br>
Nr sprawy: <strong>{case_number}</strong><br>
Kwota zadluzenia: <strong>{debt_amount} zl</strong><br>
Rachunek do splaty: {creditor_bank_account}</p>

<p><strong>Kontakt do wierzyciela w celu wyjasnienia sprawy:</strong><br>
Telefon: {creditor_phone}<br>
E-mail: {creditor_email}</p>

<p><strong>Harmonogram dzialan w przypadku braku platnosci:</strong><br>
{stage_4_date} - Powiadomienie o zamiarze skierowania sprawy do windykatora zewnetrznego i publikacji na gieldzie wierzytelnosci.<br>
{stage_5_date} - Przekazanie sprawy do windykatora zewnetrznego</p>

<p><strong>Pamietaj, aby zapobiec wpisowi na gielde wierzytelnosci nalezy splacic naleznosc.</strong></p>
"""
    },

    "stage_4": {
        "subject": "Powiadomienie o zamiarze skierowania sprawy {case_number} do windykatora zewnetrznego i publikacji na gieldzie wierzytelnosci",
        "body_html": """<p><strong>{company_name},</strong><br><br>
Informujemy, ze w systemie Vindicat.pl zostaly upublicznione Panstwa dane wraz z wysokoscia zadluzenia w sprawie <strong>{case_number}</strong>.
Aby uregulowac zaleglosc nalezy skontaktowac sie z wierzycielem:
<strong>{creditor_name}</strong>.<br><br>
W przypadku kiedy naleznosc zostala oplacona, prosze o zignorowanie ponizszej wiadomosci.</p>

<p><strong>Specyfikacja naleznosci:</strong><br>
<strong>{company_name}</strong><br>
<strong>{street_address}</strong><br>
<strong>{postal_code}</strong>, <strong>{city}</strong><br>
<strong>NIP: {nip}</strong><br>
Nr sprawy: <strong>{case_number}</strong><br>
Kwota zadluzenia: <strong>{debt_amount} zl</strong><br>
Rachunek do splaty: {creditor_bank_account}</p>

<p><strong>Kontakt do wierzyciela w celu wyjasnienia sprawy:</strong><br>
Telefon: {creditor_phone}<br>
E-mail: {creditor_email}</p>

<p><strong>Harmonogram dzialan w przypadku braku platnosci:</strong><br>
{stage_5_date} - Skierowanie sprawy do windykatora zewnetrznego</p>

<p><strong>Pamietaj, aby zapobiec wpisowi na gielde wierzytelnosci nalezy splacic naleznosc.</strong></p>
"""
    },

    "stage_5": {
        "subject": "Przekazanie sprawy {case_number} do windykatora zewnetrznego",
        "body_html": """<p><strong>{company_name},</strong><br><br>
Informujemy, ze Panstwa sprawa o zaplate kwoty <strong>{debt_amount} zl</strong> wobec
<strong>{creditor_name}</strong>
zostala skierowana do windykatora zewnetrznego. Istnieje mozliwosc wycofania sprawy i zawarcia porozumienia.
Aby uregulowac zaleglosc nalezy skontaktowac sie z wierzycielem:
<strong>{creditor_name}</strong>.<br><br>
W przypadku kiedy naleznosc zostala oplacona, prosze o zignorowanie ponizszej wiadomosci.</p>

<p><strong>Specyfikacja naleznosci:</strong><br>
<strong>{company_name}</strong><br>
<strong>{street_address}</strong><br>
<strong>{postal_code}</strong>, <strong>{city}</strong><br>
<strong>NIP: {nip}</strong><br>
Nr sprawy: <strong>{case_number}</strong><br>
Kwota zadluzenia: <strong>{debt_amount} zl</strong><br>
Rachunek do splaty: {creditor_bank_account}</p>

<p><strong>Kontakt do wierzyciela w celu wyjasnienia sprawy:</strong><br>
Telefon: {creditor_phone}<br>
E-mail: {creditor_email}</p>

<p><strong>Aby zapobiec realizacji tego etapu, prosimy o uregulowanie naleznosci.</strong></p>
"""
    }
}
