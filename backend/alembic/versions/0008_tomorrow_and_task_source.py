"""מסגרת זמן "מחר", והחלפת from_bot בעמודת source

שני שינויים שנולדו יחד בתצוגת שורת המשימה:

‏1. נוספת מסגרת הזמן tomorrow, בין today ל-week. ‏priority_set_on זוכרת
   באיזה יום התיוג נקבע, כדי שלולאת הרקע תדע להעביר "מחר" ל"היום" ביום
   שאחרי — ולא חמש דקות אחרי שתייגת.

‏2. ‏from_bot הייתה בוליאנית, ולכן לא יכלה לתאר מקור שלישי. ‏source היא
   מחרוזת, ולכן מייל או קלוד בעתיד הם ערך נוסף ולא מיגרציה מבנית.

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None

OLD_PRIORITIES = ('today', 'week', 'later')
NEW_PRIORITIES = ('today', 'tomorrow', 'week', 'later')
SOURCES = ('whatsapp', 'dashboard', 'email', 'claude')

PRIORITY_TABLES = (("tasks", "task_priority"), ("recurrences", "recurrence_priority"))


def _priority_constraint(allowed: tuple[str, ...]) -> None:
    """מחליף את אילוץ העדיפות בשתי הטבלאות ברשימת הערכים המבוקשת."""
    values = ", ".join(f"'{v}'" for v in allowed)
    for table, constraint in PRIORITY_TABLES:
        op.drop_constraint(constraint, table, type_='check')
        op.create_check_constraint(constraint, table, f"priority IN ({values})")


def upgrade() -> None:
    _priority_constraint(NEW_PRIORITIES)

    # היום שבו נקבע התיוג. במשימות קיימות אין מידע כזה, ולכן יום היצירה
    # הוא הקירוב הטוב ביותר — וממילא אין עדיין משימות שתויגו "מחר"
    op.add_column('tasks', sa.Column('priority_set_on', sa.Date(), nullable=True))
    op.execute("UPDATE tasks SET priority_set_on = created_at::date")

    op.add_column(
        'tasks',
        sa.Column('source', sa.String(length=20), nullable=False, server_default='dashboard'),
    )
    op.execute("UPDATE tasks SET source = 'whatsapp' WHERE from_bot")
    values = ", ".join(f"'{v}'" for v in SOURCES)
    op.create_check_constraint('task_source', 'tasks', f"source IN ({values})")
    op.drop_column('tasks', 'from_bot')


def downgrade() -> None:
    op.add_column(
        'tasks',
        sa.Column('from_bot', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute("UPDATE tasks SET from_bot = true WHERE source = 'whatsapp'")
    op.drop_constraint('task_source', 'tasks', type_='check')
    op.drop_column('tasks', 'source')

    op.drop_column('tasks', 'priority_set_on')

    # את האילוץ צריך להסיר לפני העדכון, אחרת הערך החדש נדחה
    for table, constraint in PRIORITY_TABLES:
        op.drop_constraint(constraint, table, type_='check')
        op.execute(f"UPDATE {table} SET priority = 'today' WHERE priority = 'tomorrow'")
    values = ", ".join(f"'{v}'" for v in OLD_PRIORITIES)
    for table, constraint in PRIORITY_TABLES:
        op.create_check_constraint(constraint, table, f"priority IN ({values})")
