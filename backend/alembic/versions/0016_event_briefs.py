"""על איזו פגישה הבוט כבר תדרך (שלב 4ב-3)

טבלה אחת, ``event_briefs``: מזהה האירוע ומתי יצא התדריך.

⚠️⚠️ **בלעדיה התדריך היה יוצא בכל סבב של הלולאה** — כל חמש דקות
באותן 45 הדקות שלפני הפגישה, כלומר תשע הודעות על פגישה אחת. זה אותו
שיקול של ``email_alerts`` ב-4-6, ומאותה סיבה: התראה שחוזרת היא רעש,
והמשתמש מפסיק לקרוא אותה.

⚠️ **מזהי אירוע בלבד, ולא תוכן.** אין כאן כותרת, שעה, מקום או משתתפים
— בדיוק כמו ``email_alerts.thread_id`` ו-``tasks.email_message_id``.
תוכן היומן אינו משוקף למסד, וההבטחה ב-``frontend/public/privacy.html``
נשארת כפי שהיא.

⚠️ **מחרוזת ולא מספר:** מזהה אירוע של גוגל הוא מחרוזת, ואורכו אינו
מובטח — 200 תווים הם מרחב ולא מידה שנמדדה.

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "event_briefs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(length=200), nullable=False),
        sa.Column("briefed_at", sa.DateTime(timezone=True), nullable=False),
        # ⚠️ **זה מה שאוכף "תדריך אחד לכל פגישה"**, ולא התנאי שבקוד:
        # גם אם מישהו יסיר את הבדיקה, המסד לא ייתן לשלוח פעמיים
        sa.UniqueConstraint("event_id", name="event_brief_once"),
    )


def downgrade() -> None:
    op.drop_table("event_briefs")
