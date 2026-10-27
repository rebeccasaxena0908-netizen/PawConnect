"""mobile number becomes optional – sign-up is verified by e-mail now

The UNIQUE constraint stays: a number can belong to one account only, but
any number of accounts may leave it empty (NULL values never clash).

Revision ID: 0002
Revises: 0001
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # batch_alter_table rebuilds the table on SQLite (which can't ALTER a column);
    # on PostgreSQL it is a plain ALTER TABLE ... DROP NOT NULL.
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("mobile", existing_type=sa.String(length=10), nullable=True)


def downgrade() -> None:
    missing = op.get_bind().execute(sa.text("SELECT COUNT(*) FROM users WHERE mobile IS NULL")).scalar()
    if missing:
        raise RuntimeError(f"{missing} account(s) have no mobile number – add one before downgrading.")
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("mobile", existing_type=sa.String(length=10), nullable=False)
