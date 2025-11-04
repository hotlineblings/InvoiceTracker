# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

**InvoiceTracker** is a multi-tenant debt collection automation system that integrates with the InFakt invoicing API. The system automatically monitors payment deadlines, sends staged reminder emails, and manages collection cases from initial reminder to external debt collector handover.

**Key Architectural Principle**: Multi-tenancy with account isolation - each Account (company profile) has its own API credentials, SMTP settings, notification schedules, and completely isolated data.

## Development Commands

### Local Development

```bash
# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Database migrations
flask db upgrade

# Run locally (connects via Cloud SQL Proxy)
python -m InvoiceTracker.app
# OR with gunicorn
gunicorn --bind 0.0.0.0:8080 wsgi:application

# Run Flask shell for debugging
FLASK_APP=InvoiceTracker/app.py flask shell
```

### Database Operations

```bash
# Create new migration
flask db migrate -m "Description of changes"

# Apply migrations
flask db upgrade

# Rollback migration
flask db downgrade

# View current migration
flask db current
```

### Custom CLI Commands

```bash
# Archive all active cases for Aquatest before reset
flask archive-active-cases

# Test synchronization with custom days_ahead setting
flask test-sync-days <DAYS>  # e.g., flask test-sync-days 7

# Verify synchronization state (shows active cases, orphaned invoices, recent syncs)
flask verify-sync-state

# Sync SMTP configuration from .env to database
flask sync-smtp-config
```

### Deployment

```bash
# Deploy to Google App Engine
gcloud app deploy --quiet

# Deploy cron jobs
gcloud app deploy cron.yaml

# View logs
gcloud app logs tail -s default

# SSH to Cloud SQL instance
gcloud sql connect <INSTANCE_NAME> --user=postgres
```

## Architecture

### Multi-Tenancy Model

**Critical**: All database operations MUST filter by `account_id` to maintain data isolation between company profiles (Aquatest, Pozytron Szkolenia, etc.)

```
Account (Company Profile)
├── InFakt API Key (encrypted)
├── SMTP Configuration (username/password encrypted with Fernet)
├── Company Details (for email templates)
├── AccountScheduleSettings (mail hours, sync hours, fetch days)
└── NotificationSettings (5 stages with offset days)
    ├── Cases (collection cases)
    │   └── Invoice (1:1 relationship)
    ├── NotificationLog (email history)
    └── SyncStatus (sync history)
```

### Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    Google Cloud Platform                     │
│                                                              │
│  ┌──────────────┐      ┌─────────────┐      ┌────────────┐ │
│  │   App Engine │◄────►│  Cloud SQL  │      │   Cloud    │ │
│  │   (Flask)    │      │(PostgreSQL) │      │ Scheduler  │ │
│  └──────┬───────┘      └─────────────┘      └──────┬─────┘ │
│         │                                           │        │
└─────────┼───────────────────────────────────────────┼────────┘
          │                                           │
          │ /cron/run_sync (every 1 hour)            │
          └───────────────────────────────────────────┘
          ▼
┌─────────────────────────┐      ┌──────────────────┐
│   InvoiceTracker App    │      │   InFakt API     │
│                         │◄────►│  (REST API)      │
│  • APScheduler (emails) │      │                  │
│  • Smart CRON (sync)    │      │  • /invoices     │
│  • Multi-tenant SMTP    │      │  • /clients      │
└─────────────────────────┘      └──────────────────┘
```

### Key Files and Responsibilities

| File | Responsibility | Critical Aspects |
|------|----------------|------------------|
| `app.py` | Flask routes, authentication, multi-tenancy session | All routes filter by `session['current_account_id']` |
| `models.py` | SQLAlchemy models with Fernet encryption | `Account` has encrypted API keys/passwords; `Case` has unique constraint `(case_number, account_id)` |
| `scheduler.py` | APScheduler with per-account email jobs | Creates dynamic jobs based on `AccountScheduleSettings.mail_send_hour` |
| `update_db.py` | InFakt API sync (new invoices + updates) | MUST pass `account_id` to all functions; uses `Account.infakt_api_key` |
| `send_email.py` | SMTP email sender with per-account config | Uses `send_email_for_account(account, ...)` NOT global SMTP |
| `src/api/api_client.py` | InFakt API client | Accepts `api_key` parameter for multi-tenancy; NO 'fields' param in `get_client_details()` |
| `mail_templates.py` | HTML email templates (5 stages) | Uses placeholders: `{company_name}`, `{debt_amount}`, `{stage_X_date}` |
| `mail_utils.py` | Email template generator | Calls `generate_email(stage, invoice, account)` |

### Database Models (Multi-Tenancy Critical)

```python
# Account - Company profile (encrypted sensitive data)
Account(
    id, name, is_active,
    _infakt_api_key_encrypted,  # Fernet encrypted
    _smtp_username_encrypted, _smtp_password_encrypted,
    company_full_name, company_phone, company_bank_account
)

