"""Add account_id to Invoice for direct multi-tenancy support

Revision ID: 2025120200_inv_acc
Revises: 2025120101_notnull
Create Date: 2025-12-02

Ta migracja:
1. Dodaje kolumnę account_id do Invoice (nullable na start)
2. USUWA orphaned invoices (case_id IS NULL) - dane bez kontekstu tenanta
3. Wypełnia account_id z powiązanego Case (UPDATE...FROM PostgreSQL)
4. Zmienia account_id na NOT NULL
5. Dodaje index i FK constraint

CRITICAL: Po tej migracji Invoice będzie miał bezpośredni account_id
i zostanie zarejestrowany w TENANT_MODELS dla automatycznego filtrowania.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = '2025120200_inv_acc'
down_revision = '2025120101_notnull'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # 1. Dodaj kolumnę account_id (nullable na start)
    op.add_column('invoice', sa.Column('account_id', sa.Integer(), nullable=True))
    print("[migration] Dodano kolumnę invoice.account_id (nullable)")

    # 2. NAJPIERW usuń orphany (sanitization) - PRZED constraint
    orphan_count = conn.execute(
        text("SELECT COUNT(*) FROM invoice WHERE case_id IS NULL")
    ).scalar()

    if orphan_count > 0:
        print(f"[migration] Znaleziono {orphan_count} orphaned invoices (case_id IS NULL)")
        print(f"[migration] Usuwanie orphanów - nie mają kontekstu tenanta...")
        conn.execute(text("DELETE FROM invoice WHERE case_id IS NULL"))
        print(f"[migration] Usunięto {orphan_count} orphaned invoices")
    else:
        print("[migration] Brak orphaned invoices - OK")

    # 3. Wypełnij account_id z Case (PostgreSQL UPDATE...FROM)
    result = conn.execute(text("""
        UPDATE invoice
        SET account_id = c.account_id
        FROM "case" c
        WHERE invoice.case_id = c.id
    """))
    updated_count = result.rowcount
    print(f"[migration] Zaktualizowano {updated_count} faktur z account_id z Case")

    # 4. Sprawdź czy wszystkie faktury mają account_id
    null_check = conn.execute(
        text("SELECT COUNT(*) FROM invoice WHERE account_id IS NULL")
    ).scalar()

    if null_check > 0:
        # Nie powinno się zdarzyć, ale obsłuż gracefully
        print(f"[migration] UWAGA: {null_check} faktur nadal ma NULL account_id")
        print(f"[migration] Usuwanie - faktury z case_id ale bez account_id w Case")
        conn.execute(text("DELETE FROM invoice WHERE account_id IS NULL"))

    # 5. Zmień na NOT NULL
    op.alter_column('invoice', 'account_id',
                    existing_type=sa.Integer(),
                    nullable=False)
    print("[migration] invoice.account_id zmienione na NOT NULL")

    # 6. Dodaj index
    op.create_index('idx_invoice_account_id', 'invoice', ['account_id'])
    print("[migration] Utworzono index idx_invoice_account_id")

    # 7. Dodaj FK constraint
    op.create_foreign_key(
        'fk_invoice_account',
        'invoice', 'account',
        ['account_id'], ['id']
    )
    print("[migration] Utworzono FK constraint fk_invoice_account")

    print("[migration] === SUKCES: Invoice ma teraz bezpośredni account_id ===")


def downgrade():
    # Usuń FK
    op.drop_constraint('fk_invoice_account', 'invoice', type_='foreignkey')
    print("[migration] Usunięto FK constraint fk_invoice_account")

    # Usuń index
    op.drop_index('idx_invoice_account_id', table_name='invoice')
    print("[migration] Usunięto index idx_invoice_account_id")

    # Usuń kolumnę
    op.drop_column('invoice', 'account_id')
    print("[migration] Usunięto kolumnę invoice.account_id")

    print("[migration] UWAGA: Orphaned invoices usunięte w upgrade() nie zostaną przywrócone")
