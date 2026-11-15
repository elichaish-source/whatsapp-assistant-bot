"""הבוט משנה משימות קיימות: מצב קודם לביטול, ופעולה שמחכה לאישור

שתי עמודות ב-bot_messages, שתיהן JSON כטקסט:

‏undo_json — מצב המשימה לפני שהבוט שינה אותה. עד עכשיו "בטל" ידע רק למחוק
משימה שהבוט יצר; שינוי במשימה קיימת אי אפשר למחוק, צריך להחזיר.

‏pending_json — פעולה שהבוט שאל עליה "למחוק?" ומחכה לתשובה. ⚠️ האישור
נאכף כאן ולא במודל: "כן" מבצע רק את מה שרשום בהודעה הקודמת, והמודל אינו
יכול להחליט בעצמו מה אושר.

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bot_messages", sa.Column("undo_json", sa.Text(), nullable=True))
    op.add_column("bot_messages", sa.Column("pending_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("bot_messages", "pending_json")
    op.drop_column("bot_messages", "undo_json")
