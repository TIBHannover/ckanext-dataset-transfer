"""create_api_token_table

Revision ID: cbbd92b9ccbf
Revises: 0fd2a18e3d6a
Create Date: 2022-06-24 12:40:16.757343

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'cbbd92b9ccbf'
down_revision = '0fd2a18e3d6a'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'publish_api_token',
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('api_token', sa.UnicodeText(), nullable=False),
        sa.Column('user_id', sa.UnicodeText(), sa.ForeignKey('user.id'), nullable=False),
        sa.Column('target_ckan', sa.UnicodeText()),
        sa.Column('created_at', sa.DateTime(timezone=False), nullable=False)
    )


def downgrade():
    op.drop_table('publish_api_token')

