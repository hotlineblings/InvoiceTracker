"""Expand SyncStatus with detailed breakdown columns

Revision ID: 2025102201_expand
Revises: 2025102200_schedule
Create Date: 2025-10-22 22:00:00.000000

Adds 4 new columns to sync_status table for detailed breakdown of synchronization metrics:
- new_invoices_processed: number of invoices added during sync_new_invoices()
- updated_invoices_processed: number of invoices updated during update_existing_cases()
- new_sync_duration: time taken by sync_new_invoices() in seconds
- update_sync_duration: time taken by update_existing_cases() in seconds

These columns eliminate the need for triple-record writes (new/update/full),
allowing a single "full" record with complete breakdown.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '2025102201_expand'
down_revision = '2025102200_schedule'
branch_labels = None
depends_on = None


def upgrade():
    """
    Dodaje 4 nowe kolumny do tabeli sync_status dla szczegółowego rozbicia metryk.
    """
    # Dodaj kolumny z wartościami domyślnymi
    op.add_column('sync_status', sa.Column('new_invoices_processed', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('sync_status', sa.Column('updated_invoices_processed', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('sync_status', sa.Column('new_sync_duration', sa.Float(), nullable=False, server_default='0.0'))
    op.add_column('sync_status', sa.Column('update_sync_duration', sa.Float(), nullable=False, server_default='0.0'))

    print("[migration] ✅ Dodano 4 nowe kolumny do tabeli sync_status")
    print("[migration] ✅ Kolumny: new_invoices_processed, updated_invoices_processed, new_sync_duration, update_sync_duration")


def downgrade():
    """
    Usuwa 4 nowe kolumny z tabeli sync_status (rollback).
    """
    op.drop_column('sync_status', 'update_sync_duration')
    op.drop_column('sync_status', 'new_sync_duration')
    op.drop_column('sync_status', 'updated_invoices_processed')
    op.drop_column('sync_status', 'new_invoices_processed')

    print("[migration] ⚠️  Usunięto 4 kolumny z tabeli sync_status")
