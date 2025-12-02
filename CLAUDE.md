# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

**InvoiceTracker** is a multi-tenant debt collection automation system integrating with the InFakt invoicing API. It monitors payment deadlines, sends 5-stage reminder emails, and manages collection cases from initial reminder to external debt collector handover.

**Core Principle**: Multi-tenancy with complete account isolation. Each Account (company profile) has its own API credentials, SMTP settings, notification schedules, and isolated data. All database queries MUST filter by `account_id`.

## Development Commands

```bash
# Activate environment and run locally
source venv/bin/activate
pip install -r requirements.txt
python -m InvoiceTracker  # or: gunicorn --bind 0.0.0.0:8080 wsgi:application

# Database migrations
flask db migrate -m "Description"
flask db upgrade
flask db downgrade

# CLI diagnostics
flask archive-active-cases                    # Archive Aquatest cases before reset
flask test-sync-days <DAYS>                   # Test sync with custom days_ahead
flask verify-sync-state                       # Show active cases, orphaned invoices
flask sync-smtp-config                        # Sync SMTP from .env to database
flask normalize-all-notification-settings    # Fix NotificationSettings for all profiles

# Deployment (GCP App Engine)
gcloud app deploy --quiet
gcloud app deploy cron.yaml
gcloud app logs tail -s default
```

## Architecture

### Application Factory Pattern

Entry point: `InvoiceTracker/app/__init__.py:create_app()` - configures Flask, extensions, blueprints, CLI, middleware, and scheduler.

### Blueprints (Routes)

| Blueprint | File | Responsibility |
|-----------|------|----------------|
| `auth` | `blueprints/auth.py` | Login, profile selection, session management |
| `cases` | `blueprints/cases.py` | Active/closed cases, client cases, case details, manual notifications |
| `settings` | `blueprints/settings.py` | Notification offsets, schedule settings, company details |
| `sync` | `blueprints/sync.py` | CRON endpoint, manual sync, sync status, mail diagnostics |
| `tasks` | `blueprints/tasks.py` | Cloud Tasks handler for async sync execution |

### Services

| Service | Responsibility |
|---------|----------------|
| `update_db.py` | `sync_new_invoices()`, `update_existing_cases()`, `run_full_sync()` |
| `scheduler.py` | APScheduler with per-account email jobs |
| `send_email.py` | Multi-tenant SMTP, `send_email_for_account(account, ...)` |
| `case_service.py` | Case business logic |
| `cloud_tasks.py` | Cloud Tasks / local HTTP queue for async operations |
| `diagnostic_service.py` | Mail debug dry-run |

### Provider Abstraction

`providers/base.py` defines `InvoiceProvider` ABC with normalized interface:
- `fetch_invoices(query_params, offset, limit)` → `list[NormalizedInvoice]`
- `get_client_details(client_id)` → `NormalizedClient`

`providers/infakt.py` implements InFakt API. Factory: `get_provider(account)`.

## Critical Patterns

### Multi-Tenancy Filtering

**ALWAYS** filter queries by `account_id`:

```python
# Standard models (Case, NotificationLog, SyncStatus)
cases = Case.query.filter_by(account_id=account_id, status='active').all()

# Invoice through Case JOIN
invoices = (Invoice.query
            .join(Case, Invoice.case_id == Case.id)
            .filter(Case.account_id == account_id)
            .all())

# Account queries (no account_id) - use sudo() context manager
from ..tenant_context import sudo
with sudo():
    account = Account.query.get(account_id)
```

### Price Storage: GROSZ (cents)

All monetary values stored as INTEGER in grosz to avoid floating-point errors:

```python
# Store: 150.50 PLN = 15050 grosz
invoice.gross_price = 15050

# Display in template
{{ "%.2f"|format(invoice.gross_price / 100) }} zł
```

### Email Recipient: Effective Email

Always use `invoice.get_effective_email()` - respects `override_email` when set:

```python
recipient = invoice.get_effective_email()  # override_email or client_email
send_email_for_account(account, recipient, subject, body_html, html=True)
```

### Per-Account SMTP (Never Global)