# AccountScheduleSettings - Per-account schedule config
AccountScheduleSettings(
    account_id,
    mail_send_hour, mail_send_minute, is_mail_enabled,
    sync_hour, sync_minute, is_sync_enabled,
    invoice_fetch_days_before,  # 1 for Aquatest, 7 for Pozytron
    auto_close_after_stage5
)

# Case - Collection case (UNIQUE per account)
Case(
    id, case_number, account_id,  # CONSTRAINT: UNIQUE(case_number, account_id)
    client_id, client_nip, client_company_name,
    status  # "active" | "closed_oplacone" | "closed_nieoplacone" | "archived_before_reset"
)

# Invoice - Invoice data from InFakt API (1:1 with Case)
Invoice(
    id,  # InFakt API ID (globally unique)
    invoice_number, gross_price,  # PRICES IN GROSZ (int)
    client_email, override_email,  # override_email takes precedence
    left_to_pay, paid_price, status,
    case_id  # FK to Case
)

# NotificationLog - Email send history (filtered by account_id)
NotificationLog(
    account_id,  # CRITICAL: filter all queries by this
    invoice_number, stage, mode,  # mode: "Automatyczne" | "Manualne" | "System"
    email_to, subject, body, sent_at
)

# SyncStatus - Sync execution history (filtered by account_id)
SyncStatus(
    account_id,  # CRITICAL: filter all queries by this
    sync_type,  # "new" | "update" | "full"
    processed, new_cases, updated_cases, closed_cases,
    api_calls, duration,
    # Detailed breakdown for "full" type:
    new_invoices_processed, updated_invoices_processed,
    new_sync_duration, update_sync_duration
)

# NotificationSettings - Email stage offsets (per account)
NotificationSettings(
    account_id, stage_name,  # CONSTRAINT: UNIQUE(account_id, stage_name)
    offset_days  # relative to payment_due_date
)
```

### Synchronization Logic (CRITICAL for Multi-Tenancy)

#### Smart CRON (`/cron/run_sync`)

Executed **every 1 hour** by Cloud Scheduler. Checks which accounts need sync at current UTC hour.

```python
# app.py:880 - cron_run_sync()
current_hour_utc = datetime.now(timezone.utc).hour

for account in Account.query.filter_by(is_active=True).all():
    settings = AccountScheduleSettings.get_for_account(account.id)

    if settings.is_sync_enabled and current_hour_utc == settings.sync_hour:
        # Start background thread for this account ONLY
        threading.Thread(target=background_sync, args=(app.app_context(), account.id)).start()
```

#### Invoice Fetch Logic (`sync_new_invoices`)

```python
# update_db.py:26
def sync_new_invoices(account_id):
    account = Account.query.get(account_id)
    client = InFaktAPIClient(api_key=account.infakt_api_key)  # Per-account API key

    settings = AccountScheduleSettings.get_for_account(account_id)
    days_ahead = settings.invoice_fetch_days_before  # 1 for Aquatest, 7 for Pozytron

    target_date = today + timedelta(days=days_ahead)
    query_params = {"q[payment_date_eq]": target_date.strftime("%Y-%m-%d")}

    # Fetch invoices with payment_due_date = target_date
    # Filter: status in ('sent', 'printed') only
    # For each invoice:
    #   - Create Invoice record
    #   - Fetch client details via /clients/{id}.json (NO 'fields' param!)
    #   - If left_to_pay > 0: Create Case with account_id
