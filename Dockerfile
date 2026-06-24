# custodex central server image (EPIC SVR).
#
# Two stages: build the Astro console, then a slim Python runtime that installs the
# [server] extra and serves the API + the built console single-origin on :33333.
#
#   docker build -t cdx-server .
#   docker run --rm -p 33333:33333 -e CDMON_ADMIN_TOKEN=... cdx-server
#
# For a real deployment with Postgres + secrets, prefer `docker compose up` (see
# docker-compose.yml) and DEPLOY.md.

# ── Stage 1: build the console (frontend/dist) ───────────────────────────────
FROM node:22-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build  # astro check && astro build → /build/frontend/dist

# ── Stage 2: the Python runtime ──────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# git is needed for clone-on-demand sync + docs-PR; no recommends, clean apt cache.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Run as a non-root user (defense-in-depth).
RUN useradd --create-home --uid 10001 cdx
WORKDIR /app

# Install the package + the [server] extra. Editable so app.py stays in /app and the
# default static dir resolves to /app/frontend/dist (the relative-path contract).
COPY pyproject.toml README.md ./
COPY custodex ./custodex
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY feature-doc ./feature-doc
COPY config ./config
RUN pip install --no-cache-dir -e '.[server]'

# The console built in stage 1, where _default_static_dir() looks (parents[2]/frontend/dist).
COPY --from=frontend /build/frontend/dist ./frontend/dist

USER cdx
EXPOSE 33333

# main() binds host/port/log level from config/settings.yaml + the CDMON_* env vars.
# $CDMON_DATABASE_URL → a persistent SqlStore (else a loud-warning in-memory store).
CMD ["cdx-server"]
