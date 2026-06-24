"""add repos.provider_secret for at-rest sealed git provider credentials (GIT-02).

ADDITIVE migration mirroring ``custodex.server.db.RepoRow.provider_secret``:
a nullable ``LargeBinary`` column on ``repos`` holding the AES-256-GCM SEALED bytes
of a repo's git provider credential (a PAT / project token / minted App token). It
is sealed, not hashed, because a git credential must be REPLAYED to the provider —
the conscious fork from E-06's one-way ``token_hash``. Nullable so it is
back-compatible with every pre-GIT-02 repo row (and repos that sync only a local
path, which carry no provider secret). The ``provider``/``remote_url`` identity
fields ride in the existing ``payload`` JSON column, so they need NO migration —
this adds the ONE binary column. ``upgrade`` adds it; ``downgrade`` drops it (the
up/down round-trip is gate-tested on temp SQLite via the env's batch mode).

Revision ID: 0005_provider_secret
Revises: 0004_config_edits
Create Date: 2026-06-10

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_provider_secret"
down_revision: str | None = "0004_config_edits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "repos", sa.Column("provider_secret", sa.LargeBinary(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("repos", "provider_secret")
