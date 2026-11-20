"""retained RADAR OAuth compatibility revision

Revision ID: 8c7e4d91a2f0
Revises: cbbd92b9ccbf
Create Date: 2026-11-20
"""

revision = "8c7e4d91a2f0"
down_revision = "cbbd92b9ccbf"
branch_labels = None
depends_on = None


def upgrade():
    # This revision was published before RADAR OAuth moved to temporary Redis
    # storage. Keep the revision identifier so databases already stamped at it
    # remain compatible. Fresh installations intentionally create no OAuth
    # tables and OAuth does not require this revision to be applied.
    pass


def downgrade():
    # Never drop tables automatically: a test installation may have applied
    # the original form of this revision before the Redis refactor.
    pass
