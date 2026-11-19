"""המספור של רשימת המיילים האחרונה שהבוט הציג (שלב 4-2)

עמודה אחת ב-bot_messages: ``listed_email_ids``, מזהי המיילים של גוגל לפי
הסדר שבו הוצגו, מופרדים בפסיק. ככה "תראה לי את 2" בהודעה הבאה מצביע על
המייל הנכון, באותו דפוס של ``listed_task_ids``.

⚠️ **עמודה נפרדת ולא שימוש חוזר בעמודה של המשימות.** מזהה מייל של גוגל
הוא מחרוזת הקסדצימלית (``19a3f2c...``) ולא מספר שלם, ו-``_resolve_by_number``
של המשימות עושה ``int()`` על כל פריט. ערבוב היה מפיל אותו.

⚠️ **תוכן המייל עצמו אינו נשמר כאן ולא בשום מקום אחר** — לא נושא, לא גוף,
לא נמענים ולא קבצים מצורפים. רק המזהה, שבאמצעותו המייל נקרא שוב מגוגל
ברגע הבקשה. זה מה שכתוב ב-``frontend/public/privacy.html``, ושינוי כאן
מחייב לעדכן גם אותו.

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bot_messages", sa.Column("listed_email_ids", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("bot_messages", "listed_email_ids")
