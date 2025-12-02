# InvoiceTracker

System automatyzacji windykacji z integracją InFakt API.

## Opis

**InvoiceTracker** to wieloprofilowy (multi-tenant) system automatyzacji windykacji, który integruje się z API fakturowym InFakt. System automatycznie monitoruje terminy płatności, wysyła etapowe przypomnienia mailowe i zarządza sprawami windykacyjnymi od pierwszego przypomnienia do przekazania zewnętrznemu windykatorowi.

### Kluczowe funkcje

- **Multi-tenancy** - pełna izolacja danych między profilami (firmami)
- **5-etapowy proces windykacji** - konfigurowalne offsety czasowe
- **Automatyczna synchronizacja** - pobieranie faktur z InFakt API
- **Automatyczne powiadomienia** - APScheduler z harmonogramem per profil
- **Szyfrowanie danych** - Fernet encryption dla API keys i haseł SMTP
- **Panel administracyjny** - Flask z Bootstrap UI

## Architektura

### Struktura projektu

```
InvoiceTracker/
├── wsgi.py                 # Entry point dla App Engine
├── requirements.txt        # Zależności Python
├── app.yaml               # Konfiguracja App Engine
├── cron.yaml              # Cloud Scheduler jobs
│
├── InvoiceTracker/
│   ├── __init__.py        # Package entry
│   ├── __main__.py        # CLI: python -m InvoiceTracker
│   ├── config.py          # Konfiguracja Flask
│   │
│   ├── app/
│   │   ├── __init__.py    # Application Factory (create_app)
│   │   ├── extensions.py  # Flask extensions (db, migrate)
│   │   ├── models.py      # 7 modeli SQLAlchemy
│   │   ├── constants.py   # Definicje etapów powiadomień
│   │   ├── cli.py         # Flask CLI commands
│   │   │
│   │   ├── blueprints/
│   │   │   ├── auth.py      # Logowanie, wybór profilu
│   │   │   ├── cases.py     # Sprawy aktywne/zamknięte
│   │   │   ├── settings.py  # Ustawienia, harmonogramy
│   │   │   └── sync.py      # CRON, synchronizacja
│   │   │
│   │   ├── services/
│   │   │   ├── update_db.py          # Synchronizacja z API
│   │   │   ├── scheduler.py          # APScheduler jobs
│   │   │   ├── case_service.py       # Logika spraw
│   │   │   ├── notification_service.py
│   │   │   ├── payment_service.py
│   │   │   ├── finance_service.py
│   │   │   ├── diagnostic_service.py
│   │   │   ├── send_email.py         # Multi-tenant SMTP
│   │   │   ├── mail_templates.py     # Szablony 5 etapów
│   │   │   └── mail_utils.py
│   │   │
│   │   └── providers/
│   │       ├── base.py      # InvoiceProvider ABC
│   │       ├── factory.py   # get_provider(account)
│   │       └── infakt.py    # InFaktProvider
│   │
│   ├── templates/          # Szablony Jinja2
│   └── static/             # CSS, JS, images
│
└── migrations/             # Alembic migrations
```

### Model danych

```
Account (Profil firmy)
├── InFakt API Key (encrypted)
├── SMTP Configuration (encrypted)
├── Company Details (dane do szablonów)
├── AccountScheduleSettings (harmonogramy)
└── NotificationSettings (5 etapów)
    ├── Cases (sprawy windykacyjne)
    │   └── Invoice (1:1)
    ├── NotificationLog (historia maili)
    └── SyncStatus (historia synchronizacji)
```

### Flow danych

```
┌─────────────────────────────────────────────────────────────┐
│                    Google Cloud Platform                     │
│                                                              │
│  ┌──────────────┐      ┌─────────────┐      ┌────────────┐  │
│  │   App Engine │◄────►│  Cloud SQL  │      │   Cloud    │  │
│  │   (Flask)    │      │(PostgreSQL) │      │ Scheduler  │  │
│  └──────┬───────┘      └─────────────┘      └──────┬─────┘  │
│         │                                           │        │
└─────────┼───────────────────────────────────────────┼────────┘
          │                                           │
          │ /cron/run_sync (co 1 godzinę)            │
          └───────────────────────────────────────────┘
          ▼
┌─────────────────────────┐      ┌──────────────────┐
│   InvoiceTracker App    │      │   InFakt API     │
│                         │◄────►│                  │
│  • APScheduler (emails) │      │  • /invoices     │
│  • Smart CRON (sync)    │      │  • /clients      │
│  • Multi-tenant SMTP    │      │                  │
└─────────────────────────┘      └──────────────────┘
```

