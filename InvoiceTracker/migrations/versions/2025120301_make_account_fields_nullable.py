"""Make Account API/SMTP fields nullable for SaaS registration

Revision ID: 2025120301_nullable
Revises: 2025120300_user
Create Date: 2025-12-03

Ta migracja:
1. Zmienia pola API i SMTP w tabeli Account na nullable=True
2. Umozliwia tworzenie Account bez konfiguracji (uzupelni w Settings po rejestracji)

UZASADNIENIE:
- UX Onboardingu: Klient musi moc zalogowac sie i poznac interfejs bez konfiguracji
- Przyszlosc: Migracja z SMTP na SendGrid/API wymaga elastycznosci schematu
- Lazy Validation: Funkcje wymagajace integracji blokowane przy probie uzycia, nie przy rejestracji
"""
from alembic import op
import sqlalchemy as sa


revision = '2025120301_nullable'
down_revision = '2025120300_user'
branch_labels = None
depends_on = None


def upgrade():
    # Zmien kolumny na nullable=True
    # UWAGA: PostgreSQL wymaga explicit ALTER COLUMN ... DROP NOT NULL

    op.alter_column('account', 'infakt_api_key',
                    existing_type=sa.LargeBinary(),
                    nullable=True)
    print("[migration] account.infakt_api_key -> nullable=True")

    op.alter_column('account', 'smtp_server',
                    existing_type=sa.String(100),
                    nullable=True)
    print("[migration] account.smtp_server -> nullable=True")

    op.alter_column('account', 'smtp_port',
                    existing_type=sa.Integer(),
                    nullable=True)
    print("[migration] account.smtp_port -> nullable=True")

    op.alter_column('account', 'smtp_username',
                    existing_type=sa.LargeBinary(),
                    nullable=True)
    print("[migration] account.smtp_username -> nullable=True")

    op.alter_column('account', 'smtp_password',
                    existing_type=sa.LargeBinary(),
                    nullable=True)
    print("[migration] account.smtp_password -> nullable=True")

    op.alter_column('account', 'email_from',
                    existing_type=sa.String(200),
                    nullable=True)
    print("[migration] account.email_from -> nullable=True")

    print("=" * 60)
    print("[migration] SUCCESS: Account fields are now nullable")
    print("[migration] New accounts can be created without API/SMTP config")
    print("=" * 60)


def downgrade():
    # UWAGA: Przed downgrade nalezy reczenie uzupelnic NULL-e danymi!
    # Inaczej migracja sie nie powiedzie (NOT NULL constraint violation)

    print("[migration] WARNING: Ensure all NULL values are filled before downgrade!")

    op.alter_column('account', 'infakt_api_key',
                    existing_type=sa.LargeBinary(),
                    nullable=False)

    op.alter_column('account', 'smtp_server',
                    existing_type=sa.String(100),
                    nullable=False)

    op.alter_column('account', 'smtp_port',
                    existing_type=sa.Integer(),
                    nullable=False)

    op.alter_column('account', 'smtp_username',
                    existing_type=sa.LargeBinary(),
                    nullable=False)

    op.alter_column('account', 'smtp_password',
                    existing_type=sa.LargeBinary(),
                    nullable=False)

    op.alter_column('account', 'email_from',
                    existing_type=sa.String(200),
                    nullable=False)

    print("[migration] Account fields are now NOT NULL again")
