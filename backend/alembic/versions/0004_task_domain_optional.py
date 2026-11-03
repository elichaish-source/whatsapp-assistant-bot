"""תחום של משימה הופך לרשות

Revision ID: 0004
Revises: 0003
"""

from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column('tasks', 'domain_id', existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    # חזרה אחורה דורשת שלכל משימה יהיה תחום. משימות בלי תחום משויכות
    # לתחום הראשון לפי סדר התצוגה, כי אי אפשר להחזיר NOT NULL עם ערכים ריקים
    op.execute(
        """
        UPDATE tasks SET domain_id = (
            SELECT id FROM domains ORDER BY sort_order, id LIMIT 1
        ) WHERE domain_id IS NULL
        """
    )
    op.execute("DELETE FROM tasks WHERE domain_id IS NULL")
    op.alter_column('tasks', 'domain_id', existing_type=sa.Integer(), nullable=False)
