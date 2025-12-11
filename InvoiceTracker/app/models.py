"""
Modele SQLAlchemy aplikacji.
Wszystkie modele dla multi-tenant systemu windykacji.
"""
from datetime import datetime
from cryptography.fernet import Fernet
from collections import OrderedDict
import base64
import json
import logging
import os

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from .extensions import db
from .constants import CANONICAL_NOTIFICATION_STAGES


class Case(db.Model):
    """
    Model Case – reprezentuje sprawę windykacyjną pojedynczej faktury.
    Numer sprawy to numer faktury.
    Status może być: "active", "closed_oplacone", "closed_nieoplacone".

    MULTI-TENANCY: case_number jest unique PER ACCOUNT (nie globalnie).
    Constraint: UNIQUE(case_number, account_id)
    """
    id = db.Column(db.Integer, primary_key=True)
    case_number = db.Column(db.String(50), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False, index=True)
    client_id = db.Column(db.String(50), nullable=False)
    client_nip = db.Column(db.String(50), nullable=True)
    client_company_name = db.Column(db.String(200), nullable=True)
    status = db.Column(db.String(50), default="active")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # MULTI-TENANCY: Compound unique constraint per account
    __table_args__ = (
        db.UniqueConstraint('case_number', 'account_id', name='uq_case_number_account'),
    )

    # Relacja 1:1 – każda sprawa odpowiada jednej fakturze
    invoice = db.relationship('Invoice', backref='case', uselist=False)

    def __repr__(self):
        return f'<Case {self.case_number} for client {self.client_id}>'


class Invoice(db.Model):
    """
    Model Invoice – przechowuje dane faktury pobrane z API inFakt
    oraz dane klienta. Jest powiązany (1:1) ze sprawą windykacyjną (Case).

    MULTI-TENANCY: Ma własne account_id dla bezpośredniej izolacji danych.
    Zarejestrowany w TENANT_MODELS dla automatycznego filtrowania.
    """
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False, index=True)
    invoice_number = db.Column(db.String(50))
    invoice_date = db.Column(db.Date)
    payment_due_date = db.Column(db.Date)
    gross_price = db.Column(db.Integer)  # wartość brutto w groszach
    status = db.Column(db.String(50))    # np. "sent", "printed", "paid"
    debt_status = db.Column(db.String(200))
    client_id = db.Column(db.String(50))
    client_company_name = db.Column(db.String(200))
    client_email = db.Column(db.String(100))
    override_email = db.Column(db.String(100), nullable=True)  # Ręcznie ustawiony email przez admina
    client_nip = db.Column(db.String(50))
    client_address = db.Column(db.String(255))
    currency = db.Column(db.String(10))
    paid_price = db.Column(db.Integer, default=0)
    notes = db.Column(db.Text)
    payment_method = db.Column(db.String(50))
    sale_date = db.Column(db.Date)
    paid_date = db.Column(db.Date)
    net_price = db.Column(db.Integer)
    tax_price = db.Column(db.Integer)
    left_to_pay = db.Column(db.Integer)
    case_id = db.Column(db.Integer, db.ForeignKey('case.id'), nullable=True)

    def get_effective_email(self):
        """
        Zwraca email do użycia dla powiadomień:
        - Jeśli administrator ustawił override_email, użyj go
        - W przeciwnym razie użyj client_email z API
        """
        return self.override_email if self.override_email else self.client_email

    def __repr__(self):
        return f'<Invoice {self.invoice_number} for client {self.client_id}>'


class NotificationLog(db.Model):
    """
    Model NotificationLog – zapisuje historię wysłanych powiadomień (e-maili).
    """
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False, index=True)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    client_id = db.Column(db.String(50))
    invoice_number = db.Column(db.String(50))
    email_to = db.Column(db.String(100))
    subject = db.Column(db.String(200))
    body = db.Column(db.Text)
    stage = db.Column(db.String(255))
    mode = db.Column(db.String(20))
    scheduled_date = db.Column(db.DateTime)

    def __repr__(self):
        return f'<NotificationLog {self.subject} to {self.email_to} at {self.sent_at}>'


