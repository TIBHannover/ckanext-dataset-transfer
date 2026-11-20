"""add RADAR OAuth token and state tables

Revision ID: 8c7e4d91a2f0
Revises: cbbd92b9ccbf
Create Date: 2026-11-20
"""

from alembic import op
import sqlalchemy as sa


revision = "8c7e4d91a2f0"
down_revision = "cbbd92b9ccbf"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "radar_oauth_token",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "ckan_user_id",
            sa.UnicodeText(),
            sa.ForeignKey("user.id"),
            nullable=False,
        ),
        sa.Column("radar_environment", sa.UnicodeText(), nullable=False),
        sa.Column("access_token_encrypted", sa.UnicodeText(), nullable=False),
        sa.Column("refresh_token_encrypted", sa.UnicodeText(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column(
            "requires_reauthentication",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.UniqueConstraint(
            "ckan_user_id",
            "radar_environment",
            name="uq_radar_oauth_token_user_environment",
        ),
    )
    op.create_table(
        "radar_oauth_state",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "ckan_user_id",
            sa.UnicodeText(),
            sa.ForeignKey("user.id"),
            nullable=False,
        ),
        sa.Column("radar_environment", sa.UnicodeText(), nullable=False),
        sa.Column("state_hash", sa.UnicodeText(), nullable=False, unique=True),
        sa.Column("session_binding_hash", sa.UnicodeText(), nullable=False),
        sa.Column("code_verifier_encrypted", sa.UnicodeText(), nullable=True),
        sa.Column("dataset_name", sa.UnicodeText(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=False), nullable=True),
    )


def downgrade():
    op.drop_table("radar_oauth_state")
    op.drop_table("radar_oauth_token")
