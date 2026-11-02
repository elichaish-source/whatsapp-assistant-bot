"""יומן הודעות הבוט, וסימון תזכורת שנשלחה

Revision ID: 0003
Revises: 0002
"""

from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('tasks', sa.Column('reminder_sent_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        'tasks',
        sa.Column('from_bot', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        'bot_messages',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('wa_message_id', sa.String(length=200), nullable=False),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('intent', sa.String(length=40), nullable=True),
        sa.Column('reply', sa.Text(), nullable=True),
        sa.Column('task_id', sa.Integer(), sa.ForeignKey('tasks.id', ondelete='SET NULL'), nullable=True),
        sa.Column('listed_task_ids', sa.Text(), nullable=True),
        sa.Column('input_tokens', sa.Integer(), nullable=True),
        sa.Column('output_tokens', sa.Integer(), nullable=True),
        sa.Column('cached_tokens', sa.Integer(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('wa_message_id', name='bot_messages_wa_message_id_key'),
    )
    # התזכורות נשלפות לפי הסינון הזה כל כמה שניות
    op.create_index(
        'ix_tasks_pending_reminder',
        'tasks',
        ['reminder_at'],
        postgresql_where=sa.text("status = 'open' AND reminder_sent_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index('ix_tasks_pending_reminder', table_name='tasks')
    op.drop_table('bot_messages')
    op.drop_column('tasks', 'from_bot')
    op.drop_column('tasks', 'reminder_sent_at')
