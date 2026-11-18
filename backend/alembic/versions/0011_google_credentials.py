"""החיבור לחשבון גוגל: טוקנים מוצפנים ומצב החיבור

טבלה אחת עם שורה אחת לכל היותר. שני הטוקנים נשמרים מוצפנים, והמפתח
יושב ב-.env בלבד — כך שגיבוי של בסיס הנתונים אינו מכיל גישה לתיבה.

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "google_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False, server_default=""),
        sa.Column("refresh_token_enc", sa.Text(), nullable=False),
        sa.Column("access_token_enc", sa.Text(), nullable=False, server_default=""),
        sa.Column("access_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="connected"),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disconnected_notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('connected', 'disconnected')", name="google_status"),
    )


def downgrade() -> None:
    op.drop_table("google_credentials")
