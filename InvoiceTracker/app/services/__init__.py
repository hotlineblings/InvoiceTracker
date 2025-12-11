"""
Serwisy aplikacji.
"""
# Email services
from .send_email import send_email, send_email_for_account, close_smtp_connection
from .mail_templates import MAIL_TEMPLATES
from .mail_utils import generate_email

# Sync services
from .update_db import sync_new_invoices, update_existing_cases, run_full_sync
from .scheduler import run_mail_for_single_account

# Business logic services (NEW - Service Layer)
from . import case_service
from . import finance_service
from . import notification_service
from . import payment_service
from . import diagnostic_service