class SyncStatus(db.Model):
    """
    Model SyncStatus – rejestruje informacje o przebiegu synchronizacji:
      - account_id: ID profilu/konta dla którego wykonano synchronizację (multi-tenancy)
      - sync_number: numer synchronizacji PER KONTO (zaczyna od 1 dla każdego konta)
      - sync_type: typ synchronizacji ("new", "update", "full")
      - processed: liczba przetworzonych faktur (ŁĄCZNIE new + update)
      - timestamp: data wykonania synchronizacji
      - duration: czas trwania operacji (w sekundach, ŁĄCZNIE)
      - new_cases: liczba nowych spraw
      - updated_cases: liczba zaktualizowanych spraw
      - closed_cases: liczba zamkniętych spraw
      - api_calls: liczba wywołań API (ŁĄCZNIE)

      NOWE POLA (rozbicie szczegółowe dla typu "full"):
      - new_invoices_processed: faktury dodane podczas sync_new_invoices()
      - updated_invoices_processed: faktury zaktualizowane podczas update_existing_cases()
      - new_sync_duration: czas trwania sync_new_invoices()
      - update_sync_duration: czas trwania update_existing_cases()
    """
    id = db.Column(db.Integer, primary_key=True)
    # MULTI-TENANCY: Powiązanie z kontem (NOT NULL - wymagane dla tenant isolation)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False, index=True)
    # Numer synchronizacji per konto (zaczyna od 1 dla każdego konta)
    sync_number = db.Column(db.Integer, nullable=False, default=1)
    sync_type = db.Column(db.String(50))
    processed = db.Column(db.Integer)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    duration = db.Column(db.Float)
    new_cases = db.Column(db.Integer, default=0)
    updated_cases = db.Column(db.Integer, default=0)
    closed_cases = db.Column(db.Integer, default=0)
    api_calls = db.Column(db.Integer, default=0)

    # ROZBICIE SZCZEGÓŁOWE (dla typu "full")
    new_invoices_processed = db.Column(db.Integer, default=0)
    updated_invoices_processed = db.Column(db.Integer, default=0)
    new_sync_duration = db.Column(db.Float, default=0.0)
    update_sync_duration = db.Column(db.Float, default=0.0)

    @classmethod
    def get_next_sync_number(cls, account_id):
        """Zwraca następny numer synchronizacji dla danego konta."""
        max_num = db.session.query(db.func.max(cls.sync_number)).filter_by(account_id=account_id).scalar()
        return (max_num or 0) + 1

    def __repr__(self):
        return f'<SyncStatus #{self.sync_number} {self.sync_type}: {self.processed} faktur, {self.duration:.2f}s>'