## Instalacja

### Wymagania

- Python 3.12+
- PostgreSQL 16+
- Google Cloud SDK (dla deployment)

### Lokalne uruchomienie

```bash
# Klonuj repozytorium
git clone <repo-url>
cd InvoiceTracker

# Utwórz virtual environment
python -m venv venv
source venv/bin/activate

# Zainstaluj zależności
pip install -r requirements.txt

# Skonfiguruj zmienne środowiskowe
cp .env.example .env
# Edytuj .env z własnymi wartościami

# Uruchom Cloud SQL Proxy (dla połączenia z bazą)
./cloud-sql-proxy <INSTANCE_CONNECTION_NAME>

# Zastosuj migracje
flask db upgrade

# Uruchom aplikację
python -m InvoiceTracker
# lub
gunicorn --bind 0.0.0.0:8080 wsgi:application
```

## Komendy

### Development

```bash
# Uruchom lokalnie
python -m InvoiceTracker

# Flask shell
flask shell

# Migracje bazy
flask db migrate -m "Opis zmian"
flask db upgrade
flask db downgrade
```

### CLI Commands

```bash
# Archiwizuj aktywne sprawy
flask archive-active-cases

# Test synchronizacji z custom days_ahead
flask test-sync-days <DAYS>

# Weryfikacja stanu synchronizacji
flask verify-sync-state

# Sync konfiguracji SMTP z .env do bazy
flask sync-smtp-config
```

### Deployment

```bash
# Deploy do App Engine
gcloud app deploy --quiet

# Deploy cron jobs
gcloud app deploy cron.yaml

# Logi
gcloud app logs tail -s default
```

## Konfiguracja

### Zmienne środowiskowe

```bash
# Aplikacja
SECRET_KEY=<min_32_random_chars>
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<secure_password>

# Baza danych (lokalne)
SQLALCHEMY_DATABASE_URI=postgresql://user:pass@localhost:5432/dbname

# Baza danych (App Engine)
DB_USER=postgres
DB_PASSWORD=<password>
DB_NAME=invoice_tracker
INSTANCE_CONNECTION_NAME=project:region:instance

# Szyfrowanie (32 bytes dla Fernet)
ENCRYPTION_KEY=<32_byte_key>

# SMTP per profil (przykład dla Aquatest)
AQUATEST_SMTP_SERVER=smtp.nazwa.pl
AQUATEST_SMTP_PORT=587
AQUATEST_SMTP_USERNAME=email@domain.pl
AQUATEST_SMTP_PASSWORD=<password>
AQUATEST_EMAIL_FROM=email@domain.pl
```

## 5-etapowy proces windykacji

| Etap | Domyślny offset | Opis |
|------|-----------------|------|
| 1 | -1 dzień | Przypomnienie przed terminem |
| 2 | +7 dni | Powiadomienie o upływie terminu |
| 3 | +14 dni | Wezwanie do zapłaty |
| 4 | +21 dni | Powiadomienie o zamiarze przekazania |
| 5 | +30 dni | Przekazanie do windykatora |

Offsety są konfigurowalne per profil w panelu `/settings`.

## Multi-tenancy

Każdy profil (Account) ma:
- Własny klucz API InFakt
- Własną konfigurację SMTP
- Własne harmonogramy synchronizacji i wysyłki maili
- Własne ustawienia offsetów powiadomień
- Pełną izolację danych (wszystkie queries filtrowane przez `account_id`)

## API Integration

### InFakt API

System używa warstwy abstrakcji `providers/` dla integracji z API:

```python
from InvoiceTracker.app.providers import get_provider

provider = get_provider(account)
invoices = provider.fetch_invoices(query_params={"payment_date_eq": "2025-01-15"})
client = provider.get_client_details(client_id)
```

Wzorzec Provider umożliwia łatwe dodanie innych dostawców (wFirma, Fakturownia) w przyszłości.

## Technologie

- **Backend**: Flask 2.2, SQLAlchemy 2.0, APScheduler
- **Database**: PostgreSQL 16 (Cloud SQL)
- **Frontend**: Jinja2, Bootstrap 5
- **Deployment**: Google App Engine, Cloud Scheduler
- **Security**: Fernet encryption, session-based auth

## Licencja

Proprietary - All rights reserved.
