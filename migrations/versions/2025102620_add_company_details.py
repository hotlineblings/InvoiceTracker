"""Add company details to Account for email templates

Revision ID: 2025102620
Revises: 2025102201
Create Date: 2025-10-26 20:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2025102620_company'
down_revision = '2025102201_expand'
branch_labels = None
depends_on = None


def upgrade():
    """
    Dodaje 4 nowe kolumny do tabeli Account dla dynamicznych danych firmowych w szablonach maili:
    - company_full_name: Pełna nazwa firmy wierzyciela
    - company_phone: Telefon kontaktowy
    - company_email_contact: Email kontaktowy
    - company_bank_account: Numer rachunku bankowego
    """
    # Dodaj kolumny
    op.add_column('account', sa.Column('company_full_name', sa.String(500), nullable=True))
    op.add_column('account', sa.Column('company_phone', sa.String(20), nullable=True))
    op.add_column('account', sa.Column('company_email_contact', sa.String(100), nullable=True))
    op.add_column('account', sa.Column('company_bank_account', sa.String(50), nullable=True))

    # Ustawienia domyślne dla Aquatest (ID=1)
    op.execute("""
        UPDATE account
        SET
            company_full_name = 'AQUATEST LABORATORIUM BADAWCZE SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ',
            company_phone = '451089077',
            company_email_contact = 'rozliczenia@aquatest.pl',
            company_bank_account = '27 1140 1124 0000 3980 6300 1001'
        WHERE id = 1
    """)

    # Ustawienia dla Pozytron (ID=2) - do uzupełnienia przez użytkownika w panelu ustawień
    op.execute("""
        UPDATE account
        SET
            company_full_name = 'POZYTRON SZKOLENIA',
            company_phone = '',
            company_email_contact = 'rozliczenia@pozytron.pl',
            company_bank_account = ''
        WHERE id = 2
    """)


def downgrade():
    """Usuwa kolumny z danymi firmowymi"""
    op.drop_column('account', 'company_bank_account')
    op.drop_column('account', 'company_email_contact')
    op.drop_column('account', 'company_phone')
    op.drop_column('account', 'company_full_name')
