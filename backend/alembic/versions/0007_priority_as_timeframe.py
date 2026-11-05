"""עדיפות הופכת למסגרת זמן: today / week / later

הערכים הישנים דירגו חשיבות (low/normal/high). מעכשיו הם אומרים מתי,
ולכן גם סדר המיון נשאר זהה: high היה ראשון, ו-today ראשון.

Revision ID: 0007
Revises: 0006
"""

from alembic import op

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None

# high היה "הכי דחוף", ולכן הופך ל"היום"
OLD_TO_NEW = {"high": "today", "normal": "week", "low": "later"}
NEW_TO_OLD = {new: old for old, new in OLD_TO_NEW.items()}

TABLES = (("tasks", "task_priority"), ("recurrences", "recurrence_priority"))


def _convert(mapping: dict[str, str], allowed: tuple[str, ...]) -> None:
    for table, constraint in TABLES:
        # את האילוץ צריך להסיר לפני העדכון, אחרת הערכים החדשים נדחים
        op.drop_constraint(constraint, table, type_='check')
        for old, new in mapping.items():
            op.execute(f"UPDATE {table} SET priority = '{new}' WHERE priority = '{old}'")
        values = ", ".join(f"'{v}'" for v in allowed)
        op.create_check_constraint(constraint, table, f"priority IN ({values})")


def upgrade() -> None:
    _convert(OLD_TO_NEW, ("today", "week", "later"))


def downgrade() -> None:
    _convert(NEW_TO_OLD, ("low", "normal", "high"))
