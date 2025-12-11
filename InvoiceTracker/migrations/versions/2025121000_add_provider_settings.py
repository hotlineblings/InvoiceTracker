"""Add provider_settings column for multi-provider support.

Revision ID: 2025121000
Revises: 2025120301
Create Date: 2025-12-10

This migration adds a new encrypted JSON column for storing provider credentials
in a generic format, enabling multi-provider support (InFakt, wFirma, Fakturownia).

The old _infakt_api_key_encrypted column is NOT removed - it serves as fallback
during migration. A separate script (migrate_credentials.py) handles data migration.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2025121000_provider_settings'
down_revision = '9d69ffc254a1'
branch_labels = None
depends_on = None


def upgrade():
    # Add new column for multi-provider credentials (encrypted JSON)
    op.add_column('account',
        sa.Column('provider_settings', sa.LargeBinary(), nullable=True)
    )


def downgrade():
    op.drop_column('account', 'provider_settings')
