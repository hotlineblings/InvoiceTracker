# InvoiceTracker - System Automatycznej Windykacji Należności

**InvoiceTracker** to zaawansowany system automatycznej windykacji należności, który integruje się z platformą **inFakt**, umożliwiając kompleksowe zarządzanie procesem monitorowania płatności i wysyłania przypomnień o zaległych fakturach. System automatyzuje cały proces windykacji, od wykrycia zbliżającego się terminu płatności aż po przekazanie sprawy do windykatora zewnętrznego.

---

## 📋 Spis Treści

1. [Główne Funkcjonalności](#-główne-funkcjonalności)
2. [Architektura Systemu](#-architektura-systemu)
3. [Modele Danych](#-modele-danych)
4. [Proces Windykacji](#-proces-windykacji)
5. [Integracja z inFakt](#-integracja-z-infakt)
6. [System Powiadomień](#-system-powiadomień)
7. [Panel Administracyjny](#-panel-administracyjny)
8. [Technologie](#-technologie)
9. [Instalacja](#-instalacja)
10. [Konfiguracja](#-konfiguracja)
11. [Deployment na Google Cloud Platform](#-deployment-na-google-cloud-platform)
12. [API Endpoints](#-api-endpoints)
13. [Monitoring i Logi](#-monitoring-i-logi)
14. [Bezpieczeństwo](#-bezpieczeństwo)
15. [Rozwiązywanie Problemów](#-rozwiązywanie-problemów)
16. [Roadmap](#-roadmap)

---

## 🎯 Główne Funkcjonalności

### Automatyzacja Windykacji
- **5-stopniowy proces windykacji** z konfigurowalnymi terminami wysyłki
- **Automatyczna synchronizacja faktur** z platformą inFakt (codziennie o 11:00 CET)
- **Inteligentne wykrywanie** nowych faktur i aktualizacja statusów płatności
- **Automatyczne zamykanie spraw** po opłaceniu faktury lub przejściu przez wszystkie etapy

### Zarządzanie Sprawami
- **Panel zarządzania sprawami aktywnych** - lista wszystkich nieopłaconych faktur
- **Archiwum spraw zakończonych** - podział na opłacone i nieopłacone
- **Widok szczegółowy sprawy** - historia powiadomień, postęp windykacji
- **Widok klienta** - wszystkie faktury danego klienta w jednym miejscu
- **Ręczne akcje** - wysyłanie powiadomień, oznaczanie jako opłacone, wznawianie spraw

### System Powiadomień
- **Automatyczne wysyłanie przypomnień email** według harmonogramu (codziennie o 11:05 CET)
- **Ręczna wysyłka powiadomień** z poziomu panelu administratora
- **Wsparcie dla wielu adresów email** (rozdzielonych przecinkami)
- **HTML templates** z dynamicznymi danymi (kwoty, terminy, dane klienta)
- **Retry logic** - 3 próby wysyłki z opóźnieniem 5 sekund

### Monitoring
- **Status synchronizacji** - historia, statystyki, czas trwania, liczba wywołań API
- **Historia powiadomień** - wszystkie wysłane emaile z treścią i datą
- **Postęp windykacji** - wizualizacja (progress bar) dla każdej sprawy
- **Export danych** do CSV (funkcja dostępna w sync_database.py)

---

## 🏗 Architektura Systemu

### Komponenty

```
┌─────────────────────────────────────────────────────────────┐
│                    Google Cloud Platform                     │
│                                                               │
│  ┌──────────────┐      ┌─────────────┐      ┌────────────┐  │
│  │   App Engine │◄────►│  Cloud SQL  │      │   Cloud    │  │
│  │   (Flask)    │      │ (PostgreSQL)│      │ Scheduler  │  │
│  └──────┬───────┘      └─────────────┘      └──────┬─────┘  │
│         │                                           │        │
└─────────┼───────────────────────────────────────────┼────────┘
          │                                           │
          │ /cron/run_sync (codziennie 11:00)        │
          └───────────────────────────────────────────┘

          ▼
┌─────────────────────────┐      ┌──────────────────┐
│   InvoiceTracker App    │      │   inFakt API     │
│                         │◄────►│  (REST API)      │
│  • Flask Routes         │      │                  │
│  • Scheduler (11:05)    │      │  • Faktury       │
│  • Email Sender (SMTP)  │      │  • Klienci       │
│  • Sync Engine          │      │  • Płatności     │
└─────────────────────────┘      └──────────────────┘
```

### Flow Danych

1. **Synchronizacja (11:00 CET)**
   - Cloud Scheduler wywołuje `/cron/run_sync`
   - `run_full_sync()` uruchamia się w osobnym wątku
   - Pobieranie nowych faktur z terminami za 1 dzień (`sync_new_invoices`)
   - Aktualizacja statusów płatności dla aktywnych spraw (`update_existing_cases`)
   - Tworzenie nowych spraw windykacyjnych dla nieopłaconych faktur
   - Zamykanie opłaconych spraw automatycznie
   - Zapis statystyk do `SyncStatus`

2. **Wysyłka Powiadomień (11:05 CET)**
   - APScheduler uruchamia `run_mail_with_context()`
   - Pobieranie wszystkich aktywnych spraw w partiach (batch_size=100)
   - Dla każdej faktury: sprawdzenie czy termin wysyłki przypada na dzisiaj
   - Generowanie emaila z szablonu HTML (`generate_email`)
   - Wysyłka przez SMTP z retry logic (3 próby)
   - Zapis do `NotificationLog`
   - Auto-zamykanie spraw po wysłaniu etapu 5

3. **Ręczne Akcje (Panel Admin)**
   - Synchronizacja: `/manual_sync` → uruchamia `run_full_sync()` w wątku
   - Wysyłka powiadomienia: `/send_manual/<case_number>/<stage>` → wysyła email i loguje
   - Oznaczenie jako opłacone: `/mark_paid/<invoice_id>` → zamyka sprawę
   - Wznowienie sprawy: `/reopen_case/<case_number>` → zmienia status na "active"

---

## 📊 Modele Danych

### Case (Sprawa Windykacyjna)
**Plik**: `InvoiceTracker/models.py:6-25`

```python
Case(
    id: int (PK),
    case_number: str (UNIQUE) - numer sprawy = numer faktury,
    client_id: str - ID klienta z inFakt,
    client_nip: str - NIP klienta,
    client_company_name: str - nazwa firmy,
    status: str - "active" | "closed_oplacone" | "closed_nieoplacone",
    created_at: datetime,
    updated_at: datetime
)
```

**Relacja**: 1:1 z Invoice (każda sprawa = jedna faktura)

### Invoice (Faktura)
**Plik**: `InvoiceTracker/models.py:27-56`

```python
Invoice(
    id: int (PK) - ID z inFakt,
    invoice_number: str - numer faktury,
    invoice_date: date - data wystawienia,
    payment_due_date: date - termin płatności,
    gross_price: int - kwota brutto w GROSZACH,
    paid_price: int - kwota opłacona w GROSZACH,
    left_to_pay: int - pozostało do spłaty w GROSZACH,
    status: str - "sent" | "printed" | "paid",
    debt_status: str - aktualny etap windykacji,
    client_id: str,
    client_company_name: str,
    client_email: str - może zawierać wiele adresów (przecinek),
    client_nip: str,
    client_address: str - pełny adres,
    currency: str - waluta (domyślnie PLN),
    paid_date: date - data opłacenia,
    payment_method: str,
    case_id: int (FK) - powiązanie z Case
)
```

**UWAGA**: Ceny przechowywane w **groszach** (int), wyświetlane jako złote (float/100).

### NotificationLog (Historia Powiadomień)
**Plik**: `InvoiceTracker/models.py:58-74`

```python
NotificationLog(
    id: int (PK),
    sent_at: datetime,
    client_id: str,
    invoice_number: str,
    email_to: str,
    subject: str,
    body: text - pełna treść HTML,
    stage: str - etap windykacji,
    mode: str - "Automatyczne" | "Manualne" | "System",
    scheduled_date: datetime
)
```

### SyncStatus (Status Synchronizacji)
**Plik**: `InvoiceTracker/models.py:76-99`

```python
SyncStatus(
    id: int (PK),
    sync_type: str - "new" | "update" | "full",
    processed: int - liczba przetworzonych faktur,
    timestamp: datetime,
    duration: float - czas trwania (sekundy),
    new_cases: int - liczba nowych spraw,
    updated_cases: int - liczba zaktualizowanych,
    closed_cases: int - liczba zamkniętych,
    api_calls: int - liczba wywołań API inFakt
)
```

### NotificationSettings (Ustawienia Powiadomień)
**Plik**: `InvoiceTracker/models.py:102-147`

```python
NotificationSettings(
    id: int (PK),
    stage_name: str (UNIQUE) - nazwa etapu,
    offset_days: int - dni względem payment_due_date,
    created_at: datetime,
    updated_at: datetime
)
```

**Domyślne wartości**:
- "Przypomnienie o zbliżającym się terminie płatności": **-1 dzień**
- "Powiadomienie o upływie terminu płatności": **7 dni**
- "Wezwanie do zapłaty": **14 dni**
- "Powiadomienie o zamiarze skierowania sprawy...": **21 dni**
- "Przekazanie sprawy do windykatora zewnętrznego": **30 dni**

---

## 🔄 Proces Windykacji

### Etapy Windykacji

| Etap | Nazwa | Domyślny Termin | Treść | Akcje |
|------|-------|-----------------|-------|-------|
| **1** | Przypomnienie o zbliżającym się terminie | **-1 dzień** przed terminem | Przypomnienie, kwota, dane rachunku | Email |
| **2** | Powiadomienie o upływie terminu | **7 dni** po terminie | Upłynięcie terminu + harmonogram | Email |
| **3** | Wezwanie do zapłaty | **14 dni** po terminie | Ostateczne wezwanie + ostrzeżenie | Email |
| **4** | Powiadomienie o zamiarze publikacji | **21 dni** po terminie | Publikacja na Vindicat.pl | Email |
| **5** | Przekazanie do windykatora | **30 dni** po terminie | Windykator zewnętrzny | Email + **Auto-zamknięcie** |

### Logika Wysyłki

**Plik**: `InvoiceTracker/scheduler.py:35-140`

```python
# Scheduler uruchamia się codziennie o 9:05 (UTC) = 11:05 (CET)
for invoice in active_invoices:
    days_diff = (today - invoice.payment_due_date).days

    for stage_name, offset_days in notification_settings.items():
        if days_diff == offset_days:
            # Sprawdź czy już wysłano
            if NotificationLog.exists(invoice_number, stage_name):
                continue

            # Generuj email
            subject, body_html = generate_email(stage_name, invoice)

            # Wyślij do wszystkich adresów (retry 3x)
            send_email(client_email, subject, body_html, html=True)

            # Zaloguj
            NotificationLog.create(...)

            # Zamknij sprawę po etapie 5
            if stage == "Przekazanie sprawy do windykatora zewnętrznego":
                case.status = "closed_nieoplacone"
```

### Szablony Email

**Plik**: `InvoiceTracker/mail_templates.py:1-137`

Każdy etap ma dedykowany szablon HTML z placeholderami:
- `{company_name}`, `{nip}`, `{case_number}`
- `{debt_amount}`, `{due_date}`
- `{street_address}`, `{postal_code}`, `{city}`
- `{stage_3_date}`, `{stage_4_date}`, `{stage_5_date}` - automatycznie kalkulowane

**Przykład (Etap 1)**:
```html
<p><strong>{company_name},</strong><br><br>
Informujemy, iż z dniem <strong>{due_date}</strong> mija termin zapłaty
dla faktury <strong>{case_number}</strong>.
Kwota zadłużenia: <strong>{debt_amount} zł</strong><br>
Rachunek do spłaty: 27 1140 1124 0000 3980 6300 1001</p>
```

---

## 🔗 Integracja z inFakt

### API Client

**Plik**: `InvoiceTracker/src/api/api_client.py:1-138`

```python
class InFaktAPIClient:
    base_url = "https://api.infakt.pl/api/v3"

    # Metody
    list_invoices(offset, limit, fields, order, query_params)
    list_clients(offset, limit)
    get_client_details(client_id)  # BEZ parametru 'fields' (fix błędu 500)
    get_multiple_client_details(client_ids)
```

### Synchronizacja Faktur

**Plik**: `InvoiceTracker/update_db.py:26-221`

#### 1. Synchronizacja Nowych Faktur (`sync_new_invoices`)
```python
# Szuka faktur z terminem płatności za 1 dzień
query_params = {"q[payment_date_eq]": tomorrow}
fields = ["id", "number", "invoice_date", "gross_price", "status", ...]

for invoice in api_client.list_invoices(...):
    # Tylko 'sent' i 'printed' (pomijamy 'paid')
    if invoice.status not in ('sent', 'printed'):
        continue

    # Pobierz szczegóły klienta
    client_data = api_client.get_client_details(invoice.client_id)
    invoice.client_email = client_data.get('email')
    invoice.client_nip = client_data.get('nip')
    invoice.client_company_name = client_data.get('company_name')

    # Utwórz sprawę windykacyjną jeśli left_to_pay > 0
    if invoice.left_to_pay > 0:
        Case.create(case_number=invoice.invoice_number, status="active")
```

#### 2. Aktualizacja Istniejących Spraw (`update_existing_cases`)
```python
# Pobiera faktury z zakresem: -35 dni do +3 dni od dzisiaj
query_params = {
    "q[payment_date_gteq]": (today - 35 days),
    "q[payment_date_lteq]": (today + 3 days)
}

for invoice in api_client.list_invoices(...):
    # Aktualizuj tylko aktywne sprawy
    if case.status != 'active':
        continue

    # Aktualizuj dane płatności
    invoice.paid_price = api_data.get('paid_price')
    invoice.left_to_pay = gross_price - paid_price

    # Zamknij sprawę jeśli opłacona
    if invoice.left_to_pay <= 0 or invoice.status == 'paid':
        case.status = "closed_oplacone"
```

#### 3. Pełna Synchronizacja (`run_full_sync`)
```python
# Wywołuje obie funkcje + zapisuje zbiorczy SyncStatus
total_new, new_cases, api_new = sync_new_invoices()
total_updates, active, closed, api_update = update_existing_cases()

SyncStatus.create(
    sync_type="full",
    processed=total_new + total_updates,
    api_calls=api_new + api_update,
    ...
)
```

### Harmonogram Synchronizacji

- **Cloud Scheduler**: Codziennie o **11:00 CET** (`cron.yaml:3-6`)
- **Endpoint**: `/cron/run_sync` (app.py:588-598)
- **Autoryzacja**: Sprawdza nagłówek `X-Appengine-Cron: true`
- **Wykonanie**: W osobnym wątku (`threading.Thread`)

---

## 📧 System Powiadomień

### Konfiguracja SMTP

**Plik**: `InvoiceTracker/send_email.py:12-17`

```python
SMTP_SERVER = os.getenv('SMTP_SERVER', 'sgz.nazwa.pl')
SMTP_PORT = 587
SMTP_USE_TLS = True
SMTP_USERNAME = os.getenv('SMTP_USERNAME')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')
```

### Persystentne Połączenie

**Plik**: `InvoiceTracker/send_email.py:22-46`

```python
# Context manager dla ponownego użycia połączenia
with get_smtp_connection() as smtp:
    smtp.send_message(msg)
```

**Zalety**:
- Szybsza wysyłka (brak reconnect dla każdego emaila)
- Auto-retry przy zerwaniu połączenia

### Generator Emaili

**Plik**: `InvoiceTracker/mail_utils.py:5-59`

```python
def generate_email(stage, invoice):
    # Mapuje pełną nazwę etapu na klucz szablonu
    template_key = stage_keys_map.get(stage)  # "stage_1" ... "stage_5"
    template = MAIL_TEMPLATES[template_key]

    # Oblicza daty przyszłych etapów
    stage_3_date = (invoice.payment_due_date + timedelta(days=7))
    stage_4_date = (invoice.payment_due_date + timedelta(days=14))
    stage_5_date = (invoice.payment_due_date + timedelta(days=21))

    # Formatuje szablon
    subject = template["subject"].format(case_number=invoice.invoice_number)
    body_html = template["body_html"].format(
        company_name=invoice.client_company_name,
        debt_amount=f"{invoice.gross_price / 100:.2f}",
        ...
    )
    return subject, body_html
```

### Scheduler

**Plik**: `InvoiceTracker/scheduler.py:142-157`

```python
scheduler = BackgroundScheduler()
# Uruchamia się o 9:05 UTC (11:05 CET) - musi być 2h wstecz!
scheduler.add_job(lambda: run_mail_with_context(app), 'cron', hour=9, minute=5)
scheduler.start()
```

**UWAGA**: APScheduler używa UTC, więc dla CET/CEST trzeba odjąć 2 godziny!

---

## 🖥 Panel Administracyjny

### Widoki i Funkcje

| Route | Funkcja | Opis |
|-------|---------|------|
| `/` | `active_cases` | Lista aktywnych spraw z wyszukiwaniem, sortowaniem, paginacją |
| `/completed` | `completed_cases` | Archiwum zakończonych spraw (opłacone + nieopłacone) |
| `/case/<case_number>` | `case_detail` | Szczegóły sprawy + historia powiadomień + akcje |
| `/client/<client_id>` | `client_cases` | Wszystkie faktury klienta (aktywne + zakończone) |
| `/mark_paid/<invoice_id>` | `mark_invoice_paid` | Oznacza fakturę jako opłaconą + zamyka sprawę |
| `/send_manual/<case>/<stage>` | `send_manual` | Ręczna wysyłka powiadomienia dla wybranego etapu |
| `/reopen_case/<case_number>` | `reopen_case` | Wznawia zamkniętą sprawę (zmienia status na "active") |
| `/manual_sync` | `manual_sync` | Uruchamia pełną synchronizację w tle |
| `/sync_status` | `sync_status` | Historia synchronizacji (ostatnie 20 rekordów) |
| `/shipping_settings` | `shipping_settings_view` | Edycja terminów wysyłki powiadomień |
| `/login` | `login` | Logowanie (username/password z env) |
| `/logout` | `logout` | Wylogowanie |

### Widok Aktywnych Spraw

**Plik**: `InvoiceTracker/templates/cases.html:1-100`

**Funkcje**:
- Wyszukiwanie: ID klienta, NIP, nazwa firmy, email, numer sprawy
- Sortowanie: według dowolnej kolumny (rosnąco/malejąco)
- Paginacja: 100 rekordów na stronę
- Statystyki: łączna kwota zadłużenia, liczba spraw
- Progress bar: wizualizacja postępu windykacji (0-100%)
- Przycisk synchronizacji: ręczne uruchomienie

**Kolumny**:
- Numer sprawy (link do szczegółów)
- ID klienta
- Nazwa firmy (link do widoku klienta)
- NIP
- Email
- Kwota zadłużenia (zł)
- Dni od/do terminu (ujemne = przed terminem)
- Postęp (progress bar)
- Akcje (przycisk "Pokaż")

### Widok Szczegółów Sprawy

**Funkcje**:
- Informacje o fakturze: numer, daty, kwoty
- Dane klienta: nazwa, NIP, email, adres
- Historia powiadomień: data, etap, tryb, treść emaila
- Postęp windykacji: progress bar
- Akcje:
  - Wysyłka powiadomień dla etapów 1-5 (przyciski)
  - Oznacz jako opłacone
  - Wznów sprawę (jeśli zamknięta)

### Ustawienia Wysyłki

**Plik**: `InvoiceTracker/templates/shipping_settings.html`

**Funkcje**:
- Edycja terminów dla wszystkich 5 etapów
- Wartości w dniach względem terminu płatności
- Wartości ujemne = przed terminem (np. -1 = dzień przed)
- Zapis do bazy (tabela `NotificationSettings`)
- Inicjalizacja domyślnych wartości przy pierwszym uruchomieniu

---

## 🛠 Technologie

### Backend
- **Python 3.11** (runtime: python311 na App Engine)
- **Flask 2.2.5** - framework webowy
- **SQLAlchemy 2.0.37** - ORM
- **Flask-Migrate** - migracje bazy danych
- **APScheduler 3.9.1** - scheduler powiadomień
- **aiohttp 3.9.0** - asynchroniczne wywołania API

### Baza Danych
- **PostgreSQL 16** (Cloud SQL)
- **psycopg2-binary 2.9.6** - driver PostgreSQL

### Frontend
- **Bootstrap 5.3** - UI framework
- **Jinja2 3.1.5** - silnik szablonów
- HTML/CSS/JavaScript

### Email
- **smtplib** (Python stdlib) - wysyłka emaili
- **email.mime** - tworzenie wiadomości MIME

### Infrastruktura
- **Google App Engine** (Python 3.11 Standard Environment)
- **Cloud SQL** (PostgreSQL 16)
- **Cloud Scheduler** (cron jobs)
- **Gunicorn 20.1.0** - WSGI server

### Inne
- **python-dotenv 1.0.1** - zarządzanie zmiennymi środowiskowymi
- **requests 2.32.3** - wywołania HTTP
- **certifi 2024.12.14** - certyfikaty SSL

---

## 🚀 Instalacja

### Wymagania Systemowe

- Python 3.9+
- PostgreSQL 12+
- Konto w serwisie **inFakt** z aktywnym API
- Serwer SMTP (np. nazwa.pl, Gmail, SendGrid)
- Google Cloud Platform (dla wdrożenia produkcyjnego)

### Kroki Instalacji

#### 1. Klonowanie Repozytorium

```bash
git clone https://github.com/yourusername/InvoiceTracker.git
cd InvoiceTracker
```

#### 2. Utworzenie Środowiska Wirtualnego

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# lub
venv\Scripts\activate  # Windows
```

#### 3. Instalacja Zależności

```bash
pip install -r requirements.txt
```

**Zawartość requirements.txt**:
```
Flask==2.2.5
Flask-SQLAlchemy==3.0.2
flask-migrate
SQLAlchemy==2.0.37
psycopg2-binary==2.9.6
APScheduler==3.9.1
aiohttp==3.9.0
python-dotenv==1.0.1
requests==2.32.3
gunicorn==20.1.0
```

#### 4. Konfiguracja Bazy Danych Lokalnej

```bash
# Utwórz bazę PostgreSQL
createdb invoice_tracker

# Lub z poziomu psql
psql -U postgres
CREATE DATABASE invoice_tracker;
\q
```

#### 5. Konfiguracja Zmiennych Środowiskowych

Utwórz plik `.env` w katalogu głównym:

```env
# --- Baza Danych (Lokalna) ---
DB_USER=postgres
DB_PASSWORD=your_password
DB_NAME=invoice_tracker
INSTANCE_CONNECTION_NAME=your-project:region:instance  # Dla GCP

# --- Aplikacja ---
SECRET_KEY=your_secret_key_here_min_32_chars
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your_secure_password

# --- API inFakt ---
INFAKT_API_KEY=your_infakt_api_key

# --- SMTP ---
SMTP_SERVER=smtp.nazwa.pl
SMTP_PORT=587
SMTP_USERNAME=your_email@domain.pl
SMTP_PASSWORD=your_smtp_password
EMAIL_FROM=your_email@domain.pl
SMTP_USE_TLS=True
```

#### 6. Inicjalizacja Bazy Danych

```bash
# Generuj migracje (jeśli nie istnieją)
flask db init
flask db migrate -m "Initial migration"

# Zastosuj migracje
flask db upgrade
```

#### 7. Uruchomienie Aplikacji Lokalnie

```bash
python -m InvoiceTracker.app

# Lub
gunicorn --bind 0.0.0.0:8080 wsgi:application
```

Aplikacja będzie dostępna pod adresem: **http://localhost:8080**

---

## ⚙ Konfiguracja

### Ustawienia Terminów Wysyłki

Po pierwszym uruchomieniu aplikacji:

1. Zaloguj się (domyślnie: admin/admin)
2. Przejdź do: **Ustawienia wysyłki**
3. Edytuj terminy dla każdego etapu (w dniach):
   - Wartości dodatnie = po terminie płatności
   - Wartości ujemne = przed terminem płatności
4. Kliknij **Zapisz ustawienia**

**Ustawienia zapisywane są w bazie** (tabela `notification_settings`), więc scheduler używa aktualnych wartości.

### Konfiguracja Schedulera

**Plik**: `InvoiceTracker/scheduler.py:142-157`

```python
# Zmień godzinę wysyłki powiadomień (UWAGA: UTC -2h dla CET)
scheduler.add_job(
    lambda: run_mail_with_context(app),
    'cron',
    hour=9,   # 9:00 UTC = 11:00 CET
    minute=5
)
```

### Konfiguracja Cloud Scheduler

**Plik**: `cron.yaml:1-7`

```yaml
cron:
- description: "Codzienna Pełna Synchronizacja Danych"
  url: /cron/run_sync
  schedule: every day 11:00
  timezone: Europe/Warsaw
```

**Deployment**:
```bash
gcloud app deploy cron.yaml
```

---

## ☁️ Deployment na Google Cloud Platform

### Architektura GCP

```
App Engine (Python 3.11)
    ↓
Cloud SQL (PostgreSQL 16)
    ↓
Cloud Scheduler (Cron Jobs)
```

### Krok 1: Przygotowanie Projektu GCP

```bash
# Zainstaluj Google Cloud SDK
curl https://sdk.cloud.google.com | bash

# Inicjalizacja
gcloud init

# Ustaw projekt
gcloud config set project YOUR_PROJECT_ID

# Włącz wymagane API
gcloud services enable sqladmin.googleapis.com
gcloud services enable appengine.googleapis.com
gcloud services enable cloudscheduler.googleapis.com
```

### Krok 2: Utworzenie Cloud SQL

```bash
# Utwórz instancję PostgreSQL
gcloud sql instances create invoice-tracker-db \
    --database-version=POSTGRES_16 \
    --tier=db-f1-micro \
    --region=europe-central2

# Ustaw hasło dla użytkownika postgres
gcloud sql users set-password postgres \
    --instance=invoice-tracker-db \
    --password=YOUR_SECURE_PASSWORD

# Utwórz bazę danych
gcloud sql databases create invoice_tracker \
    --instance=invoice-tracker-db
```

### Krok 3: Konfiguracja app.yaml

Utwórz plik `app.yaml` w katalogu głównym:

```yaml
runtime: python311
entrypoint: gunicorn -b :$PORT wsgi:application

env_variables:
  # Baza danych
  DB_USER: "postgres"
  DB_PASSWORD: "YOUR_DB_PASSWORD"
  DB_NAME: "invoice_tracker"
  INSTANCE_CONNECTION_NAME: "YOUR_PROJECT_ID:REGION:invoice-tracker-db"

  # Aplikacja
  SECRET_KEY: "YOUR_SECRET_KEY_MIN_32_CHARS"
  ADMIN_USERNAME: "admin"
  ADMIN_PASSWORD: "YOUR_ADMIN_PASSWORD"

  # API inFakt
  INFAKT_API_KEY: "YOUR_INFAKT_API_KEY"

  # SMTP
  SMTP_SERVER: "smtp.nazwa.pl"
  SMTP_PORT: "587"
  SMTP_USERNAME: "your_email@domain.pl"
  SMTP_PASSWORD: "YOUR_SMTP_PASSWORD"
  EMAIL_FROM: "your_email@domain.pl"

  # Gunicorn
  GUNICORN_PID: "1"

automatic_scaling:
  target_cpu_utilization: 0.65
  min_instances: 1
  max_instances: 2
```

**UWAGA**: Nigdy nie commituj `app.yaml` z danymi wrażliwymi! Dodaj do `.gitignore`.

### Krok 4: Deployment Aplikacji

```bash
# Wdróż aplikację
gcloud app deploy app.yaml

# Wdróż cron jobs
gcloud app deploy cron.yaml

# Otwórz aplikację w przeglądarce
gcloud app browse
```

### Krok 5: Migracje Bazy na Produkcji

```bash
# Połącz się z Cloud SQL przez proxy
cloud_sql_proxy -instances=YOUR_PROJECT_ID:REGION:invoice-tracker-db=tcp:5432 &

# Ustaw zmienne środowiskowe
export DB_USER=postgres
export DB_PASSWORD=YOUR_DB_PASSWORD
export DB_NAME=invoice_tracker
export DATABASE_URL=postgresql://$DB_USER:$DB_PASSWORD@localhost:5432/$DB_NAME

# Zastosuj migracje
flask db upgrade

# Lub przez gcloud
gcloud sql connect invoice-tracker-db --user=postgres
\c invoice_tracker
# Wykonaj migracje ręcznie
```

### Monitorowanie na GCP

```bash
# Logi aplikacji
gcloud app logs tail -s default

# Logi Cloud Scheduler
gcloud logging read "resource.type=cloud_scheduler_job"

# Status cron jobs
gcloud scheduler jobs list
```

---

## 📡 API Endpoints

### Publiczne (bez autoryzacji)

| Method | Endpoint | Opis |
|--------|----------|------|
| GET/POST | `/login` | Logowanie do panelu |
| GET | `/static/<path>` | Pliki statyczne (CSS, JS, obrazy) |

### Chronione (wymagana autoryzacja)

| Method | Endpoint | Parametry | Opis |
|--------|----------|-----------|------|
| GET | `/` | `search`, `sort_by`, `sort_order`, `page` | Lista aktywnych spraw |
| GET | `/completed` | `search`, `sort_by`, `sort_order`, `page` | Lista zakończonych spraw |
| GET | `/case/<case_number>` | - | Szczegóły sprawy + historia |
| GET | `/client/<client_id>` | - | Wszystkie faktury klienta |
| GET | `/mark_paid/<invoice_id>` | - | Oznacz jako opłacone |
| GET | `/send_manual/<case_number>/<stage>` | stage: przeds/7dni/14dni/21dni/30dni | Ręczna wysyłka powiadomienia |
| GET | `/reopen_case/<case_number>` | - | Wznów zamkniętą sprawę |
| GET | `/manual_sync` | - | Uruchom synchronizację w tle |
| GET | `/sync_status` | - | Historia synchronizacji |
| GET/POST | `/shipping_settings` | POST: formData z terminami | Edycja ustawień wysyłki |
| GET | `/logout` | - | Wylogowanie |

### Cron (tylko z Cloud Scheduler)

| Method | Endpoint | Autoryzacja | Opis |
|--------|----------|-------------|------|
| GET | `/cron/run_sync` | Header: `X-Appengine-Cron: true` | Pełna synchronizacja danych |

### Przykład Wywołania API

```bash
# Logowanie
curl -X POST http://localhost:8080/login \
  -d "username=admin&password=admin" \
  -c cookies.txt

# Lista aktywnych spraw (z cookies)
curl -X GET "http://localhost:8080/?sort_by=days_diff&sort_order=desc" \
  -b cookies.txt

# Ręczna synchronizacja
curl -X GET http://localhost:8080/manual_sync \
  -b cookies.txt
```

---

## 📊 Monitoring i Logi

### Tabela SyncStatus

**Plik**: `InvoiceTracker/models.py:76-99`

Każda synchronizacja (new, update, full) zapisuje rekord:

```python
SyncStatus(
    sync_type="full",
    processed=150,        # liczba faktur przetworzonych
    timestamp=datetime,
    duration=12.45,       # czas w sekundach
    new_cases=5,          # nowe sprawy
    updated_cases=120,    # zaktualizowane
    closed_cases=10,      # zamknięte
    api_calls=25          # wywołania API inFakt
)
```

**Widok**: `/sync_status` - ostatnie 20 synchronizacji

### Tabela NotificationLog

**Plik**: `InvoiceTracker/models.py:58-74`

Każde wysłane powiadomienie (automatyczne/ręczne) zapisuje:

```python
NotificationLog(
    sent_at=datetime,
    client_id="12345",
    invoice_number="FV2024/01/123",
    email_to="client@example.com",
    subject="Przypomnienie o zbliżającym się terminie...",
    body="<p>Pełna treść HTML</p>",
    stage="Przypomnienie o zbliżającym się terminie płatności",
    mode="Automatyczne",  # lub "Manualne"
    scheduled_date=datetime
)
```

**Widok**: Widoczne w szczegółach sprawy (`/case/<case_number>`)

### Logi Aplikacyjne

**Konfiguracja**: `InvoiceTracker/app.py:33-34`

```python
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
```

**Logi API**: `InvoiceTracker/logs/api_client.log` (jeśli skonfigurowane)

**Przykłady logów**:
```
2024-01-15 11:00:05 [INFO] scheduler: Rozpoczynam automatyczną wysyłkę maili
2024-01-15 11:01:23 [INFO] update_db: [sync_new_invoices] Przetworzono: 5, Nowe sprawy: 3
2024-01-15 11:02:45 [ERROR] api_client: Błąd HTTP 500 przy get_client_details
```

### Metryki

- **Czas synchronizacji**: zapisany w `SyncStatus.duration`
- **Liczba wywołań API**: zapisana w `SyncStatus.api_calls`
- **Skuteczność wysyłki**: `NotificationLog.count()` vs `error_count`

---

## 🔐 Bezpieczeństwo

### Autoryzacja

**Plik**: `InvoiceTracker/app.py:92-100`

```python
@app.before_request
def require_login():
    # Zwolnione endpointy
    if request.endpoint in ('static', 'login', 'cron_run_sync'):
        return None

    # Wymagaj sesji dla reszty
    if not session.get('logged_in'):
        flash("Musisz się zalogować", "warning")
        return redirect(url_for('login'))
```

### Dane Wrażliwe

1. **Zmienne środowiskowe**: Wszystkie klucze API, hasła w `.env` (nie commitowane)
2. **app.yaml**: Dodane do `.gitignore` (zawiera secrets)
3. **SECRET_KEY**: Używane do szyfrowania sesji Flask
4. **CSRF Protection**: Flask domyślnie chroni formularze

### Połączenie z Bazą

**Plik**: `InvoiceTracker/app.py:63-75`

```python
# Enkodowanie hasła z specjalnymi znakami
safe_password = urllib.parse.quote_plus(db_password)

# Unix socket dla Cloud SQL (bezpieczniejsze niż TCP)
unix_socket_path = f'/cloudsql/{instance_connection_name}'
db_uri = f"postgresql+psycopg2://{db_user}:{safe_password}@/{db_name}?host={unix_socket_path}"
```

### Cloud Scheduler Security

**Plik**: `InvoiceTracker/app.py:588-598`

```python
@app.route('/cron/run_sync')
def cron_run_sync():
    # Sprawdź czy request z App Engine Cron
    is_cron_request = request.headers.get('X-Appengine-Cron') == 'true'

    if not is_cron_request:
        log.warning("Nieautoryzowana próba wywołania /cron/run_sync")
        return jsonify({"status": "ignored"}), 200
```

### Rekomendacje

1. **Zmień domyślne hasło admina** zaraz po instalacji
2. **Użyj silnego SECRET_KEY** (min. 32 znaki, losowe)
3. **Włącz HTTPS** (automatycznie na App Engine)
4. **Rotacja kluczy API** co 90 dni
5. **Audyt logów** regularnie sprawdzaj `NotificationLog` i logi błędów

---

## 🐛 Rozwiązywanie Problemów

### 1. Błędy Synchronizacji

**Objaw**: Brak nowych faktur, błędy w `/sync_status`

**Przyczyny i Rozwiązania**:

```bash
# A) Nieprawidłowy klucz API inFakt
# Sprawdź logi
grep "INFAKT_API_KEY" logs/api_client.log

# Zweryfikuj klucz
curl -H "X-inFakt-ApiKey: YOUR_KEY" https://api.infakt.pl/api/v3/invoices.json

# B) Brak połączenia z bazą danych
# Sprawdź status Cloud SQL
gcloud sql instances describe invoice-tracker-db

# Sprawdź czy proxy działa (lokalnie)
ps aux | grep cloud_sql_proxy

# C) Błąd 500 przy get_client_details
# Upewnij się że NIE używasz parametru 'fields'
# (FIX już w kodzie: InvoiceTracker/src/api/api_client.py:103)
```

### 2. Niedziałająca Wysyłka Emaili

**Objaw**: Brak emaili, błędy w logach

**Przyczyny**:

```bash
# A) Nieprawidłowe dane SMTP
# Testuj ręcznie
python -c "
from InvoiceTracker.send_email import send_email
send_email('test@example.com', 'Test', 'Body test')
"

# B) Zablokowany port 587
# Sprawdź firewall
telnet smtp.nazwa.pl 587

# C) Adres email klienta niepoprawny
# Sprawdź w bazie
psql -d invoice_tracker -c "SELECT invoice_number, client_email FROM invoice WHERE client_email IS NULL OR client_email = 'N/A';"
```

### 3. Scheduler Nie Wysyła Powiadomień

**Objaw**: Brak wpisów w `NotificationLog`

**Przyczyny**:

```bash
# A) Scheduler nie uruchomiony
# Sprawdź logi
grep "Scheduler uruchomiony" logs/app.log

# B) Zła strefa czasowa
# Sprawdź kod scheduler.py:149
# Powinno być: hour=9 (UTC) dla 11:00 CET

# C) Brak aktywnych spraw z terminem
# Sprawdź w bazie
psql -d invoice_tracker -c "
SELECT invoice_number, payment_due_date,
       CURRENT_DATE - payment_due_date AS days_diff
FROM invoice
JOIN case ON invoice.case_id = case.id
WHERE case.status = 'active';
"
```

### 4. Cloud Scheduler Nie Wywołuje Synchronizacji

**Objaw**: Brak rekordów w `SyncStatus` o 11:00

**Przyczyny**:

```bash
# A) Cron job nie wdrożony
gcloud scheduler jobs list
# Powinien być: cron-run-sync

# B) Błąd autoryzacji
# Sprawdź logi Cloud Scheduler
gcloud logging read "resource.type=cloud_scheduler_job" --limit 20

# C) Endpoint zwraca błąd
# Testuj ręcznie (z nagłówkiem)
curl -H "X-Appengine-Cron: true" https://YOUR_APP.appspot.com/cron/run_sync
```

### 5. Migracje Bazy Danych

**Objaw**: Błąd "table does not exist"

```bash
# Sprawdź wersję migracji
flask db current

# Zastosuj brakujące migracje
flask db upgrade

# Jeśli błąd persist, regeneruj migracje
flask db stamp head
flask db migrate -m "Rebuild schema"
flask db upgrade
```

### 6. Duplicated Key Errors

**Objaw**: IntegrityError przy zapisie

```python
# Invoice ID jest z inFakt (może się powtórzyć przy re-sync)
# FIX: Sprawdzaj przed zapisem
existing = db.session.query(Invoice.id).filter_by(id=invoice_id).scalar()
if not existing:
    db.session.add(new_invoice)
```

---

## 🗺 Roadmap

### Wersja 2.0 (Q2 2024)

- [ ] **Dashboard Analytics**
  - Wykresy skuteczności windykacji (% odzyskanych należności)
  - Statystyki klientów (TOP10 dłużników)
  - Prognozowanie przepływów pieniężnych

- [ ] **API REST**
  - Publiczne API dla integracji zewnętrznych
  - Webhook dla zdarzeń (nowa faktura, opłacona, zamknięta sprawa)
  - Dokumentacja Swagger/OpenAPI

- [ ] **Multi-tenant**
  - Obsługa wielu firm/użytkowników
  - Oddzielne bazy danych lub separacja na poziomie `tenant_id`
  - Role i uprawnienia (admin, accountant, viewer)

### Wersja 2.1 (Q3 2024)

- [ ] **SMS Notifications**
  - Integracja z Twilio/SMSAPI
  - Alternatywny kanał dla etapów 3-5

- [ ] **Payment Gateway**
  - Integracja z Stripe/PayU
  - Link do płatności w emailach
  - Auto-zamykanie po potwierdzeniu płatności

- [ ] **Machine Learning**
  - Predykcja prawdopodobieństwa spłaty
  - Automatyczna optymalizacja terminów wysyłki
  - Segmentacja klientów (ryzykowni/bezpieczni)

### Wersja 3.0 (Q4 2024)

- [ ] **Mobile App**
  - Aplikacja na iOS/Android (React Native)
  - Push notifications
  - Obsługa spraw offline

- [ ] **Advanced Reporting**
  - Eksport do PDF (faktury, raporty)
  - Generowanie wezwań do zapłaty
  - Integracja z systemami księgowymi (Fakturownia, Wfirma)

- [ ] **AI Chatbot**
  - Obsługa zapytań klientów
  - Automatyczne negocjacje rat
  - NLP dla analizy odpowiedzi klientów

---

## 📞 Kontakt i Wsparcie

### Autor
**Bartosz Machucki**

### Zgłaszanie Błędów
1. Sprawdź [Issues](https://github.com/yourusername/InvoiceTracker/issues)
2. Utwórz nowy issue z:
   - Opisem problemu
   - Logami błędów
   - Krokami do reprodukcji

### Dokumentacja API inFakt
- [Oficjalna dokumentacja](https://developers.infakt.pl/)
- [Changelog](https://developers.infakt.pl/changelog)

### Licencja
Ten projekt jest własnością prywatną i nie jest dostępny publicznie.

---

## 🎓 Informacje Dodatkowe

### Struktura Projektu

```
InvoiceTracker/
├── InvoiceTracker/
│   ├── __init__.py
│   ├── app.py                  # Główna aplikacja Flask (715 linii)
│   ├── models.py               # Modele SQLAlchemy (147 linii)
│   ├── scheduler.py            # APScheduler (157 linii)
│   ├── send_email.py           # Wysyłka SMTP (85 linii)
│   ├── mail_templates.py       # Szablony HTML (137 linii)
│   ├── mail_utils.py           # Generator emaili (59 linii)
│   ├── update_db.py            # Synchronizacja (467 linii)
│   ├── sync_database.py        # Legacy sync (195 linii)
│   ├── fetch_invoices.py       # Selektywne pobieranie
│   ├── shipping_settings.py    # Konfiguracja terminów
│   ├── secret_key.py           # Generator SECRET_KEY
│   ├── src/
│   │   └── api/
│   │       └── api_client.py   # Klient inFakt API (138 linii)
│   └── templates/
│       ├── layout.html         # Bazowy szablon
│       ├── cases.html          # Lista aktywnych
│       ├── completed.html      # Lista zakończonych
│       ├── case_detail.html    # Szczegóły sprawy
│       ├── client_cases.html   # Widok klienta
│       ├── sync_status.html    # Historia synchronizacji
│       ├── shipping_settings.html  # Ustawienia
│       └── login.html          # Logowanie
├── migrations/                 # Migracje Alembic
├── logs/                       # Logi aplikacyjne
├── wsgi.py                     # Entry point (5 linii)
├── requirements.txt            # Zależności Pythona
├── cron.yaml                   # Cloud Scheduler config
├── app.yaml                    # App Engine config (GITIGNORED)
├── .env                        # Zmienne środowiskowe (GITIGNORED)
└── readme.md                   # Dokumentacja (ten plik)
```

### Konwencje Kodowe

- **Nazewnictwo**:
  - Klasy: `PascalCase` (np. `InvoiceTracker`, `NotificationLog`)
  - Funkcje: `snake_case` (np. `run_full_sync`, `generate_email`)
  - Stałe: `UPPER_CASE` (np. `MAIL_TEMPLATES`, `SMTP_SERVER`)

- **Dokumentacja**:
  - Docstringi dla wszystkich funkcji publicznych
  - Komentarze inline dla złożonej logiki
  - Type hints (opcjonalnie)

- **Logowanie**:
  - `log.info()` - operacje sukcesu
  - `log.warning()` - sytuacje niestandardowe (brak emaila)
  - `log.error()` - błędy, które nie przerwały działania
  - `log.critical()` - błędy krytyczne (brak SECRET_KEY)

### Wartości w Groszach vs Złotych

**WAŻNE**: Baza danych przechowuje ceny w **groszach** (int), aby uniknąć problemów z zaokrągleniami float.

```python
# Zapis do bazy
invoice.gross_price = 15050  # 150.50 zł

# Wyświetlanie użytkownikowi
debt_amount = f"{invoice.gross_price / 100:.2f}"  # "150.50"

# Template
{{ "%.2f"|format(invoice.gross_price / 100) }}  # 150.50
```

### Testowanie

```bash
# Uruchom testy jednostkowe (jeśli istnieją)
pytest tests/

# Test synchronizacji
python -m InvoiceTracker.update_db

# Test wysyłki emaila
python -c "
from InvoiceTracker.send_email import send_email
send_email('test@example.com', 'Test Subject', '<p>Test Body</p>', html=True)
"
```

---

**Wersja dokumentacji**: 2.0
**Data ostatniej aktualizacji**: 2024-01-15
**Kompatybilność**: Python 3.11, PostgreSQL 16, inFakt API v3

---

