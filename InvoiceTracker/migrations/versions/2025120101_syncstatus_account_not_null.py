"""SyncStatus account_id NOT NULL - required for multi-tenancy safety

Revision ID: 2025120101_notnull
Revises: 2025120100_provider
Create Date: 2025-12-01

UWAGA: Ta migracja MUSI być wykonana PRZED włączeniem filtrów tenant
w extensions.py. Stare rekordy z NULL account_id zostaną przypisane
do pierwszego aktywnego konta.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = '2025120101_notnull'
down_revision = '2025120100_provider'
branch_labels = None
depends_on = None


def upgrade():
    """
    1. Znajdź pierwsze aktywne konto
    2. Uzupełnij NULL account_id tym kontem
    3. Zmień kolumnę na NOT NULL
    """
    conn = op.get_bind()

    # 1. Znajdź pierwsze aktywne konto
    result = conn.execute(text("SELECT id FROM account WHERE is_active = true ORDER BY id LIMIT 1"))
    row = result.fetchone()
    default_account_id = row[0] if row else None

    # 2. Sprawdź ile rekordów ma NULL
    null_count = conn.execute(text("SELECT COUNT(*) FROM sync_status WHERE account_id IS NULL")).scalar()

    if null_count > 0:
        if default_account_id:
            print(f"[migration] Znaleziono {null_count} rekordów z NULL account_id")
            print(f"[migration] Przypisuję do konta ID={default_account_id}")

            # Uzupełnij NULL-e
            conn.execute(
                text(f"UPDATE sync_status SET account_id = :acc_id WHERE account_id IS NULL"),
                {"acc_id": default_account_id}
            )
            print(f"[migration] Zaktualizowano {null_count} rekordów")
        else:
            # Brak aktywnych kont - usuń rekordy z NULL (orphaned data)
            print(f"[migration] UWAGA: Brak aktywnych kont, usuwam {null_count} rekordów z NULL account_id")
            conn.execute(text("DELETE FROM sync_status WHERE account_id IS NULL"))
    else:
        print("[migration] Wszystkie rekordy sync_status mają account_id - OK")

    # 3. Zmień na NOT NULL
    op.alter_column(
        'sync_status',
        'account_id',
        existing_type=sa.Integer(),
        nullable=False
    )
    print("[migration] Kolumna sync_status.account_id zmieniona na NOT NULL")


def downgrade():
    """Przywraca nullable=True dla account_id"""
    op.alter_column(
        'sync_status',
        'account_id',
        existing_type=sa.Integer(),
        nullable=True
    )
    print("[migration] Kolumna sync_status.account_id przywrócona do nullable=True")
