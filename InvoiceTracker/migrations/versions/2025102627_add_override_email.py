"""Add override_email to Invoice for manual email override

Revision ID: 2025102627_override
Revises: 2025102620_company
Create Date: 2025-10-26 22:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2025102627_override'
down_revision = '2025102620_company'
branch_labels = None
depends_on = None


def upgrade():
    """
    Dodaje kolumnę override_email do tabeli invoice.
    Umożliwia administratorowi ręczne nadpisanie emaila klienta z API.
    """
    op.add_column('invoice', sa.Column('override_email', sa.String(100), nullable=True))

    print("[migration] ✅ Dodano kolumnę override_email do tabeli invoice")
    print("[migration] ℹ️  Domyślnie NULL - używany jest client_email z API")
    print("[migration] ℹ️  Gdy admin ustawi override_email, ma on priorytet nad API")


def downgrade():
    """Usuwa kolumnę override_email"""
    op.drop_column('invoice', 'override_email')

    print("[migration] ⚠️  Usunięto kolumnę override_email z tabeli invoice")
