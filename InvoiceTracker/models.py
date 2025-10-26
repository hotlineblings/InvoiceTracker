from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from cryptography.fernet import Fernet
import base64
import os

db = SQLAlchemy()

class Case(db.Model):
    """
    Model Case – reprezentuje sprawę windykacyjną pojedynczej faktury.
    Numer sprawy to numer faktury.
    Status może być: "active", "closed_oplacone", "closed_nieoplacone".

    MULTI-TENANCY: case_number jest unique PER ACCOUNT (nie globalnie).
    Constraint: UNIQUE(case_number, account_id)
    """
    id = db.Column(db.Integer, primary_key=True)
    case_number = db.Column(db.String(50), nullable=False)  # ZMIENIONE: usunięto unique=True
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
    """
    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(50))
    invoice_date = db.Column(db.Date)
    payment_due_date = db.Column(db.Date)
    gross_price = db.Column(db.Integer)  # wartość brutto w groszach
    status = db.Column(db.String(50))    # np. "sent", "printed", "paid"
    debt_status = db.Column(db.String(200))
    client_id = db.Column(db.String(50))
    client_company_name = db.Column(db.String(200))
    client_email = db.Column(db.String(100))
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
    # MULTI-TENANCY: Powiązanie z kontem (nullable=True dla wstecznej kompatybilności)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=True, index=True)
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

    def __repr__(self):
        return f'<SyncStatus {self.sync_type}: {self.processed} faktur, {self.duration:.2f}s>'
    
    
class NotificationSettings(db.Model):
    """
    Model NotificationSettings – przechowuje ustawienia powiadomień w bazie danych.
    Każde konto (Account) ma własne ustawienia.
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
        """Initializes default settings for a specific account if none exist"""
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


class Account(db.Model):
    """
    Model Account - reprezentuje profil/konto (np. Aquatest, Pozytron Szkolenia).
    Każdy profil ma własne ustawienia API i SMTP.
    Wrażliwe dane (API keys, hasła) są szyfrowane przy użyciu Fernet.
    """
    __tablename__ = 'account'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True, nullable=False)

    # API Configuration (zaszyfrowane)
    _infakt_api_key_encrypted = db.Column('infakt_api_key', db.LargeBinary, nullable=False)

    # SMTP Configuration
    _smtp_server = db.Column('smtp_server', db.String(100), nullable=False)
    _smtp_port = db.Column('smtp_port', db.Integer, nullable=False, default=587)
    _smtp_username_encrypted = db.Column('smtp_username', db.LargeBinary, nullable=False)
    _smtp_password_encrypted = db.Column('smtp_password', db.LargeBinary, nullable=False)
    _email_from = db.Column('email_from', db.String(200), nullable=False)

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
    def infakt_api_key(self):
        """Decrypts and returns InFakt API key"""
        if self._infakt_api_key_encrypted:
            cipher = self._get_cipher()
            return cipher.decrypt(self._infakt_api_key_encrypted).decode()
        return None

    @infakt_api_key.setter
    def infakt_api_key(self, value):
        """Encrypts and stores InFakt API key"""
        cipher = self._get_cipher()
        self._infakt_api_key_encrypted = cipher.encrypt(value.encode())

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