class NotificationSettings(db.Model):
    """
    Model NotificationSettings – przechowuje ustawienia powiadomień w bazie danych.
    Każde konto (Account) ma własne ustawienia.

    MULTI-TENANCY CONSISTENCY:
    - Każdy profil MUSI mieć dokładnie 5 wpisów zdefiniowanych w CANONICAL_NOTIFICATION_STAGES
    - Metoda normalize_for_account() automatycznie naprawia niespójne dane
    """
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)
    stage_name = db.Column(db.String(255), nullable=False)
    offset_days = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('account_id', 'stage_name', name='uq_account_stage'),
    )

    def __repr__(self):
        return f'<NotificationSettings {self.stage_name}: {self.offset_days} days>'

    @classmethod
    def get_all_settings(cls, account_id):
        """Returns all settings for a specific account as a dictionary"""
        settings = cls.query.filter_by(account_id=account_id).all()
        return {setting.stage_name: setting.offset_days for setting in settings}

    @classmethod
    def update_settings(cls, account_id, settings_dict):
        """Updates all settings for a specific account from a dictionary"""
        for stage_name, offset_days in settings_dict.items():
            setting = cls.query.filter_by(account_id=account_id, stage_name=stage_name).first()
            if setting:
                setting.offset_days = offset_days
            else:
                new_setting = cls(account_id=account_id, stage_name=stage_name, offset_days=offset_days)
                db.session.add(new_setting)
        db.session.commit()

    @classmethod
    def initialize_default_settings(cls, account_id):
        """
        DEPRECATED: Use normalize_for_account() instead.
        Initializes default settings for a specific account if none exist.
        """
        if not cls.query.filter_by(account_id=account_id).first():
            default_settings = {
                "Przypomnienie o zbliżającym się terminie płatności": -1,
                "Powiadomienie o upływie terminu płatności": 7,
                "Wezwanie do zapłaty": 14,
                "Powiadomienie o zamiarze skierowania sprawy do windykatora zewnętrznego i publikacji na giełdzie wierzytelności": 21,
                "Przekazanie sprawy do windykatora zewnętrznego": 30,
            }
            for stage_name, offset_days in default_settings.items():
                new_setting = cls(account_id=account_id, stage_name=stage_name, offset_days=offset_days)
                db.session.add(new_setting)
            db.session.commit()

    @classmethod
    def normalize_for_account(cls, account_id):
        """
        Normalizuje NotificationSettings dla profilu - zapewnia dokładnie 5 poprawnych wpisów.

        SELF-HEALING SYSTEM:
        1. Pobiera wszystkie istniejące wpisy z bazy
        2. Usuwa wpisy NIE znajdujące się w CANONICAL_NOTIFICATION_STAGES (np. stare stage_1, stage_2)
        3. Dodaje brakujące wpisy z domyślnymi wartościami z CANONICAL_NOTIFICATION_STAGES
        4. Zwraca OrderedDict z 5 wpisami w poprawnej kolejności

        Args:
            account_id (int): ID profilu do normalizacji

        Returns:
            OrderedDict: Słownik {stage_name: offset_days} z dokładnie 5 wpisami
        """
        # Krok 1: Pobierz wszystkie istniejące wpisy
        existing_settings = cls.query.filter_by(account_id=account_id).all()

        # Krok 2: Stwórz set nazw kanonicznych dla szybkiego sprawdzania
        canonical_names = {stage_name for stage_name, _ in CANONICAL_NOTIFICATION_STAGES}

        # Krok 3: Usuń wpisy NIE znajdujące się w CANONICAL_NOTIFICATION_STAGES
        for setting in existing_settings:
            if setting.stage_name not in canonical_names:
                # Stary/niepoprawny wpis (np. "stage_1", "stage_2") - USUŃ
                db.session.delete(setting)
                print(f"[normalize] Usunięto niepoprawny wpis: {setting.stage_name} dla account_id={account_id}")

        db.session.commit()

        # Krok 4: Pobierz ponownie po czyszczeniu
        existing_settings = cls.query.filter_by(account_id=account_id).all()
        existing_dict = {setting.stage_name: setting.offset_days for setting in existing_settings}

        # Krok 5: Dodaj brakujące wpisy z CANONICAL_NOTIFICATION_STAGES
        for stage_name, default_offset in CANONICAL_NOTIFICATION_STAGES:
            if stage_name not in existing_dict:
                # Brakujący wpis - DODAJ z domyślną wartością
                new_setting = cls(
                    account_id=account_id,
                    stage_name=stage_name,
                    offset_days=default_offset
                )
                db.session.add(new_setting)
                existing_dict[stage_name] = default_offset
                print(f"[normalize] Dodano brakujący wpis: {stage_name} = {default_offset} dni dla account_id={account_id}")

        db.session.commit()

        # Krok 6: Zwróć OrderedDict w kolejności CANONICAL_NOTIFICATION_STAGES
        normalized = OrderedDict()
        for stage_name, default_offset in CANONICAL_NOTIFICATION_STAGES:
            normalized[stage_name] = existing_dict.get(stage_name, default_offset)

        return normalized


# Association table for User <-> Account many-to-many relationship
account_users = db.Table(
    'account_users',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), primary_key=True),
    db.Column('account_id', db.Integer, db.ForeignKey('account.id', ondelete='CASCADE'), primary_key=True),
    db.Column('created_at', db.DateTime, default=datetime.utcnow)
)


