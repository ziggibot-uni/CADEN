"""remove task chunk columns

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-26 00:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("task_events") as batch_op:
        batch_op.drop_column("chunk_index")
        batch_op.drop_column("chunk_count")


def downgrade() -> None:
    with op.batch_alter_table("task_events") as batch_op:
        batch_op.add_column(sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="1"))