```python
# CORRECT - uses account-specific SMTP
from .services.send_email import send_email_for_account
send_email_for_account(account, recipient, subject, body, html=True)

# WRONG - would use global SMTP
send_email(recipient, subject, body)  # DO NOT USE
```

### Fernet Encryption

`Account` model encrypts sensitive fields (API keys, SMTP credentials) using Fernet. Access via properties that auto-decrypt:

```python
account.infakt_api_key   # Returns decrypted key
account.smtp_password    # Returns decrypted password
```

Requires `ENCRYPTION_KEY` env var (32 bytes).

## Database Models

| Model | Key Fields | Multi-tenant |
|-------|------------|--------------|
| `Account` | `name`, encrypted API/SMTP | N/A (is tenant) |
| `AccountScheduleSettings` | `mail_send_hour`, `sync_hour`, `invoice_fetch_days_before` | `account_id` |
| `NotificationSettings` | `stage_name`, `offset_days` | `account_id` |
| `Case` | `case_number`, `status`, `client_*` | `account_id` + UNIQUE constraint |
| `Invoice` | `invoice_number`, `gross_price`, `left_to_pay`, `override_email` | via `case_id` JOIN |
| `NotificationLog` | `stage`, `mode`, `email_to` | `account_id` |
| `SyncStatus` | `sync_type`, `processed`, `duration` | `account_id` |

**Constraint**: `UNIQUE(case_number, account_id)` on Case.

## Synchronization Flow

1. **Cloud Scheduler** triggers `/cron/run_sync` every hour
2. **Smart CRON** checks which accounts have `sync_hour == current_hour`
3. **Cloud Tasks** queued for matching accounts → `tasks_bp.run_sync_for_account`
4. **run_full_sync()** calls:
   - `sync_new_invoices()` - fetch invoices with `payment_due_date = today + invoice_fetch_days_before`
   - `update_existing_cases()` - update active cases, close paid ones

### Per-Account Settings

| Setting | Aquatest | Pozytron |
|---------|----------|----------|
| `invoice_fetch_days_before` | 1 day | 7 days |

## 5-Stage Notification System

| Stage | Default Offset | Action |
|-------|----------------|--------|
| 1: Przypomnienie o zbliżającym się terminie płatności | -1 day | Reminder before due |
| 2: Powiadomienie o upływie terminu płatności | +7 days | Overdue notice |
| 3: Wezwanie do zapłaty | +14 days | Formal demand |
| 4: Powiadomienie o zamiarze skierowania... | +21 days | Warning |
| 5: Przekazanie sprawy do windykatora zewnętrznego | +30 days | Handover (auto-close if enabled) |

Canonical stages defined in `constants.py:CANONICAL_NOTIFICATION_STAGES`.

## InFakt API Notes

- **NO 'fields' parameter** in `/clients/{id}.json` - returns HTTP 500
- Client data fetched separately from invoice (invoice only has `client_id`)
- Provider normalizes all responses to common structure

## Environment Variables

```bash
SECRET_KEY=<min_32_chars>
ENCRYPTION_KEY=<32_bytes_for_fernet>
ADMIN_USERNAME=admin
ADMIN_PASSWORD=<password>

# Local DB (Cloud SQL Proxy)
SQLALCHEMY_DATABASE_URI=postgresql://user:pass@localhost:5432/dbname

# App Engine DB
DB_USER=postgres
DB_PASSWORD=<password>
DB_NAME=invoice_tracker
INSTANCE_CONNECTION_NAME=project:region:instance

# Per-account SMTP (synced to DB via flask sync-smtp-config)
AQUATEST_SMTP_SERVER=smtp.nazwa.pl
AQUATEST_SMTP_PORT=587
AQUATEST_SMTP_USERNAME=email@domain.pl
AQUATEST_SMTP_PASSWORD=<password>
AQUATEST_EMAIL_FROM=email@domain.pl
# Similar for POZYTRON_*
```

## Timezone Handling

- **Database**: All timestamps stored in UTC
- **UI Display**: Converted to `Europe/Warsaw` (CET/CEST)
- **Scheduler**: APScheduler jobs use UTC hours from `AccountScheduleSettings`