class User(UserMixin, db.Model):
    """
    Model User - reprezentuje uzytkownika systemu.

    Integracja z Flask-Login poprzez UserMixin.
    Relacja Many-to-Many z Account (profilami firmowymi).

    UWAGA: Brak rol/uprawnien - powiazanie z Account oznacza pelny dostep.
    """
    __tablename__ = 'user'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    _password_hash = db.Column('password_hash', db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login_at = db.Column(db.DateTime, nullable=True)

    # Many-to-Many relationship with Account
    accounts = db.relationship(
        'Account',
        secondary=account_users,
        lazy='dynamic',
        backref=db.backref('users', lazy='dynamic')
    )

    @property
    def password(self):
        """Password is write-only."""
        raise AttributeError('password is not readable')

    @password.setter
    def password(self, value):
        """Hash password on assignment."""
        self._password_hash = generate_password_hash(value)

    def check_password(self, password):
        """Verify password against hash."""
        return check_password_hash(self._password_hash, password)

    def has_access_to_account(self, account_id):
        """Check if user has access to specific account."""
        return self.accounts.filter_by(id=account_id).first() is not None

    def get_accessible_accounts(self):
        """Return list of accounts user can access."""
        return self.accounts.filter_by(is_active=True).order_by(Account.name).all()

    def __repr__(self):
        return f'<User {self.email} (ID: {self.id})>'


class Account(db.Model):
    """
    Model Account - reprezentuje profil/konto (np. Aquatest, Pozytron Szkolenia).
    Każdy profil ma własne ustawienia API i SMTP.
    Wrażliwe dane (API keys, hasła) są szyfrowane przy użyciu Fernet.

    MULTI-TENANCY: Many-to-Many z User poprzez account_users.
    """
    __tablename__ = 'account'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True, nullable=False)

    # API Configuration (zaszyfrowane)
    # NULLABLE: Umozliwia rejestracje bez konfiguracji (uzupelni w Settings)
    _infakt_api_key_encrypted = db.Column('infakt_api_key', db.LargeBinary, nullable=True)

    # Multi-Provider Credentials (zaszyfrowany JSON)
    # Format: {"api_key": "xyz"} dla InFakt, {"login": "user", "password": "pass"} dla wFirma
    _provider_settings_encrypted = db.Column('provider_settings', db.LargeBinary, nullable=True)

    # SMTP Configuration
    # NULLABLE: Umozliwia rejestracje bez konfiguracji (uzupelni w Settings)
    _smtp_server = db.Column('smtp_server', db.String(100), nullable=True)
    _smtp_port = db.Column('smtp_port', db.Integer, nullable=True, default=587)
    _smtp_username_encrypted = db.Column('smtp_username', db.LargeBinary, nullable=True)
    _smtp_password_encrypted = db.Column('smtp_password', db.LargeBinary, nullable=True)
    _email_from = db.Column('email_from', db.String(200), nullable=True)

    # Company details for email templates (niezaszyfrowane)
    company_full_name = db.Column(db.String(500), nullable=True)
    company_phone = db.Column(db.String(20), nullable=True)
    company_email_contact = db.Column(db.String(100), nullable=True)
    company_bank_account = db.Column(db.String(50), nullable=True)

    # Provider configuration (multi-provider support)
    provider_type = db.Column(db.String(50), default='infakt', nullable=False)

    # Status
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    cases = db.relationship('Case', backref='account', lazy=True)
    notification_logs = db.relationship('NotificationLog', backref='account', lazy=True)
    notification_settings = db.relationship('NotificationSettings', backref='account', lazy=True)

    @staticmethod
    def _get_cipher():
        """Returns Fernet cipher for encryption/decryption"""
        key_str = os.environ.get('ENCRYPTION_KEY', 'default_32_byte_key_for_dev!!!')
        # Ensure key is exactly 32 bytes
        key_bytes = key_str.encode().ljust(32)[:32]
        key = base64.urlsafe_b64encode(key_bytes)
        return Fernet(key)

    @property
    def infakt_api_key(self) -> str | None:
        """
        DEPRECATED: Użyj provider_settings['api_key'] zamiast tego property.

        Backward compatibility - czyta najpierw z nowego formatu JSON,
        potem fallback na starą kolumnę.
        """
        # Najpierw sprawdź nowy format (provider_settings)
        settings = self.provider_settings
        if settings and self.provider_type == 'infakt':
            api_key = settings.get('api_key')
            if api_key:
                return api_key

        # Fallback na starą kolumnę (migracja w toku)
        if self._infakt_api_key_encrypted:
            cipher = self._get_cipher()
            return cipher.decrypt(self._infakt_api_key_encrypted).decode()
        return None

    @infakt_api_key.setter
    def infakt_api_key(self, value):
        """
        DEPRECATED: Użyj provider_settings = {'api_key': value} zamiast tego.

        Backward compatibility - zapisuje do starej kolumny.
        """
        cipher = self._get_cipher()
        self._infakt_api_key_encrypted = cipher.encrypt(value.encode())

    # =========================================================================
    # Multi-Provider Credentials (JSON)
    # =========================================================================

    @property
    def provider_settings(self) -> dict | None:
        """Deszyfruje i zwraca credentials providera jako dict."""
        if self._provider_settings_encrypted:
            try:
                cipher = self._get_cipher()
                decrypted = cipher.decrypt(self._provider_settings_encrypted).decode()
                return json.loads(decrypted)
            except (json.JSONDecodeError, Exception) as e:
                # Loguj błąd, ale nie crashuj - zwróć None i pozwól na ponowną konfigurację
                logging.getLogger(__name__).error(
                    f"Failed to decrypt/parse provider_settings for Account {self.id}: {e}"
                )
                return None
        return None

    @provider_settings.setter
    def provider_settings(self, value: dict | None):
        """Szyfruje i zapisuje credentials providera jako JSON."""
        if value is None:
            self._provider_settings_encrypted = None
            return
        cipher = self._get_cipher()
        json_str = json.dumps(value)
        self._provider_settings_encrypted = cipher.encrypt(json_str.encode())

    @property
    def smtp_username(self):
        """Decrypts and returns SMTP username"""
        if self._smtp_username_encrypted:
            cipher = self._get_cipher()
            return cipher.decrypt(self._smtp_username_encrypted).decode()
        return None

    @smtp_username.setter
    def smtp_username(self, value):
        """Encrypts and stores SMTP username"""
        cipher = self._get_cipher()
        self._smtp_username_encrypted = cipher.encrypt(value.encode())

    @property
    def smtp_password(self):
        """Decrypts and returns SMTP password"""
        if self._smtp_password_encrypted:
            cipher = self._get_cipher()
            return cipher.decrypt(self._smtp_password_encrypted).decode()
        return None

    @smtp_password.setter
    def smtp_password(self, value):
        """Encrypts and stores SMTP password"""
        cipher = self._get_cipher()
        self._smtp_password_encrypted = cipher.encrypt(value.encode())

    @property
    def smtp_server(self):
        return self._smtp_server

    @smtp_server.setter
    def smtp_server(self, value):
        self._smtp_server = value

    @property
    def smtp_port(self):
        return self._smtp_port

    @smtp_port.setter
    def smtp_port(self, value):
        self._smtp_port = value

    @property
    def email_from(self):
        return self._email_from

    @email_from.setter
    def email_from(self, value):
        self._email_from = value

    # =========================================================================
    # Configuration Status Properties (for Lazy Validation / Onboarding)
    # =========================================================================

    @property
    def is_provider_configured(self) -> bool:
        """Sprawdza czy credentials dla providera są kompletne."""
        from .constants import REQUIRED_CREDENTIALS  # Import wewnątrz - unika cyklicznych importów

        settings = self.provider_settings
        if not settings:
            # Fallback dla migracji w toku (stara kolumna)
            if self.provider_type == 'infakt' and self._infakt_api_key_encrypted:
                return True
            return False

        required = REQUIRED_CREDENTIALS.get(self.provider_type, [])
        return all(settings.get(key) for key in required)

    @property
    def is_smtp_configured(self):
        """Sprawdza czy SMTP jest skonfigurowany."""
        return all([
            self._smtp_server,
            self._smtp_username_encrypted,
            self._smtp_password_encrypted,
            self._email_from
        ])

    @property
    def is_fully_configured(self):
        """Sprawdza czy konto jest w pelni skonfigurowane (API + SMTP)."""
        return self.is_provider_configured and self.is_smtp_configured

    def __repr__(self):
        return f'<Account {self.name} (ID: {self.id}, Active: {self.is_active})>'


