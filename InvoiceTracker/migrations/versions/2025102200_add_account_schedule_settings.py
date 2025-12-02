"""add AccountScheduleSettings table for per-account schedule configuration

Revision ID: 2025102200_schedule
Revises: 2025101601_sync
Create Date: 2025-10-22 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '2025102200_schedule'
down_revision = '2025101601_sync'
branch_labels = None
depends_on = None


def upgrade():
    """
    Tworzy tabelę account_schedule_settings dla ustawień harmonogramu per-profil.
    Automatycznie generuje domyślne ustawienia dla wszystkich istniejących kont.
    """
    # 1. Utwórz tabelę
    op.create_table(
        'account_schedule_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('account_id', sa.Integer(), nullable=False),
        sa.Column('mail_send_hour', sa.Integer(), nullable=False),
        sa.Column('mail_send_minute', sa.Integer(), nullable=False),
        sa.Column('is_mail_enabled', sa.Boolean(), nullable=False),
        sa.Column('sync_hour', sa.Integer(), nullable=False),
        sa.Column('sync_minute', sa.Integer(), nullable=False),
        sa.Column('is_sync_enabled', sa.Boolean(), nullable=False),
        sa.Column('invoice_fetch_days_before', sa.Integer(), nullable=False),
        sa.Column('timezone', sa.String(length=50), nullable=False),
        sa.Column('auto_close_after_stage5', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['account_id'], ['account.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('account_id')
    )

    # 2. Utwórz indeks dla szybszego wyszukiwania
    op.create_index('idx_account_schedule_settings_account_id', 'account_schedule_settings', ['account_id'])

    # 3. Wygeneruj domyślne ustawienia dla istniejących kont
    # Aquatest (ID=1): 1 dzień przed terminem
    # Pozytron (ID=2): 7 dni przed terminem (zgodnie z poprzednią logiką)
    # Pozostałe: 1 dzień przed terminem
    op.execute("""
        INSERT INTO account_schedule_settings
        (account_id, mail_send_hour, mail_send_minute, is_mail_enabled,
         sync_hour, sync_minute, is_sync_enabled, invoice_fetch_days_before,
         timezone, auto_close_after_stage5, created_at, updated_at)
        SELECT
            id,
            7, 0, TRUE,  -- mail: 7:00 UTC (9:00 PL w zimie, 10:00 w lecie)
            9, 0, TRUE,  -- sync: 9:00 UTC (11:00 PL w zimie, 12:00 w lecie)
            CASE WHEN id = 2 THEN 7 ELSE 1 END,  -- Pozytron: 7 dni, reszta: 1 dzień
            'Europe/Warsaw',
            TRUE,
            NOW(),
            NOW()
        FROM account
        WHERE is_active = TRUE
    """)

    print("[migration] ✅ Utworzono tabelę account_schedule_settings")
    print("[migration] ✅ Wygenerowano domyślne ustawienia dla istniejących kont")


def downgrade():
    """
    Usuwa tabelę account_schedule_settings.
    """
    # Drop index
    op.drop_index('idx_account_schedule_settings_account_id', table_name='account_schedule_settings')

    # Drop table
    op.drop_table('account_schedule_settings')

    print("[migration] ⚠️  Usunięto tabelę account_schedule_settings")
