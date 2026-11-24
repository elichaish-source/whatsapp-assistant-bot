"""על מה הבוט כבר התריע (שלב 4-6)

טבלה אחת, ``email_alerts``: מזהה שרשור, סוג ההתראה, ומתי יצאה.

⚠️⚠️ **בלעדיה הבוט היה מתריע על אותו שרשור בכל סבב, כל יום, לנצח.**
התראה שחוזרת היא רעש, והמשתמש מפסיק לקרוא אותה — וזה הכשל שהורג את
כל היכולת.

⚠️ **מזהים בלבד, ולא תוכן.** אין כאן נושא, גוף, שולח או נמען — בדיוק
כמו ``bot_messages.listed_email_ids`` ו-``tasks.email_message_id``.
ההבטחה ב-``frontend/public/privacy.html`` נשארת, ובדיקת התוכן עוברת.

⚠️ **מחרוזת ולא מספר:** מזהה שרשור של גוגל הוא הקסדצימלי.

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "google_credentials", sa.Column("last_digest_on", sa.Date(), nullable=True)
    )
    op.create_table(
        "email_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("thread_id", sa.String(length=100), nullable=False),
        # ‏waiting = מישהו מחכה לתשובה ממך; silent = מישהו לא ענה לך
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("alerted_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('waiting', 'silent')", name="email_alert_kind"),
        sa.UniqueConstraint("thread_id", "kind", name="email_alert_once"),
    )


def downgrade() -> None:
    op.drop_table("email_alerts")
    op.drop_column("google_credentials", "last_digest_on")