class AccountScheduleSettings(db.Model):
    """
    Model przechowujący zaawansowane ustawienia harmonogramu dla każdego konta.
    - Godziny wysyłki emaili
    - Godziny synchronizacji
    - Parametry pobierania faktur

    MULTI-TENANCY: Każde konto ma własne, niezależne ustawienia harmonogramu.
    """
    __tablename__ = 'account_schedule_settings'

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False, unique=True)

    # Wysyłka emaili (UTC)
    mail_send_hour = db.Column(db.Integer, default=7, nullable=False)  # 0-23
    mail_send_minute = db.Column(db.Integer, default=0, nullable=False)  # 0-59
    is_mail_enabled = db.Column(db.Boolean, default=True, nullable=False)

    # Synchronizacja (UTC)
    sync_hour = db.Column(db.Integer, default=9, nullable=False)  # 0-23
    sync_minute = db.Column(db.Integer, default=0, nullable=False)  # 0-59
    is_sync_enabled = db.Column(db.Boolean, default=True, nullable=False)

    # Parametry pobierania faktur
    invoice_fetch_days_before = db.Column(db.Integer, default=1, nullable=False)  # 1-30

    # Strefa czasowa (dla wyświetlania w UI)
    timezone = db.Column(db.String(50), default='Europe/Warsaw', nullable=False)

    # Opcje dodatkowe
    auto_close_after_stage5 = db.Column(db.Boolean, default=True, nullable=False)

    # Metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relacja
    account = db.relationship('Account', backref=db.backref('schedule_settings', uselist=False, lazy=True))

    def __repr__(self):
        return f'<AccountScheduleSettings Account:{self.account_id} Mail:{self.mail_send_hour}:{self.mail_send_minute:02d} Sync:{self.sync_hour}:{self.sync_minute:02d}>'

    @classmethod
    def get_for_account(cls, account_id):
        """
        Pobiera ustawienia dla konta lub tworzy domyślne jeśli nie istnieją.

        Args:
            account_id (int): ID konta

        Returns:
            AccountScheduleSettings: Obiekt ustawień
        """
        settings = cls.query.filter_by(account_id=account_id).first()
        if not settings:
            # Utwórz domyślne ustawienia
            # Dla Pozytron (ID=2) ustawienia są inne
            default_fetch_days = 7 if account_id == 2 else 1
            settings = cls(
                account_id=account_id,
                invoice_fetch_days_before=default_fetch_days
            )
            db.session.add(settings)
            db.session.commit()
        return settings

    @classmethod
    def get_all_active(cls):
        """
        Pobiera ustawienia dla wszystkich aktywnych kont.

        Returns:
            list[AccountScheduleSettings]: Lista ustawień
        """
        return cls.query.join(Account).filter(Account.is_active == True).all()

    def to_dict(self):
        """Konwersja do słownika dla API/JSON"""
        return {
            'account_id': self.account_id,
            'mail_send_hour': self.mail_send_hour,
            'mail_send_minute': self.mail_send_minute,
            'is_mail_enabled': self.is_mail_enabled,
            'sync_hour': self.sync_hour,
            'sync_minute': self.sync_minute,
            'is_sync_enabled': self.is_sync_enabled,
            'invoice_fetch_days_before': self.invoice_fetch_days_before,
            'timezone': self.timezone,
            'auto_close_after_stage5': self.auto_close_after_stage5
        }

    def validate(self):
        """
        Walidacja wartości pól.

        Returns:
            tuple: (is_valid: bool, errors: list)
        """
        errors = []

        if not (0 <= self.mail_send_hour <= 23):
            errors.append("Godzina wysyłki musi być między 0-23")
        if not (0 <= self.mail_send_minute <= 59):
            errors.append("Minuta wysyłki musi być między 0-59")

        if not (0 <= self.sync_hour <= 23):
            errors.append("Godzina synchronizacji musi być między 0-23")
        if not (0 <= self.sync_minute <= 59):
            errors.append("Minuta synchronizacji musi być między 0-59")

        if not (1 <= self.invoice_fetch_days_before <= 30):
            errors.append("Termin pobierania faktur musi być między 1-30 dni")

        return (len(errors) == 0, errors)
