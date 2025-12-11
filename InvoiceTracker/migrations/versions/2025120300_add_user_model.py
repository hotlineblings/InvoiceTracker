"""Add User model and account_users association table

Revision ID: 2025120300_user
Revises: 2025120200_inv_acc
Create Date: 2025-12-03

Ta migracja:
1. Tworzy tabele 'user' z email/password_hash/is_active/timestamps
2. Tworzy tabele asocjacyjna 'account_users' (M:N User<->Account)
3. NIE tworzy poczatkowego admina - obslugiwane przez CLI (flask create-admin)

MULTI-TENANCY: User moze miec dostep do wielu Accounts.
Powiazanie w account_users oznacza pelny dostep do profilu.
"""
from alembic import op
import sqlalchemy as sa


revision = '2025120300_user'
down_revision = '2025120200_inv_acc'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Tabela user
    op.create_table(
        'user',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('last_login_at', sa.DateTime(), nullable=True),
    )
    print("[migration] Created 'user' table")

    # 2. Unique index on email
    op.create_index('ix_user_email', 'user', ['email'], unique=True)
    print("[migration] Created unique index on user.email")

    # 3. Tabela asocjacyjna account_users
    op.create_table(
        'account_users',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('account.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    print("[migration] Created 'account_users' association table")

    print("=" * 60)
    print("[migration] SUCCESS: User model ready")
    print("[migration] Run 'flask create-admin' to create initial admin user")
    print("=" * 60)


def downgrade():
    op.drop_table('account_users')
    print("[migration] Dropped 'account_users' table")

    op.drop_index('ix_user_email', table_name='user')
    op.drop_table('user')
    print("[migration] Dropped 'user' table")
