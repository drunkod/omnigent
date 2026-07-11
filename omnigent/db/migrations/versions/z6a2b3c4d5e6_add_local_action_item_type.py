"""Allow persisted local-action audit items."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "z6a2b3c4d5e6"
down_revision: str | None = "z5a2b3c4d5e6"
branch_labels: tuple[str, ...] | None = None
depends_on: tuple[str, ...] | None = None


def upgrade() -> None:
    with op.batch_alter_table("conversation_items") as batch_op:
        batch_op.drop_constraint("ck_conversation_items_type", type_="check")
        batch_op.create_check_constraint(
            "ck_conversation_items_type",
            "type IN (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12)",
        )


def downgrade() -> None:
    with op.batch_alter_table("conversation_items") as batch_op:
        batch_op.drop_constraint("ck_conversation_items_type", type_="check")
        batch_op.create_check_constraint(
            "ck_conversation_items_type",
            "type IN (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11)",
        )
