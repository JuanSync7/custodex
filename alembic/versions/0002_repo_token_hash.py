"""add repos.token_hash for per-repo bearer auth (E-06).

ADDITIVE migration mirroring ``custodex.server.db.RepoRow.token_hash``: a
nullable ``token_hash`` column on ``repos`` holding the sha256 hash of a repo's
bearer token (never the plaintext). Nullable so it is back-compatible with pre-E-06
repo rows / token-less repos (whose writes stay open). ``upgrade`` adds the column;
``downgrade`` drops it (the up/down round-trip is gate-tested on temp SQLite).

Revision ID: 0002_token_hash
Revises: 0001_initial
Create Date: 2026-06-05

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_token_hash"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("repos", sa.Column("token_hash", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("repos", "token_hash")
