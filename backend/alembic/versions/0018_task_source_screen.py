"""מקור חדש למשימה: screen — נוצרה מהצ'אט שבמסך הוואטסאפ

עד עכשיו כל משימה שהבוט יצר נרשמה כ-``whatsapp``, כי זה היה הערוץ
היחיד. מאז מסך הוואטסאפ (מיגרציה 0017) יש שניים, ו⚠️ **האייקון
ברשימת המשימות אמר «מוואטסאפ» על משימה שנוצרה מול המסך** — כלומר
השדה שנועד לענות על «מאיפה זה הגיע» ענה תשובה שגויה.

⚠️ **רק הגבלת הערכים משתנה; שום שורה קיימת אינה נוגעת.** משימה
שנוצרה לפני השינוי באמת הגיעה מוואטסאפ, ואין דרך — ולא סיבה — לשנות
אותה בדיעבד.

⚠️ **התחייבות חוזרת נשארת ``whatsapp``**: ``recurrences`` אינה שומרת
באיזה ערוץ היא נרשמה, ולכן המחזורים שהיא מייצרת אינם יודעים זאת. זה
גבול ידוע ולא פספוס.

Revision ID: 0018
Revises: 0017
"""

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

OLD = ("whatsapp", "dashboard", "email", "claude")
NEW = (*OLD, "screen")


def _constraint(values) -> None:
    op.drop_constraint("task_source", "tasks", type_="check")
    joined = ", ".join(f"'{value}'" for value in values)
    op.create_check_constraint("task_source", "tasks", f"source IN ({joined})")


def upgrade() -> None:
    _constraint(NEW)


def downgrade() -> None:
    # ⚠️ חזרה אחורה חייבת להחזיר את השורות החדשות למקור מוכר, אחרת
    # ההגבלה לא תוכל להיווצר. ``whatsapp`` הוא מה שהן היו לפני השינוי
    op.execute("UPDATE tasks SET source = 'whatsapp' WHERE source = 'screen'")
    _constraint(OLD)
