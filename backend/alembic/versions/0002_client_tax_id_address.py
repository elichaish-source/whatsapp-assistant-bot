"""ת"ז/ח"פ וכתובת ללקוח

Revision ID: 0002
Revises: 0001
"""

from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('clients', sa.Column('tax_id', sa.String(length=20), nullable=True))
    op.add_column('clients', sa.Column('address', sa.String(length=300), nullable=True))


def downgrade() -> None:
    op.drop_column('clients', 'address')
    op.drop_column('clients', 'tax_id')
