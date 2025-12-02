"""add multi-tenancy support

Revision ID: 2025101600_multi
Revises: 2025101513_perf
Create Date: 2025-10-16 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime
from cryptography.fernet import Fernet
import base64
import os

# revision identifiers, used by Alembic.
revision = '2025101600_multi'
down_revision = '2025101513_perf'
branch_labels = None
depends_on = None


def get_cipher():
    """Returns Fernet cipher for encryption/decryption"""
    key_str = os.environ.get('ENCRYPTION_KEY', 'default_32_byte_key_for_dev!!!')
    # Ensure key is exactly 32 bytes
    key_bytes = key_str.encode().ljust(32)[:32]
    key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(key)


def upgrade():
    # 1. Utwórz tabelę Account
    op.create_table(
        'account',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(200), unique=True, nullable=False),
        sa.Column('infakt_api_key', sa.LargeBinary(), nullable=False),
        sa.Column('smtp_server', sa.String(100), nullable=False),
        sa.Column('smtp_port', sa.Integer(), nullable=False, server_default='587'),
        sa.Column('smtp_username', sa.LargeBinary(), nullable=False),
        sa.Column('smtp_password', sa.LargeBinary(), nullable=False),
        sa.Column('email_from', sa.String(200), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now())
    )

    # 2. Dodaj account_id do istniejących tabel (nullable na razie)
    op.add_column('case', sa.Column('account_id', sa.Integer(), nullable=True))
    op.add_column('notification_log', sa.Column('account_id', sa.Integer(), nullable=True))
    op.add_column('notification_settings', sa.Column('account_id', sa.Integer(), nullable=True))

    # 3. Utwórz domyślne konto "Aquatest" z obecnej konfiguracji
    cipher = get_cipher()

    # Pobierz obecne dane z .env
    infakt_key = os.environ.get('INFAKT_API_KEY', 'default_key')
    smtp_user = os.environ.get('SMTP_USERNAME', 'rozliczenia@aquatest.pl')
    smtp_pass = os.environ.get('SMTP_PASSWORD', 'default_pass')
    smtp_server = os.environ.get('SMTP_SERVER', 'sgz.nazwa.pl')
    email_from = os.environ.get('EMAIL_FROM', 'rozliczenia@aquatest.pl')

    # Zaszyfruj
    encrypted_api_key = cipher.encrypt(infakt_key.encode())
    encrypted_smtp_user = cipher.encrypt(smtp_user.encode())
    encrypted_smtp_pass = cipher.encrypt(smtp_pass.encode())

    # Wstaw konto Aquatest (ID=1)
    # Użyj connection.execute zamiast op.execute dla lepszej kontroli
    conn = op.get_bind()
    conn.execute(
        sa.text("""
            INSERT INTO account (id, name, infakt_api_key, smtp_server, smtp_port, smtp_username, smtp_password, email_from, is_active, created_at)
            VALUES (:id, :name, :api_key, :server, :port, :username, :password, :email, :active, :created)
        """),
        {
            'id': 1,
            'name': 'Aquatest',
            'api_key': encrypted_api_key,
            'server': smtp_server,
            'port': 587,
            'username': encrypted_smtp_user,
            'password': encrypted_smtp_pass,
            'email': email_from,
            'active': True,
            'created': datetime.utcnow()
        }
    )

    # 4. Przypisz wszystkie istniejące dane do konta Aquatest (ID=1)
    op.execute("UPDATE \"case\" SET account_id = 1 WHERE account_id IS NULL")
    op.execute("UPDATE notification_log SET account_id = 1 WHERE account_id IS NULL")
    op.execute("UPDATE notification_settings SET account_id = 1 WHERE account_id IS NULL")

    # 5. Usuń unique constraint z notification_settings.stage_name (jeśli istnieje)
    try:
        op.drop_constraint('notification_settings_stage_name_key', 'notification_settings', type_='unique')
    except Exception:
        # Constraint może nie istnieć, kontynuuj
        pass

    # 6. Dodaj composite unique constraint
    op.create_unique_constraint('uq_account_stage', 'notification_settings', ['account_id', 'stage_name'])

    # 7. Ustaw account_id jako NOT NULL
    op.alter_column('case', 'account_id', nullable=False)
    op.alter_column('notification_log', 'account_id', nullable=False)
    op.alter_column('notification_settings', 'account_id', nullable=False)

    # 8. Utwórz foreign keys
    op.create_foreign_key('fk_case_account', 'case', 'account', ['account_id'], ['id'])
    op.create_foreign_key('fk_notification_log_account', 'notification_log', 'account', ['account_id'], ['id'])
    op.create_foreign_key('fk_notification_settings_account', 'notification_settings', 'account', ['account_id'], ['id'])

    # 9. Utwórz indeksy wydajnościowe
    op.create_index('idx_case_account_id', 'case', ['account_id'])
    op.create_index('idx_notification_log_account_id', 'notification_log', ['account_id'])
    op.create_index('idx_case_account_status', 'case', ['account_id', 'status'])


def downgrade():
    # Drop indexes
    op.drop_index('idx_case_account_status', table_name='case')
    op.drop_index('idx_notification_log_account_id', table_name='notification_log')
    op.drop_index('idx_case_account_id', table_name='case')

    # Drop foreign keys
    op.drop_constraint('fk_notification_settings_account', 'notification_settings', type_='foreignkey')
    op.drop_constraint('fk_notification_log_account', 'notification_log', type_='foreignkey')
    op.drop_constraint('fk_case_account', 'case', type_='foreignkey')

    # Restore old unique constraint
    op.drop_constraint('uq_account_stage', 'notification_settings', type_='unique')
    try:
        op.create_unique_constraint('notification_settings_stage_name_key', 'notification_settings', ['stage_name'])
    except Exception:
        pass

    # Drop account_id columns
    op.drop_column('notification_settings', 'account_id')
    op.drop_column('notification_log', 'account_id')
    op.drop_column('case', 'account_id')

    # Drop account table
    op.drop_table('account')
