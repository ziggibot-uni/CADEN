"""curated memories and memory vectors

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-26 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op


revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER REFERENCES events(id) ON DELETE CASCADE,
            memory_key TEXT NOT NULL UNIQUE,
            memory_type TEXT NOT NULL,
            source TEXT NOT NULL,
            domain TEXT NOT NULL,
            tags_json TEXT NOT NULL,
            context TEXT NOT NULL,
            outcome TEXT NOT NULL,
            hooks_json TEXT NOT NULL,
            embedding_text TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    op.execute("CREATE INDEX memories_event ON memories(event_id);")
    op.execute("CREATE INDEX memories_source ON memories(source);")

    op.execute(
        """
        CREATE TABLE memory_embeddings (
            memory_id INTEGER PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
            embedding BLOB NOT NULL
        );
        """
    )


def downgrade() -> None:
    pass