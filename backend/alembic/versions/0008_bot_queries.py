"""שליפה חופשית: משתמש קריאה-בלבד, והשאילתה נשמרת בהודעה

‏⚠️ המשתמש נוצר רק אם BOT_READONLY_PASSWORD קיים בסביבה. בלעדיו המיגרציה
עוברת בלי ליצור אותו, והשאילתות רצות דרך המשתמש הרגיל בעסקה לקריאה בלבד.
זה מכוון: אותו דפוס של מפתחות הבוט — בלי המפתח היכולת מצומצמת, ולא
שהמערכת לא עולה.

ההרשאות ניתנות במפורש, טבלה-טבלה. אין GRANT על הסכימה כולה ואין
‏ALTER DEFAULT PRIVILEGES, כדי שטבלה חדשה שתיווצר בעתיד **לא** תהיה
גלויה לבוט מעצם קיומה. הרחבת הרשימה היא החלטה שמישהו צריך לקבל.

Revision ID: 0008
Revises: 0007
"""

import os

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

ROLE = "assistant_ro"

# הטבלאות שהבוט רשאי לשלוף מהן. ‏login_codes, auth_sessions, memory_facts,
# observations ו-bot_messages אינן כאן, ולא במקרה
ALLOWED = ("tasks", "clients", "projects", "domains", "task_types", "recurrences")


def upgrade() -> None:
    op.add_column("bot_messages", sa.Column("query_sql", sa.Text(), nullable=True))

    password = os.environ.get("BOT_READONLY_PASSWORD", "").strip()
    if not password:
        return

    bind = op.get_bind()
    database = bind.engine.url.database
    quoted = password.replace("'", "''")

    bind.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROLE}') THEN
                    CREATE ROLE {ROLE} LOGIN PASSWORD '{quoted}';
                ELSE
                    ALTER ROLE {ROLE} LOGIN PASSWORD '{quoted}';
                END IF;
            END
            $$;
            """
        )
    )
    bind.execute(sa.text(f'GRANT CONNECT ON DATABASE "{database}" TO {ROLE}'))
    bind.execute(sa.text(f"GRANT USAGE ON SCHEMA public TO {ROLE}"))
    # קודם שלילה גורפת, ורק אחר כך מתן נקודתי. הסדר הזה חשוב: הוא מנקה
    # גם הרשאה שניתנה בעבר לטבלה שירדה מהרשימה
    bind.execute(sa.text(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {ROLE}"))
    bind.execute(sa.text(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {ROLE}"))
    for table in ALLOWED:
        bind.execute(sa.text(f"GRANT SELECT ON {table} TO {ROLE}"))


def downgrade() -> None:
    bind = op.get_bind()
    database = bind.engine.url.database
    exists = bind.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = :name"), {"name": ROLE}
    ).first()
    if exists:
        bind.execute(sa.text(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {ROLE}"))
        bind.execute(sa.text(f"REVOKE USAGE ON SCHEMA public FROM {ROLE}"))
        bind.execute(sa.text(f'REVOKE CONNECT ON DATABASE "{database}" FROM {ROLE}'))
        bind.execute(sa.text(f"DROP ROLE {ROLE}"))

    op.drop_column("bot_messages", "query_sql")