```

**CRITICAL**: `invoice_fetch_days_before` setting controls how far ahead to look for invoices:
- Aquatest: `1 day` - invoices due tomorrow
- Pozytron: `7 days` - invoices due in a week

#### Update Existing Cases (`update_existing_cases`)

```python
# update_db.py:245
def update_existing_cases(account_id):
    # Fetch active cases for this account ONLY
    active_cases = Case.query.filter_by(status='active', account_id=account_id).all()

    # Scan API for invoices with payment_date in range: [today - 35 days, today + 3 days]
    # For each matching invoice:
    #   - Update paid_price, status, left_to_pay
    #   - If left_to_pay <= 0: close case as "closed_oplacone"
```

### Email Sending (CRITICAL for Multi-Tenancy)

**NEVER use global SMTP settings**. Always use account-specific configuration:

```python
# WRONG - uses global SMTP
send_email(recipient, subject, body)

# CORRECT - uses account-specific SMTP
from send_email import send_email_for_account

account = Account.query.get(account_id)
send_email_for_account(account, recipient, subject, body, html=True)
```

#### Email Priority: override_email vs client_email

```python
# Invoice.get_effective_email()
def get_effective_email(self):
    return self.override_email if self.override_email else self.client_email
```

**Always use `invoice.get_effective_email()`** instead of `invoice.client_email` directly.

### APScheduler Configuration

The scheduler creates **dynamic per-account jobs** at startup:

```python
# scheduler.py:181 - start_scheduler()
for account in Account.query.filter_by(is_active=True).all():
    settings = AccountScheduleSettings.get_for_account(account.id)

    if settings.is_mail_enabled:
        scheduler.add_job(
            func=lambda acc_id=account.id: run_mail_for_single_account(app, acc_id),
            trigger='cron',
            hour=settings.mail_send_hour,  # UTC!
            minute=settings.mail_send_minute,
            id=f'mail_account_{account.id}'
        )
```

**CRITICAL**: Times are stored in **UTC** but displayed in **Europe/Warsaw** (CET/CEST) in UI.

### Staged Notification System

5-stage collection process with configurable timing (stored in `NotificationSettings`):

| Stage | Default Offset | Typical Action |
|-------|----------------|----------------|
| Stage 1: "Przypomnienie o zbliżającym się terminie płatności" | **-1 day** | Friendly reminder before due date |
| Stage 2: "Powiadomienie o upływie terminu płatności" | **+7 days** | Payment overdue notice |
| Stage 3: "Wezwanie do zapłaty" | **+14 days** | Formal demand letter |
| Stage 4: "Powiadomienie o zamiarze skierowania..." | **+21 days** | Warning of external action |
| Stage 5: "Przekazanie sprawy do windykatora zewnętrznego" | **+30 days** | Handover to collector (auto-closes case) |

**Offset Logic**:
- Negative = before `payment_due_date`
- Positive = after `payment_due_date`
- Calculated as: `days_diff = (today - payment_due_date).days`

**Auto-Close**: If `AccountScheduleSettings.auto_close_after_stage5 = True`, case status changes to `"closed_nieoplacone"` after stage 5 email is sent.

## Important Technical Details

### Price Storage: GROSZ not ZŁOTY

**CRITICAL**: All monetary values in database are stored in **grosz (cents)** as INTEGER to avoid floating-point rounding errors.

```python
# WRONG
invoice.gross_price = 150.50  # Float - NEVER!

# CORRECT
invoice.gross_price = 15050  # 150.50 PLN = 15050 grosz

# Display to user
debt_zl = invoice.gross_price / 100.0  # 15050 / 100 = 150.50
formatted = f"{debt_zl:.2f} zł"  # "150.50 zł"

# Jinja2 template
{{ "%.2f"|format(invoice.gross_price / 100) }}
```

### InFakt API Quirks

1. **NO 'fields' parameter in `/clients/{id}.json`**
   ```python
   # WRONG - returns HTTP 500
   response = client.get(f"/clients/{id}.json", params={"fields": "email,nip"})

   # CORRECT - fetch all fields
   response = client.get(f"/clients/{id}.json")  # NO params
   ```

2. **Date format**: Always `"YYYY-MM-DD"` string in API, convert to `date` object for database

3. **Client data separate from invoice**: Invoice API returns only `client_id`, must call `/clients/{id}.json` separately

### Authentication & Session Management

```python
# Login flow
POST /login → session['logged_in'] = True → redirect to /select_account

# Profile selection
/select_account → session['current_account_id'] = X
                → session['current_account_name'] = "Company Name"
                → redirect to /

# Profile switching (navbar dropdown)
/switch_account/<account_id> → Update session → redirect to /

