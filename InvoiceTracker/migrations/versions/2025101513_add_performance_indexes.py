"""add performance indexes

Revision ID: 2025101513_perf
Revises: 1b0341bc76bd
Create Date: 2025-10-15 13:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2025101513_perf'
down_revision = '1b0341bc76bd'
branch_labels = None
depends_on = None


def upgrade():
    # Add index on case.status for filtering active/closed cases
    op.create_index('idx_case_status', 'case', ['status'], unique=False)

    # Add composite index on case for ordering closed cases
    op.create_index('idx_case_status_updated_at', 'case', ['status', 'updated_at'], unique=False)

    # Add index on invoice.case_id for JOIN operations
    op.create_index('idx_invoice_case_id', 'invoice', ['case_id'], unique=False)

    # Add index on notification_log.invoice_number for batch queries
    op.create_index('idx_notification_log_invoice_number', 'notification_log', ['invoice_number'], unique=False)

    # Add composite index for checking notification stages
    op.create_index('idx_notification_log_invoice_stage', 'notification_log', ['invoice_number', 'stage'], unique=False)


def downgrade():
    # Remove indexes in reverse order
    op.drop_index('idx_notification_log_invoice_stage', table_name='notification_log')
    op.drop_index('idx_notification_log_invoice_number', table_name='notification_log')
    op.drop_index('idx_invoice_case_id', table_name='invoice')
    op.drop_index('idx_case_status_updated_at', table_name='case')
    op.drop_index('idx_case_status', table_name='case')
