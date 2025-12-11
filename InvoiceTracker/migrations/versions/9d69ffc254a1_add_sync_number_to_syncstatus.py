"""Add sync_number to SyncStatus

Revision ID: 9d69ffc254a1
Revises: 2025120301_nullable
Create Date: 2025-12-04 20:28:30.563967

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '9d69ffc254a1'
down_revision = '2025120301_nullable'
branch_labels = None
depends_on = None


def upgrade():
    # Dodaj kolumnę sync_number (nullable na start)
    op.add_column('sync_status', sa.Column('sync_number', sa.Integer(), nullable=True))

    # Ustaw sync_number = 1 dla istniejących rekordów (każdy jest pierwszą sync dla konta)
    op.execute("UPDATE sync_status SET sync_number = 1 WHERE sync_number IS NULL")

    # Zmień na NOT NULL
    op.alter_column('sync_status', 'sync_number', nullable=False)


def downgrade():
    op.drop_column('sync_status', 'sync_number')
