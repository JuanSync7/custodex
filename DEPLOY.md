# Deploying the code-doc-monitor central server

The central server (`cdmon-server`) ingests review records from many repos, syncs
configs, opens docs-PRs, and serves the console. This is the operator runbook for
running it for real. (For a single local repo with no central state, you don't need
any of this — just `cdmon serve`.)

## TL;DR — Docker Compose (server + Postgres)

```bash
export CDMON_ADMIN_TOKEN=$(openssl rand -hex 32)     # gates the GLOBAL roster routes
export CDMON_SECRET_KEY=$(openssl rand -base64 32)   # seals per-repo git credentials
docker compose up --build
# → console + API on http://localhost:33333  (GET /health, GET /settings)
```

On startup the server reads `$CDMON_DATABASE_URL`, runs the Alembic migrations to
head, and uses a persistent `SqlStore` — records/resolutions/coverage/roster survive a
restart. With no database URL it logs a loud warning and falls back to an in-memory
store (everything is lost on restart) — fine for a demo, never for production.

## Configuration — `config/settings.yaml` + `CDMON_*`

Non-secret runtime tunables live in `config/settings.yaml` (mounted read-only in the
compose file). Every value defaults to the historical behavior, so the file is
optional. Precedence is **environment variable > file > built-in default** (the central server
reads no CLI flags; `cdmon serve`'s own `--host`/`--port` only affect the standalone
dashboard, which keeps its localhost defaults).

| Setting (`config/settings.yaml`)         | Env override               | Default            |
|------------------------------------------|----------------------------|--------------------|
| `server.host`                            | `CDMON_SERVER_HOST`        | `0.0.0.0`          |
| `server.port`                            | `CDMON_SERVER_PORT`        | `33333`            |
| `server.log_level`                       | `CDMON_SERVER_LOG_LEVEL`   | `info`             |
| `server.trusted_hosts`                   | `CDMON_TRUSTED_HOSTS`      | `["*"]` (any host) |
| `server.cors.allow_origins`              | `CDMON_CORS_ORIGINS`       | `[]` (CORS off)    |
| `server.rate_limit.requests_per_minute`  | `CDMON_RATE_LIMIT_RPM`     | `null` (no limit)  |
| `server.git.extra_allowed_hosts`         | `CDMON_ALLOWED_GIT_HOSTS`  | `[]`               |
| `server.git.clone_timeout_seconds`       | `CDMON_GIT_CLONE_TIMEOUT`  | `null` (no timeout)|

Inspect the **effective** resolved settings any time with `cdmon settings` (or
`GET /settings`) — it prints the values above plus whether each secret is configured,
never the secret values.

### Secrets (environment only — never the file)

| Env var               | Purpose                                                         |
|-----------------------|-----------------------------------------------------------------|
| `CDMON_ADMIN_TOKEN`   | Bearer token for the GLOBAL roster routes (`POST /admin/roster*`). **Unset = those routes are OPEN** — the server warns loudly on a persistent store. Always set it in a shared deployment. |
| `CDMON_DATABASE_URL`  | `postgresql+psycopg://user:pw@host/db` — selects the persistent store + runs migrations. |
| `CDMON_SECRET_KEY`    | base64 32-byte KEK that AES-256-GCM-seals per-repo git provider credentials at rest. |

Per-repo write tokens are passed at registration and stored only as sha256 hashes.

## Hardening checklist (production)

1. **Restrict the Host header.** Set `server.trusted_hosts` (or `CDMON_TRUSTED_HOSTS`)
   to your real hostname(s) so a spoofed `Host` / DNS-rebinding is a 400.
2. **Set the admin token + KEK.** See the table above; the compose file refuses to
   start without them.
3. **Terminate TLS at a reverse proxy.** The app speaks plain HTTP; run nginx/Caddy/an
   ingress in front for TLS, and forward to `:33333`. Bind the app to `127.0.0.1` (set
   `server.host`) when the proxy is on the same host.
4. **CORS only if the console is hosted separately.** The bundled console is served
   single-origin (no CORS needed). If you host the frontend elsewhere, list its origin
   in `server.cors.allow_origins`.
5. **Rate limiting.** Set `server.rate_limit.requests_per_minute` to throttle
   brute-force of the bearer/admin tokens and clone-on-demand. **Caveat:** the limiter
   is per-process — with N uvicorn workers the effective limit is N×, and it resets on
   restart. For a hard, shared limit, enforce it at the reverse proxy instead.
6. **Cap clone-on-demand.** Set `server.git.clone_timeout_seconds` so a slow/hung
   remote can't pin a worker; add self-hosted git hosts to `server.git.extra_allowed_hosts`.

## Health & operations

- **Liveness:** `GET /health` → `{"status": "ok"}` (unauthenticated).
- **Effective config:** `GET /settings` (open, redacted) or `cdmon settings`.
- **Migrations** run automatically on startup from `$CDMON_DATABASE_URL`; to run them
  by hand: `CDMON_DATABASE_URL=... alembic upgrade head`.
- **Scaling:** the store is the only shared state, so you can run multiple replicas
  against one Postgres. Remember the rate limiter is per-replica.

## Building the image standalone

```bash
docker build -t cdmon-server .
docker run --rm -p 33333:33333 \
  -e CDMON_DATABASE_URL=postgresql+psycopg://user:pw@host/db \
  -e CDMON_ADMIN_TOKEN=... -e CDMON_SECRET_KEY=... \
  cdmon-server
```

The image builds the Astro console in a node stage and serves it single-origin, so
`GET /` returns the dashboard (and falls back to a JSON landing if the build is absent).
