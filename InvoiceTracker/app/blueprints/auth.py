"""
Blueprint autoryzacji.
Logowanie, wylogowanie, wybór profilu.

UPDATED: Integracja z Flask-Login (User model zamiast .env credentials).
"""
import os
import requests
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, session, request
from flask_login import login_user, logout_user, login_required, current_user

from ..extensions import db
from ..models import Account, User, AccountScheduleSettings, NotificationSettings
from ..forms import LoginForm, SwitchAccountForm, RegistrationForm

import logging
log = logging.getLogger(__name__)

# reCAPTCHA Enterprise configuration
RECAPTCHA_SITE_KEY = os.getenv('RECAPTCHA_SITE_KEY', '6LcIVh8sAAAAADYgtfnv0Q9S_S-s4XgRBNlzk9_z')
RECAPTCHA_API_KEY = os.getenv('RECAPTCHA_API_KEY', '')
RECAPTCHA_PROJECT_ID = os.getenv('RECAPTCHA_PROJECT_ID', 'invoicetracker-451108')


def verify_recaptcha_enterprise(token: str, action: str = 'REGISTER') -> bool:
    """
    Weryfikacja tokenu reCAPTCHA Enterprise.

    Args:
        token: Token z formularza (g-recaptcha-response)
        action: Oczekiwana akcja (np. 'REGISTER')

    Returns:
        True jeśli weryfikacja przeszła pomyślnie, False w przeciwnym razie
    """
    if not RECAPTCHA_API_KEY:
        log.warning("[reCAPTCHA] API Key nie skonfigurowany - pomijam weryfikację")
        return True  # Skip verification if not configured

    try:
        url = f"https://recaptchaenterprise.googleapis.com/v1/projects/{RECAPTCHA_PROJECT_ID}/assessments?key={RECAPTCHA_API_KEY}"

        payload = {
            "event": {
                "token": token,
                "expectedAction": action,
                "siteKey": RECAPTCHA_SITE_KEY
            }
        }

        response = requests.post(url, json=payload, timeout=10)
        result = response.json()

        log.debug(f"[reCAPTCHA] Response: {result}")

        # Sprawdź czy token jest ważny
        if not result.get('tokenProperties', {}).get('valid', False):
            log.warning(f"[reCAPTCHA] Invalid token: {result.get('tokenProperties', {}).get('invalidReason')}")
            return False

        # Sprawdź score (0.0 = bot, 1.0 = człowiek)
        score = result.get('riskAnalysis', {}).get('score', 0)
        if score < 0.5:
            log.warning(f"[reCAPTCHA] Low score: {score}")
            return False

        log.info(f"[reCAPTCHA] Verification passed, score: {score}")
        return True

    except Exception as e:
        log.error(f"[reCAPTCHA] Verification error: {e}")
        return False  # Fail closed - block on error

auth_bp = Blueprint('auth', __name__)


