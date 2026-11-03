"""זיכרון ארוך-טווח: עובדות ויומן אירועים

Revision ID: 0005
Revises: 0004
"""

from alembic import op
import sqlalchemy as sa


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'memory_facts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('dimension', sa.Integer(), nullable=False),
        sa.Column('client_id', sa.Integer(), sa.ForeignKey('clients.id', ondelete='CASCADE'), nullable=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('source', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint('dimension BETWEEN 1 AND 9', name='memory_fact_dimension'),
        sa.CheckConstraint("source IN ('bot', 'dashboard')", name='memory_fact_source'),
    )
    # הבלוק שנשלח לבוט נשלף בכל הודעה, לפי הממדים שנכנסים אליו
    op.create_index('memory_facts_dimension_idx', 'memory_facts', ['dimension'])

    op.create_table(
        'observations',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('kind', sa.String(length=40), nullable=False),
        sa.Column('source', sa.String(length=20), nullable=False),
        sa.Column('task_id', sa.Integer(), sa.ForeignKey('tasks.id', ondelete='SET NULL'), nullable=True),
        sa.Column('client_id', sa.Integer(), sa.ForeignKey('clients.id', ondelete='SET NULL'), nullable=True),
        sa.Column('detail', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('observations_kind_idx', 'observations', ['kind'])

    op.add_column('bot_messages', sa.Column('memory_used', sa.Text(), nullable=True))
    op.add_column(
        'bot_messages',
        sa.Column('fact_id', sa.Integer(), sa.ForeignKey('memory_facts.id', ondelete='SET NULL'), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('bot_messages', 'fact_id')
    op.drop_column('bot_messages', 'memory_used')
    op.drop_index('observations_kind_idx', table_name='observations')
    op.drop_table('observations')
    op.drop_index('memory_facts_dimension_idx', table_name='memory_facts')
    op.drop_table('memory_facts')
