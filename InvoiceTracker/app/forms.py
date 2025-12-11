"""
Formularze WTForms z ochroną CSRF.
Wszystkie formularze POST w aplikacji dziedziczą po FlaskForm.
"""
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, IntegerField, HiddenField
from wtforms.fields import EmailField
from wtforms.validators import DataRequired, Email, Optional, NumberRange, Length, EqualTo


# =============================================================================
# AUTH - Formularze autoryzacji
# =============================================================================

class LoginForm(FlaskForm):
    """Formularz logowania uzytkownika."""
    email = EmailField(
        'Email',
        validators=[
            DataRequired(message="Email jest wymagany"),
            Email(message="Nieprawidlowy format email")
        ]
    )
    password = PasswordField('Hasło', validators=[DataRequired(message="Hasło jest wymagane")])


class SwitchAccountForm(FlaskForm):
    """Formularz przełączania między profilami (konta firmowe)."""
    account_id = HiddenField('Account ID', validators=[DataRequired()])


class RegistrationForm(FlaskForm):
    """
    Formularz rejestracji nowego uzytkownika i firmy.
    Tworzy User + Account w jednej transakcji.
    """
    email = EmailField(
        'Email',
        validators=[
            DataRequired(message="Email jest wymagany"),
            Email(message="Nieprawidlowy format email")
        ]
    )
    password = PasswordField(
        'Haslo',
        validators=[
            DataRequired(message="Haslo jest wymagane"),
            Length(min=8, message="Haslo musi miec minimum 8 znakow")
        ]
    )
    confirm_password = PasswordField(
        'Potwierdz haslo',
        validators=[
            DataRequired(message="Potwierdzenie hasla jest wymagane"),
            EqualTo('password', message="Hasla musza byc identyczne")
        ]
    )
    company_name = StringField(
        'Nazwa firmy',
        validators=[
            DataRequired(message="Nazwa firmy jest wymagana"),
            Length(min=2, max=200, message="Nazwa firmy musi miec 2-200 znakow")
        ]
    )
    nip = StringField(
        'NIP (opcjonalnie)',
        validators=[Optional(), Length(max=20)]
    )


# =============================================================================
# SETTINGS - Formularze ustawień
# =============================================================================

class SettingsForm(FlaskForm):
    """
    Zunifikowany formularz ustawień profilu.

    Uwaga: Stage offsets (NotificationSettings) są dynamiczne i obsługiwane
    przez request.form po walidacji CSRF głównego formularza.
    """
    # === Sekcja 1: API & Integracje ===
    infakt_api_key = PasswordField('InFakt API Key', validators=[Optional()])

    # === Sekcja 2: Wysyłka powiadomień ===
    is_mail_enabled = BooleanField('Wysyłka włączona')
    mail_send_hour = HiddenField()   # UTC - ustawiane przez JavaScript
    mail_send_minute = HiddenField()  # UTC - ustawiane przez JavaScript

    # === Sekcja 3: Synchronizacja ===
    is_sync_enabled = BooleanField('Synchronizacja włączona')
    sync_hour = HiddenField()        # UTC - ustawiane przez JavaScript
    sync_minute = HiddenField()       # UTC - ustawiane przez JavaScript
    invoice_fetch_days_before = IntegerField(
        'Dni przed terminem',
        validators=[Optional(), NumberRange(min=1, max=30, message="Wartość musi być między 1 a 30")]
    )

    # === Sekcja 4: Dane firmowe ===
    company_full_name = StringField(
        'Pełna nazwa firmy',
        validators=[Optional(), Length(max=500)]
    )
    company_phone = StringField(
        'Telefon kontaktowy',
        validators=[Optional(), Length(max=20)]
    )
    company_email_contact = EmailField(
        'Email kontaktowy',
        validators=[Optional(), Email(message="Nieprawidłowy format email")]
    )
    company_bank_account = StringField(
        'Numer konta bankowego',
        validators=[Optional(), Length(max=50)]
    )

    # === Sekcja 5: Opcje dodatkowe ===
    auto_close_after_stage5 = BooleanField('Auto-zamknij sprawę po Stage 5')


class EmailUpdateForm(FlaskForm):
    """Formularz aktualizacji override_email dla faktury (AJAX)."""
    new_email = EmailField(
        'Nowy email',
        validators=[Optional(), Email(message="Nieprawidłowy format email")]
    )


# =============================================================================
# ACTIONS - Formularze akcji (tylko CSRF + hidden fields)
# =============================================================================

class ManualSyncForm(FlaskForm):
    """
    Formularz ręcznej synchronizacji.
    Pusty formularz - służy tylko do ochrony CSRF dla akcji POST.
    """
    pass


class MarkPaidForm(FlaskForm):
    """Formularz oznaczania faktury jako opłaconej."""
    invoice_id = HiddenField('Invoice ID', validators=[DataRequired()])


class SendManualForm(FlaskForm):
    """Formularz ręcznej wysyłki powiadomienia."""
    case_number = HiddenField('Case Number', validators=[DataRequired()])
    stage = HiddenField('Stage', validators=[DataRequired()])


class ReopenCaseForm(FlaskForm):
    """Formularz wznawiania zamkniętej sprawy."""
    case_number = HiddenField('Case Number', validators=[DataRequired()])
