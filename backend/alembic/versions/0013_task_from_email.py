"""המייל שממנו נוצרה המשימה (שלב 4-5)

עמודה אחת ב-``tasks``: ``email_message_id``, מזהה המייל של גוגל. ממנו
נבנה הקישור חזרה לג'ימייל במסך המשימה, וממנו יודעים שהמשימה הגיעה ממייל
מסוים ולא רק ש-``source`` הוא ``email``.

⚠️ **מזהה בלבד, ולא תוכן.** לא נושא, לא גוף, לא נמענים ולא קבצים — בדיוק
כמו ``bot_messages.listed_email_ids`` משלב 4-2. הכותרת וההערות שנשמרות
במשימה הן מה שהמשתמש אישר בטופס לפני השמירה, ולא העתק של המייל. זה מה
שכתוב ב-``frontend/public/privacy.html``, ושינוי כאן מחייב לעדכן גם אותו.

⚠️ **מחרוזת ולא מספר:** מזהה של גוגל הוא הקסדצימלי (``19a3f2c...``).

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("email_message_id", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "email_message_id")
