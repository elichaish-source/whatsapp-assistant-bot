"""מתי הוכנו טיוטות בפעם האחרונה (שלב 4-4/4-5)

שתי חותמות זמן על ``google_credentials``, לצד ``last_checked_at`` שכבר שם.

⚠️⚠️ **הן מה שמונע התחדשות בלולאה.** המטמון של הטיוטות חי בזיכרון, ולכן
הפעלה מחדש מוחקת אותו. בלי חותמת במסד, הסבב הבא היה מכין מחדש טיוטה לכל
מייל שעדיין בדואר הנכנס — ועל מענה זה מודל יקר. עם החותמת, מוכנות רק
טיוטות למיילים **שהגיעו אחריה**, והשאר נשאר ללחיצה ידנית.

⚠️ **זמנים בלבד, ולא תוכן.** אין כאן טיוטה, גוף, נושא או נמען — ההבטחה
ב-``frontend/public/privacy.html`` נשארת כמו שהיא, ובדיקת התוכן ממשיכה
לעבור.

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "google_credentials",
        sa.Column("last_prepared_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "google_credentials",
        sa.Column("last_reply_prepared_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("google_credentials", "last_reply_prepared_at")
    op.drop_column("google_credentials", "last_prepared_at")
