"""v0 extras: predictions.rationale + task_events scheduling fields

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-25 00:00:00.000000

The initial spec schema is faithful to CADEN.md but elides two operational
columns the v0 residual loop cannot run without:

  - predictions.rationale  : the LLM's short explanation of the bundle. Spec
    forbids us silently throwing that away; we mirror it into events anyway,
    but having it on the structured row keeps the data path symmetrical.
  - task_events.planned_start / planned_end / actual_end : the times the
    scheduler chose for a chunk and (later) when Sean finished it. Without
    these the residual computation has no anchor for "where the block was"
    versus "where it ended up", so duration residuals cannot be produced.

Both additions are loud (NOT NULL where they are guaranteed, NULL where they
are filled in later by completion). The change is backwards compatible: empty
rows simply do not exist on a freshly-built v0 DB.
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE predictions ADD COLUMN rationale TEXT")
    op.execute("ALTER TABLE task_events ADD COLUMN planned_start TEXT")
    op.execute("ALTER TABLE task_events ADD COLUMN planned_end TEXT")
    op.execute("ALTER TABLE task_events ADD COLUMN actual_end TEXT")


def downgrade() -> None:
    pass
