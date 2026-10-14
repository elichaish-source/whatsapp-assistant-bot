"""initial schema

Revision ID: 0001
Revises: 
"""

from alembic import op
import sqlalchemy as sa


revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('auth_sessions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('phone', sa.String(length=30), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_table('client_families',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('clients',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('phone', sa.String(length=30), nullable=True),
    sa.Column('email', sa.String(length=200), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('domains',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('requires_client', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('login_codes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('phone', sa.String(length=30), nullable=False),
    sa.Column('code_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_login_codes_phone'), 'login_codes', ['phone'], unique=False)
    op.create_table('task_types',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('client_family_links',
    sa.Column('client_id', sa.Integer(), nullable=False),
    sa.Column('family_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['family_id'], ['client_families.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('client_id', 'family_id')
    )
    op.create_table('projects',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('domain_id', sa.Integer(), nullable=False),
    sa.Column('client_id', sa.Integer(), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('active', 'done')", name='project_status'),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['domain_id'], ['domains.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('tasks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=500), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('done_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('domain_id', sa.Integer(), nullable=False),
    sa.Column('task_type_id', sa.Integer(), nullable=True),
    sa.Column('client_id', sa.Integer(), nullable=True),
    sa.Column('project_id', sa.Integer(), nullable=True),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('reminder_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('priority', sa.String(length=10), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("priority IN ('low', 'normal', 'high')", name='task_priority'),
    sa.CheckConstraint("status IN ('open', 'done')", name='task_status'),
    sa.ForeignKeyConstraint(['client_id'], ['clients.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['domain_id'], ['domains.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['task_type_id'], ['task_types.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )

    # רשימות התחלתיות (ניתנות לעריכה מהדשבורד)
    families = sa.table("client_families", sa.column("name"), sa.column("sort_order"))
    op.bulk_insert(families, [
        {"name": "יעדים", "sort_order": 1},
        {"name": "עסק פרטי", "sort_order": 2},
        {"name": "נדל\"ן", "sort_order": 3},
    ])
    domains = sa.table("domains", sa.column("name"), sa.column("sort_order"), sa.column("requires_client"))
    op.bulk_insert(domains, [
        {"name": "לקוחות", "sort_order": 1, "requires_client": True},
        {"name": "כספים", "sort_order": 2, "requires_client": False},
        {"name": "שיווק ומכירות", "sort_order": 3, "requires_client": False},
        {"name": "פיתוח", "sort_order": 4, "requires_client": False},
        {"name": "אישי/בית", "sort_order": 5, "requires_client": False},
    ])
    task_types = sa.table("task_types", sa.column("name"), sa.column("sort_order"))
    op.bulk_insert(task_types, [
        {"name": "טלפון", "sort_order": 1},
        {"name": "פגישה", "sort_order": 2},
        {"name": "מחשב", "sort_order": 3},
    ])


def downgrade() -> None:
    op.drop_table('tasks')
    op.drop_table('projects')
    op.drop_table('client_family_links')
    op.drop_table('task_types')
    op.drop_index(op.f('ix_login_codes_phone'), table_name='login_codes')
    op.drop_table('login_codes')
    op.drop_table('domains')
    op.drop_table('clients')
    op.drop_table('client_families')
    op.drop_table('auth_sessions')
