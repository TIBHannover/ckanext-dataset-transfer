"""change_table_column_type

Revision ID: 0fd2a18e3d6a
Revises: 179b2d180536
Create Date: 2022-06-24 12:02:57.530231

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0fd2a18e3d6a'
down_revision = '179b2d180536'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column('published_dataset', 'publlished_dataset_id')
    op.add_column('published_dataset', sa.Column('published_dataset_id', sa.UnicodeText, nullable=True))


def downgrade():
    pass
