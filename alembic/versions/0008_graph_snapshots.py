"""add the graph_snapshots table for the AGT-03 knowledge-graph mirror.

ADDITIVE migration mirroring ``custodex.server.db.GraphSnapshotRow`` 1:1 — the
exact ``coverage_snapshots`` pattern: the knowledge graph is computed REPO-SIDE
(where the doc bodies live, K2) by ``cdx graph`` / ``kgraph.build_graph`` and
pushed to the hub as an OPAQUE versioned JSON snapshot; the hub stores it and
serves the latest on ``GET /repos/{id}/graph``, never re-deriving from bodies
it does not hold. ``snapshot`` is the full ``KnowledgeGraph`` wire dict (the K6
source of truth, via the SAME ``_json_type`` the model uses); ``repo_id`` and
``captured_at`` are the indexed projection. ``upgrade`` creates it;
``downgrade`` drops it (the up/down round-trip is gate-tested on temp SQLite).

Revision ID: 0008_graph_snapshots
Revises: 0007_doc_edges
Create Date: 2026-07-02

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from custodex.server.db import _json_type

# revision identifiers, used by Alembic.
revision: str = "0008_graph_snapshots"
down_revision: str | None = "0007_doc_edges"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "graph_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("repo_id", sa.String(), nullable=False, index=True),
        sa.Column("captured_at", sa.String(), nullable=False, index=True),
        sa.Column("snapshot", _json_type(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("graph_snapshots")
