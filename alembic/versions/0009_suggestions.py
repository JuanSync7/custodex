"""add the suggestions table for the AGT-06 background-suggester inbox.

ADDITIVE migration mirroring ``custodex.server.db.SuggestionRow`` 1:1: one row
per ``(repo_id, key)`` worker suggestion (unique constraint — reconciliation
UPDATES in place, never duplicates). ``suggestion`` is the full
``StoredSuggestion`` JSON envelope (the K6 source of truth, via the SAME
``_json_type`` the model uses); ``repo_id`` / ``key`` / ``status`` are the
indexed projection the reconcile + inbox reads use. Lifecycle rides in
``status``: ``pending`` (current reality) / ``resolved`` (disappeared from a
later tick — audit trail) / ``dismissed`` (the durable human 'no', never
resurrected). ``upgrade`` creates it; ``downgrade`` drops it (the up/down
round-trip is gate-tested on temp SQLite).

Revision ID: 0009_suggestions
Revises: 0008_graph_snapshots
Create Date: 2026-07-06

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from custodex.server.db import _json_type

# revision identifiers, used by Alembic.
revision: str = "0009_suggestions"
down_revision: str | None = "0008_graph_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "suggestions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("repo_id", sa.String(), nullable=False, index=True),
        sa.Column("key", sa.String(), nullable=False, index=True),
        sa.Column("status", sa.String(), nullable=False, index=True),
        sa.Column("suggestion", _json_type(), nullable=False),
        sa.UniqueConstraint("repo_id", "key", name="uq_suggestion_key"),
    )


def downgrade() -> None:
    op.drop_table("suggestions")
