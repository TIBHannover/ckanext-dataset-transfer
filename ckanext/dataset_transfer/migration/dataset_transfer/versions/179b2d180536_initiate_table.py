"""initiate_table

Revision ID: 179b2d180536
Revises: 
Create Date: 2022-06-24 11:27:19.135139

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '179b2d180536'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'published_dataset',
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('dataset_id', sa.UnicodeText(), nullable=False),
        sa.Column('doi', sa.UnicodeText(), nullable=False),
        sa.Column('published_url', sa.UnicodeText()),
        sa.Column('publish_time', sa.DateTime(timezone=False), nullable=False),
        sa.Column('publlished_dataset_id', sa.DateTime(timezone=False), nullable=False),
    )


def downgrade():
    op.drop_table('published_dataset')