# Before every request
@app.before_request checks:
1. Is user logged in? (session['logged_in'])
2. Is profile selected? (session['current_account_id'])
```

**CRITICAL**: All routes (except login/static/cron) MUST check `session['current_account_id']` and filter all DB queries by `account_id`.

### Database Connection Configuration

```python
# app.py:65
if os.path.exists('/cloudsql'):  # App Engine
    unix_socket_path = f'/cloudsql/{instance_connection_name}'
    db_uri = f"postgresql+psycopg2://{user}:{pass}@/{db}?host={unix_socket_path}"
else:  # Local development (Cloud SQL Proxy)
    db_uri = os.environ.get('SQLALCHEMY_DATABASE_URI')
```

### Encryption (Fernet)

Sensitive credentials are encrypted using Fernet symmetric encryption:

```python
# models.py - Account
@property
def infakt_api_key(self):
    cipher = self._get_cipher()  # Uses ENCRYPTION_KEY env var
    return cipher.decrypt(self._infakt_api_key_encrypted).decode()

@infakt_api_key.setter
def infakt_api_key(self, value):
    cipher = self._get_cipher()
    self._infakt_api_key_encrypted = cipher.encrypt(value.encode())
```

**CRITICAL**: Set `ENCRYPTION_KEY` environment variable (32 bytes). Use `flask sync-smtp-config` to encrypt and store credentials from `.env` to database.

## Common Patterns

### Adding a New Route

```python
@app.route('/my_route')
def my_route():
    # 1. Check account selection
    account_id = session.get('current_account_id')
    if not account_id:
        flash("Wybierz profil.", "warning")
        return redirect(url_for('select_account'))

    # 2. Filter all queries by account_id
    cases = Case.query.filter_by(account_id=account_id).all()

    # 3. For invoices, JOIN through Case to filter by account
    invoices = (Invoice.query
                .join(Case, Invoice.case_id == Case.id)
                .filter(Case.account_id == account_id)
                .all())

    return render_template('my_template.html', cases=cases)
```

### Sending Emails (Manual or Automatic)

```python
# 1. Get account and invoice
account = Account.query.get(account_id)
invoice = Invoice.query.get(invoice_id)

# 2. Use effective email (respects override)
recipient = invoice.get_effective_email()
if not recipient or '@' not in recipient:
    return error("Invalid email")

# 3. Generate email from template
subject, body_html = generate_email(stage_name, invoice, account)

# 4. Send using account's SMTP config
send_email_for_account(account, recipient, subject, body_html, html=True)

# 5. Log the notification
log_entry = NotificationLog(
    account_id=account.id,
    invoice_number=invoice.invoice_number,
    email_to=recipient,
    subject=subject,
    body=body_html,
    stage=stage_name,
    mode="Manualne",  # or "Automatyczne"
    sent_at=datetime.utcnow()
)
db.session.add(log_entry)
db.session.commit()
```

### Creating Database Migrations

```bash
# 1. Modify models.py
# 2. Generate migration
flask db migrate -m "Add new_column to Invoice"

# 3. Review generated migration in migrations/versions/
# 4. Edit if necessary (e.g., set default values for existing rows)

# 5. Apply migration
flask db upgrade

# 6. Test locally BEFORE deploying to production
```

## Testing Checklist

Before deploying changes:

1. **Multi-Tenancy Isolation**: Test with 2+ accounts, verify no data leakage
2. **Email Sending**: Test with both `client_email` and `override_email` set
3. **Synchronization**: Run `flask test-sync-days <DAYS>` to verify invoice fetching
4. **Stage Transitions**: Send manual notifications for all 5 stages, verify auto-close
5. **Database Queries**: Check all queries include `account_id` filter (use `EXPLAIN ANALYZE`)
6. **Price Display**: Verify all money amounts show correctly (grosz → zł conversion)
7. **Scheduler Jobs**: Check logs for correct UTC→CET time conversions

## Environment Variables Reference

### Required for All Environments

```bash
# Application
SECRET_KEY=<min_32_random_chars>
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<secure_password>

# Database (Local)
SQLALCHEMY_DATABASE_URI=postgresql://user:pass@localhost:5432/dbname

# Database (App Engine - uses unix socket)
DB_USER=postgres
DB_PASSWORD=<password>
DB_NAME=invoice_tracker
INSTANCE_CONNECTION_NAME=project-id:region:instance-name

