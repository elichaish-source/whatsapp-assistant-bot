"""הערוץ שבו נכתבה ההודעה, והודעות שהמערכת יוזמת (מסך הוואטסאפ)

שלוש עמודות ב-``bot_messages``:

``channel`` — ``whatsapp`` או ``screen``.
⚠️⚠️ **זה תנאי לשלב ולא פרט טכני.** המספור ("סיימתי 2") והאישור ("כן")
נפתרים היום מול **ההודעה הקודמת**, בלי קשר לאיפה היא נכתבה. ברגע שיש
מסך, הודעה שנכתבה בו הופכת ל"הקודמת" — ואז "סיימתי 2" שהוקלד בוואטסאפ
נפתר מול רשימה שהמשתמש ראה במסך, כלומר **סוגר את המשימה הלא נכונה,
בשקט**. אחרי המיגרציה כל פותר כזה מסנן לפי אותו ערוץ.
⚠️ ברירת המחדל לשורות קיימות היא ``whatsapp``, אחרת כל ההיסטוריה
נראית כאילו נכתבה במסך.

``initiated`` — האם המערכת יזמה את ההודעה (תזכורת, סיכום, התראה,
תדריך) ולא המשתמש. עד היום הודעות כאלה לא נרשמו בכלל, ולכן המסך לא
יכול היה להראות אותן ולא היה שום מקום שאומר "על זה התרעתי ולא טיפלת".
⚠️ **השורות האלה חייבות להיות מסומנות ולא רק ריקות מגוף**, כי כל פותר
שמסתכל על "ההודעה הקודמת" חייב לדלג עליהן: תזכורת שנחתה בין השאלה
"למחוק?" לבין "כן" הייתה מבטלת את האישור.

``handled_at`` — מתי סימנת שההתראה טופלה. ⚠️ **זה המושג שלא היה קיים**:
בלעדיו הלשונית "התראות שלא טופלו" אינה יכולה להבדיל בין מה שנשלח למה
שעוד פתוח. הסימון הוא לחיצה מפורשת במסך ולא ניחוש של המערכת.

⚠️ **אין כאן שום תוכן חדש מגוגל.** מה שנשמר בשורה יוזמת הוא הטקסט
שיצא בוואטסאפ, ובתדריך הוא נשמר **בלי שורת הכותרת** — כותרת הפגישה
והשעה אינן נשמרות, כפי שמובטח ב-``frontend/public/privacy.html``.

Revision ID: 0017
Revises: 0016
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ‏server_default כדי שהשורות הקיימות יקבלו ערך, והוא נשאר על
    # העמודה: שורה שנוצרת בלי ערך מפורש היא הודעת וואטסאפ
    op.add_column(
        "bot_messages",
        sa.Column("channel", sa.String(length=20), nullable=False, server_default="whatsapp"),
    )
    op.add_column(
        "bot_messages",
        sa.Column("initiated", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("bot_messages", sa.Column("handled_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "bot_message_channel", "bot_messages", "channel IN ('whatsapp', 'screen')"
    )


def downgrade() -> None:
    op.drop_constraint("bot_message_channel", "bot_messages", type_="check")
    op.drop_column("bot_messages", "handled_at")
    op.drop_column("bot_messages", "initiated")
    op.drop_column("bot_messages", "channel")
