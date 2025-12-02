"""add account_id to sync_status

Revision ID: 2025101601_sync
Revises: 2025101600_multi
Create Date: 2025-10-16 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '2025101601_sync'
down_revision = '2025101600_multi'
branch_labels = None
depends_on = None


def upgrade():
    """
    Dodaje account_id do sync_status dla obsługi multi-tenancy.
    Wszystkie istniejące rekordy zostaną przypisane do konta Aquatest (ID=1).
    """
    # 1. Dodaj kolumnę account_id (nullable=True dla wstecznej kompatybilności)
    op.add_column('sync_status', sa.Column('account_id', sa.Integer(), nullable=True))

    # 2. Przypisz wszystkie istniejące rekordy do konta Aquatest (ID=1)
    op.execute("UPDATE sync_status SET account_id = 1 WHERE account_id IS NULL")

    # 3. Utwórz foreign key do account
    op.create_foreign_key('fk_sync_status_account', 'sync_status', 'account', ['account_id'], ['id'])

    # 4. Utwórz indeks wydajnościowy
    op.create_index('idx_sync_status_account_id', 'sync_status', ['account_id'])

    # Uwaga: Nie ustawiamy NOT NULL constraint, aby zachować elastyczność
    # na wypadek starych rekordów lub migracji danych


def downgrade():
    """
    Usuwa account_id z sync_status.
    """
    # Drop index
    op.drop_index('idx_sync_status_account_id', table_name='sync_status')

    # Drop foreign key
    op.drop_constraint('fk_sync_status_account', 'sync_status', type_='foreignkey')

    # Drop column
    op.drop_column('sync_status', 'account_id')