# Encryption (32 bytes for Fernet)
ENCRYPTION_KEY=<32_byte_key>

# Legacy SMTP (fallback - prefer per-account settings in DB)
SMTP_SERVER=smtp.nazwa.pl
SMTP_PORT=587
SMTP_USERNAME=email@domain.pl
SMTP_PASSWORD=<smtp_password>
EMAIL_FROM=email@domain.pl

# Per-Account SMTP (for flask sync-smtp-config)
AQUATEST_SMTP_SERVER=smtp.nazwa.pl
AQUATEST_SMTP_PORT=587
AQUATEST_SMTP_USERNAME=aquatest@domain.pl
AQUATEST_SMTP_PASSWORD=<password>
AQUATEST_EMAIL_FROM=aquatest@domain.pl

POZYTRON_SMTP_SERVER=smtp.nazwa.pl
POZYTRON_SMTP_PORT=587
POZYTRON_SMTP_USERNAME=pozytron@domain.pl
POZYTRON_SMTP_PASSWORD=<password>
POZYTRON_EMAIL_FROM=pozytron@domain.pl

# Per-Account InFakt API Keys (stored encrypted in DB after setup)
AQUATEST_INFAKT_API_KEY=<api_key>
POZYTRON_INFAKT_API_KEY=<api_key>
```

## Troubleshooting

### "Brak dostępnych profili" after login

**Cause**: No active accounts in database.

**Fix**: Create account via Flask shell:
```python
from InvoiceTracker.app import create_app
from InvoiceTracker.models import db, Account

app = create_app()
with app.app_context():
    account = Account(name="Company Name", is_active=True)
    account.infakt_api_key = "your_api_key"
    account.smtp_server = "smtp.nazwa.pl"
    account.smtp_port = 587
    account.smtp_username = "email@domain.pl"
    account.smtp_password = "password"
    account.email_from = "email@domain.pl"
    db.session.add(account)
    db.session.commit()
```

### Synchronization returns 0 new invoices

**Possible causes**:
1. `invoice_fetch_days_before` setting incorrect (check `/settings` page)
2. API key invalid or expired (check `Account.infakt_api_key`)
3. No invoices with matching `payment_due_date` in InFakt

**Debug**: Use `flask test-sync-days <DAYS>` to test different fetch periods.

### Emails not sending

**Checklist**:
1. `AccountScheduleSettings.is_mail_enabled = True`?
2. SMTP credentials correct in `Account` table (not `.env`)?
3. Scheduler jobs created? Check logs for "✅ Job dodany: <account>"
4. Firewall blocking port 587?
5. Invoice has `client_email` or `override_email` set?

### Database migrations fail

**Common issues**:
1. **Duplicate migration**: Delete duplicate file in `migrations/versions/`
2. **Constraint violation**: Add `nullable=True` temporarily, run migration, then populate data, then add constraint
3. **Out of sync**: `flask db stamp head` then `flask db migrate` to regenerate

## Performance Optimization

### Query Optimization (Already Implemented)

```python
# OPTIMIZED: Single query with JOIN
cases = (Case.query
         .options(joinedload(Case.invoice))
         .filter_by(account_id=account_id)
         .all())

# SLOW: N+1 query problem
cases = Case.query.filter_by(account_id=account_id).all()
for case in cases:
    invoice = case.invoice  # Triggers separate query for EACH case!
```

### Batch Processing

Scheduler processes invoices in batches of 100 to avoid memory issues with large datasets:

```python
# scheduler.py:75
batch_size = 100
offset = 0

while True:
    active_invoices = (Invoice.query
                       .offset(offset)
                       .limit(batch_size)
                       .all())
    if not active_invoices:
        break
    # Process batch...
    offset += batch_size
```

## Additional Notes

- **Logging**: Use `log.info()`, `log.warning()`, `log.error()` not `print()` (except in scheduler for immediate output)
- **Transactions**: Always wrap multi-step DB operations in try/except with `db.session.rollback()` on error
- **UTC vs Local Time**: Database stores UTC, display converts to Europe/Warsaw timezone in templates
- **Bootstrap Icons**: UI uses Bootstrap Icons 1.11.0 (https://icons.getbootstrap.com/)
- **Flask-Migrate**: Alembic migrations stored in `migrations/versions/`
