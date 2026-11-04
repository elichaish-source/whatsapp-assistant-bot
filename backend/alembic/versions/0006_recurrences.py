"""התחייבויות חוזרות: ישות שמייצרת משימה בכל מחזור

Revision ID: 0006
Revises: 0005
"""

from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'recurrences',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('interval_unit', sa.String(length=10), nullable=False),
        sa.Column('interval_count', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('cycle', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('lead_days', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('domain_id', sa.Integer(), sa.ForeignKey('domains.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('task_type_id', sa.Integer(), sa.ForeignKey('task_types.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('client_id', sa.Integer(), sa.ForeignKey('clients.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id', ondelete='RESTRICT'), nullable=True),
        sa.Column('priority', sa.String(length=10), nullable=False, server_default='normal'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('from_bot', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("interval_unit IN ('week', 'month', 'year')", name='recurrence_unit'),
        sa.CheckConstraint('interval_count BETWEEN 1 AND 60', name='recurrence_count'),
        sa.CheckConstraint('lead_days BETWEEN 0 AND 365', name='recurrence_lead'),
        sa.CheckConstraint("priority IN ('low', 'normal', 'high')", name='recurrence_priority'),
    )
    # ‏הלולאה סורקת רק התחייבויות פעילות, בכל סבב
    op.create_index('recurrences_active_idx', 'recurrences', ['active'])

    op.add_column(
        'tasks',
        sa.Column('recurrence_id', sa.Integer(), sa.ForeignKey('recurrences.id', ondelete='SET NULL'), nullable=True),
    )
    # ‏"יש כבר מחזור פתוח?" היא השאילתה שרצה לפני כל יצירה
    op.create_index('tasks_recurrence_idx', 'tasks', ['recurrence_id'])

    op.add_column(
        'bot_messages',
        sa.Column('recurrence_id', sa.Integer(), sa.ForeignKey('recurrences.id', ondelete='SET NULL'), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('bot_messages', 'recurrence_id')
    op.drop_index('tasks_recurrence_idx', table_name='tasks')
    op.drop_column('tasks', 'recurrence_id')
    op.drop_index('recurrences_active_idx', table_name='recurrences')
    op.drop_table('recurrences')
