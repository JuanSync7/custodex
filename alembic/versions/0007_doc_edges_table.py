"""add the config_doc_edges reverse-lookup table for doc↔doc deps (B-09).

ADDITIVE migration mirroring ``custodex.server.db.ConfigDocEdgeRow`` 1:1 — the
FLATTENED projection of every document's ``depends_on`` into a standalone, indexable
row so the central hub answers "which docs depend on X" with an indexed
``WHERE upstream_id = X`` instead of a JSON scan over every document. ``edge`` is the
FULL :class:`~custodex.server.store.StoredDocEdge` JSON (the K6 source of truth, via
the SAME ``_json_type`` the model uses); the scalar columns
(``repo_id``/``doc_id``/``upstream_id``/``sync_kind``/``type``) are the indexed
projection. ``upstream_id`` is indexed — the reverse-lookup key the table exists for.

The declarative ``depends_on`` edges ALSO ride in the EXISTING ``config_documents``
JSON column (additive, K6 — that is the per-document source of truth and needed no
migration); this table is a DERIVED index re-projected on every ``replace_config``,
so a rebuild from the documents reconstructs it. ``upgrade`` creates it; ``downgrade``
drops it (the up/down round-trip is gate-tested on temp SQLite).

Revision ID: 0007_doc_edges
Revises: 0006_roster_and_ownership
Create Date: 2026-06-30

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from custodex.server.db import _json_type

# revision identifiers, used by Alembic.
revision: str = "0007_doc_edges"
down_revision: str | None = "0006_roster_and_ownership"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "config_doc_edges",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("repo_id", sa.String(), nullable=False),
        sa.Column("doc_id", sa.String(), nullable=False),
        sa.Column("upstream_id", sa.String(), nullable=False),
        sa.Column("sync_kind", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("edge", _json_type(), nullable=False),
    )
    op.create_index("ix_config_doc_edges_repo_id", "config_doc_edges", ["repo_id"])
    op.create_index("ix_config_doc_edges_doc_id", "config_doc_edges", ["doc_id"])
    op.create_index(
        "ix_config_doc_edges_upstream_id", "config_doc_edges", ["upstream_id"]
    )
    op.create_index("ix_config_doc_edges_sync_kind", "config_doc_edges", ["sync_kind"])


def downgrade() -> None:
    op.drop_index("ix_config_doc_edges_sync_kind", table_name="config_doc_edges")
    op.drop_index("ix_config_doc_edges_upstream_id", table_name="config_doc_edges")
    op.drop_index("ix_config_doc_edges_doc_id", table_name="config_doc_edges")
    op.drop_index("ix_config_doc_edges_repo_id", table_name="config_doc_edges")
    op.drop_table("config_doc_edges")