def _smart_redirect_after_auth():
    """
    Helper: Inteligentne przekierowanie po autentykacji.

    - 0 kont: wyloguj (brak dostepu)
    - 1 konto: automatyczny wybor i dashboard
    - >1 kont: ekran wyboru profilu
    """
    accounts = current_user.get_accessible_accounts()

    if not accounts:
        flash("Brak dostepnych profili.", "warning")
        return redirect(url_for('auth.logout'))

    if len(accounts) == 1:
        # Jedno konto - automatyczny wybor i dashboard
        account = accounts[0]
        session['current_account_id'] = account.id
        session['current_account_name'] = account.name
        return redirect(url_for('cases.active_cases'))

    # Wiele kont - wybor profilu
    return redirect(url_for('auth.select_account'))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Logowanie uzytkownika."""
    # Redirect if already logged in
    if current_user.is_authenticated:
        return _smart_redirect_after_auth()

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()

        if user and user.check_password(form.password.data):
            if not user.is_active:
                flash("Konto jest dezaktywowane.", "danger")
                return render_template('login.html', form=form)

            # Flask-Login: Log in the user
            login_user(user, remember=True)

            # Update last login timestamp
            user.last_login_at = datetime.utcnow()
            db.session.commit()

            # BACKWARD COMPATIBILITY: Set legacy session key
            session['logged_in'] = True

            flash("Zalogowano.", "success")
            # SMART REDIRECT zamiast stalego select_account
            return _smart_redirect_after_auth()
        else:
            flash("Nieprawidlowy email lub haslo.", "danger")

    return render_template('login.html', form=form)


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    """
    Rejestracja nowego uzytkownika i firmy.

    ATOMOWA TRANSAKCJA:
    1. User (email + password)
    2. Account (nazwa firmy, bez API/SMTP)
    3. account_users (powiazanie)
    4. AccountScheduleSettings (domyslne, wylaczone)
    5. NotificationSettings (5 etapow via normalize_for_account)
    """
    if current_user.is_authenticated:
        return redirect(url_for('cases.active_cases'))

    form = RegistrationForm()

    if form.validate_on_submit():
        # Weryfikacja reCAPTCHA Enterprise
        recaptcha_token = request.form.get('g-recaptcha-response', '')
        if not verify_recaptcha_enterprise(recaptcha_token, 'REGISTER'):
            flash("Weryfikacja reCAPTCHA nie powiodła się. Spróbuj ponownie.", "danger")
            return render_template('register.html', form=form)

        # Walidacja unikalnosci
        if User.query.filter_by(email=form.email.data).first():
            flash("Ten email jest juz zarejestrowany.", "danger")
            return render_template('register.html', form=form)

        if Account.query.filter_by(name=form.company_name.data).first():
            flash("Firma o tej nazwie juz istnieje.", "danger")
            return render_template('register.html', form=form)

        try:
            # === ATOMOWA TRANSAKCJA ===

            # 1. Utworz User
            user = User(email=form.email.data)
            user.password = form.password.data
            db.session.add(user)

            # 2. Utworz Account (bez API/SMTP - uzupelni w Settings)
            account = Account(
                name=form.company_name.data,
                provider_type='infakt'
                # Pozostale pola NULL - uzupelni w Settings
            )
            # Opcjonalnie: zapisz NIP jesli podany
            if form.nip.data:
                account.company_full_name = f"NIP: {form.nip.data}"

            db.session.add(account)
            db.session.flush()  # Uzyskaj account.id

            # 3. Powiazanie User <-> Account
            user.accounts.append(account)

            # 4. Domyslne AccountScheduleSettings
            schedule_settings = AccountScheduleSettings(
                account_id=account.id,
                is_mail_enabled=False,  # Wylaczone do czasu konfiguracji SMTP
                is_sync_enabled=False   # Wylaczone do czasu konfiguracji API
            )
            db.session.add(schedule_settings)

            # 5. Domyslne NotificationSettings (5 etapow)
            NotificationSettings.normalize_for_account(account.id)

            db.session.commit()

            # === KONIEC TRANSAKCJI ===

            log.info(f"[register] Utworzono konto: User={user.email}, Account={account.name}")

            # 6. Automatyczne logowanie
            login_user(user, remember=True)
            session['logged_in'] = True

            # 7. Smart Redirect (1 konto = prosto do settings)
            session['current_account_id'] = account.id
            session['current_account_name'] = account.name

            flash(f"Konto '{account.name}' zostalo utworzone! Uzupelnij konfiguracjie API.", "success")
            return redirect(url_for('settings.settings_view'))

        except Exception as e:
            db.session.rollback()
            log.error(f"Registration error: {e}", exc_info=True)
            flash("Blad podczas rejestracji. Sprobuj ponownie.", "danger")

    return render_template('register.html', form=form)


@auth_bp.route('/select_account')
@login_required
def select_account():
    """
    Wybor profilu po zalogowaniu.

    UWAGA: Auto-select dla 1 konta jest teraz w _smart_redirect_after_auth().
    Ten endpoint jest dla multi-account users.
    """
    accounts = current_user.get_accessible_accounts()

    if not accounts:
        flash("Brak dostepnych profili. Skontaktuj sie z administratorem.", "warning")
        return redirect(url_for('auth.logout'))

    switch_form = SwitchAccountForm()
    return render_template('select_account.html', accounts=accounts, switch_form=switch_form)


@auth_bp.route('/switch_account', methods=['POST'])
@login_required
def switch_account():
    """Przełączanie między profilami (POST z CSRF)."""
    form = SwitchAccountForm()

    if form.validate_on_submit():
        account_id = int(form.account_id.data)

        # SECURITY: Verify user has access to this account
        if not current_user.has_access_to_account(account_id):
            flash("Brak dostępu do tego profilu.", "danger")
            return redirect(url_for('auth.select_account'))

        account = Account.query.filter_by(id=account_id, is_active=True).first()
        if not account:
            flash("Nieprawidłowe konto.", "danger")
            return redirect(url_for('auth.select_account'))

        session['current_account_id'] = account.id
        session['current_account_name'] = account.name
        flash(f'Przełączono na profil: {account.name}', 'success')
        return redirect(url_for('cases.active_cases'))

    # Walidacja formularza nie powiodła się
    log.warning(f"[switch_account] Form validation failed: {form.errors}")
    flash("Błąd wyboru profilu. Spróbuj ponownie.", "danger")
    return redirect(url_for('auth.select_account'))


@auth_bp.route('/logout')
def logout():
    """Wylogowanie."""
    # Flask-Login: Log out the user
    logout_user()

    # Clear all session data
    session.pop('logged_in', None)
    session.pop('current_account_id', None)
    session.pop('current_account_name', None)

    flash("Wylogowano.", "success")
    return redirect(url_for('auth.login'))
