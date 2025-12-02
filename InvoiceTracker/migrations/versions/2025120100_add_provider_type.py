"""Add provider_type to Account for multi-provider support

Revision ID: 2025120100_provider
Revises: 2025102627_override
Create Date: 2025-12-01 16:30:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2025120100_provider'
down_revision = '2025102627_override'
branch_labels = None
depends_on = None


def upgrade():
    """
    Dodaje kolumnę provider_type do tabeli account.
    Umożliwia obsługę różnych dostawców faktur (InFakt, wFirma, itp.).
    """
    op.add_column('account', sa.Column('provider_type', sa.String(50), nullable=False, server_default='infakt'))

    print("[migration] Dodano kolumnę provider_type do tabeli account")
    print("[migration] Domyślna wartość: 'infakt' (dla wstecznej kompatybilności)")


def downgrade():
    """Usuwa kolumnę provider_type"""
    op.drop_column('account', 'provider_type')

    print("[migration] Usunięto kolumnę provider_type z tabeli account")
